"""Inventory, process and publish SPHEREx spectral images on a durable worker."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from science import bulk_catalog
from science.archive import now
from science.bulk_survey import BulkSurvey, atomic_write, message
from science.survey import canonical
from science.survey_image import ImageRejected, process_image


def finish_task(store, task, job, elapsed):
    try:
        return "success" if store.finish(job, "success", elapsed, result=task.result()) else None
    except Exception as error:
        status = "skipped" if isinstance(error, ImageRejected) else "error"
        if store.finish(job, status, elapsed, reason=message(error)):
            print(f"{job['id']} · {status} · {message(error)}", flush=True)
            return status
        return None


def process_batch(store, budget, workers):
    batch = store.begin_batch(workers, budget)
    started = time.monotonic()
    pending = {}
    submitted = 0
    counts = dict(success=0, error=0, skipped=0)
    print(f"{batch} · up to {budget} FITS images on {workers} workers", flush=True)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            try:
                while pending or submitted < budget:
                    while len(pending) < workers and submitted < budget:
                        job = store.claim(batch)
                        if job is None:
                            break
                        submitted += 1
                        task = pool.submit(process_image, job["url"], job["id"], job["detector"])
                        pending[task] = (job, time.monotonic())
                    if not pending:
                        break
                    done, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for task in done:
                        job, started_at = pending.pop(task)
                        status = finish_task(store, task, job, time.monotonic() - started_at)
                        if status:
                            counts[status] += 1
                        if status and sum(counts.values()) % 16 == 0:
                            print(f"{batch} · {counts['success']} processed · {counts['error']} errors · "
                                  f"{counts['skipped']} skips", flush=True)
            except KeyboardInterrupt:
                for task, (job, started_at) in pending.items():
                    if task.cancel():
                        store.finish(job, "interrupted", time.monotonic() - started_at, reason="Worker stopped")
                    else:
                        finish_task(store, task, job, time.monotonic() - started_at)
                raise
    finally:
        store.close_batch(batch, round(time.monotonic() - started, 3))
    return dict(successful=counts["success"], failed=counts["error"], skipped=counts["skipped"])


def write_json(path, value):
    atomic_write(path, lambda tmp: tmp.write_text(canonical(value) + "\n", encoding="utf-8"))


def run_motion_pass(store, options):
    from science.survey_motion import run_motion

    cursor_key = "motion-checkpoint:" + str(options.motion_db.resolve())
    checkpoint = int(store.setting(cursor_key) or 0)

    def new_images():
        nonlocal checkpoint
        for checkpoint, image in store.completed_since(checkpoint):
            yield image

    snapshot = run_motion(options.motion_db, new_images(), max_fields=options.motion_fields,
                          investigate=options.investigate, retry=options.retry_failed,
                          workers=options.motion_workers, mesh_degrees=options.motion_spacing_arcmin / 60,
                          on_event=lambda status, item: print(f"DeepTrace · {status} · {item}", flush=True))
    # Motion ingestion is idempotent. A crash before this cursor update safely replays the overlap.
    store.save_setting(cursor_key, checkpoint)
    return snapshot


def publish_discoveries(path, motion):
    """Keep the pilot and publish the bounded evidence records for bulk search fields."""
    if not motion or not motion["fields"]:
        return
    base = json.loads(path.read_text(encoding="utf-8"))
    motion_field_ids = set(base.get("bulkSurvey", {}).get("fieldIds", []))
    fields = [item for item in base["fields"] if item["id"] not in motion_field_ids]
    analyses = [item for item in base["analyses"] if item["fieldId"] not in motion_field_ids]
    old_motion_analysis_ids = {item["id"] for item in base["analyses"] if item["fieldId"] in motion_field_ids}
    candidates = [item for item in base["candidates"] if item["analysisId"] not in old_motion_analysis_ids]
    fields.extend(motion["fields"])
    analyses.extend(motion["analyses"])
    candidates.extend(motion["candidates"])
    exposure_ids = {image["id"] for result in analyses for image in result["observations"]}
    summary = {key: sum(item["status"] == status for item in fields)
               for key, status in (("queued", "queued"), ("running", "running"), ("complete", "complete"),
                                   ("empty", "empty"), ("incomplete", "incomplete"), ("errors", "error"))}
    summary.update(planned=len(fields), candidates=len(candidates), uniqueExposuresAnalyzed=len(exposure_ids),
                   fieldsAnalyzed=len({value["fieldId"] for value in analyses}),
                   fieldExposuresAnalyzed=sum(len(item["observations"]) for item in analyses),
                   usablePixelSamples=sum(item["usablePixelSamples"] for item in analyses),
                   trialGridPositions=sum(item["trialGridPositions"] for item in analyses),
                   elapsedSeconds=round(sum(a.get("elapsedSeconds", 0) for f in fields for a in f["history"]), 3))
    base.update(label="SPHEREx pilot and archive survey", generatedAt=now(), summary=summary,
                fields=fields, analyses=analyses, candidates=candidates,
                bulkSurvey=dict(fieldIds=[item["id"] for item in motion["fields"]], generatedAt=motion["generatedAt"]))
    write_json(path, base)


def cycle(store, options, refresh=False):
    if options.pages:
        result = bulk_catalog.discover(store, options.pages, releases=options.release or bulk_catalog.RELEASES,
                                       selected_periods=options.period, refresh=refresh)
        print("Archive inventory · " + json.dumps(result), flush=True)
    if options.images:
        print("Full-image batch · " + json.dumps(process_batch(store, options.images, options.workers)), flush=True)
    motion = None
    motion_state = options.motion_db.with_suffix(".snapshot.json")
    if options.motion_fields or options.investigate or options.publish_findings:
        motion = run_motion_pass(store, options)
        write_json(motion_state, motion)
    elif motion_state.exists():
        motion = json.loads(motion_state.read_text(encoding="utf-8"))
    if options.publish_findings:
        publish_discoveries(options.publish_findings, motion)
    if options.ledger:
        store.write_ledger(options.ledger)
    snapshot = store.snapshot(motion, ledger_url="/" + options.ledger.name if options.ledger else None)
    write_json(options.output, snapshot)
    print("Survey totals · " + json.dumps(snapshot["summary"]), flush=True)


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "work/bulk-survey.sqlite")
    parser.add_argument("--motion-db", type=Path, help="Defaults to bulk-motion.sqlite beside --db")
    parser.add_argument("--output", type=Path, default=ROOT / "work/bulk-survey.json")
    parser.add_argument("--ledger", type=Path, help="Export all image attempts as compressed JSONL")
    parser.add_argument("--publish-findings", type=Path, help="Merge published bulk findings into the existing survey JSON")
    parser.add_argument("--seed-pilot", type=Path, help="Give verified existing pilot input URLs early queue priority")
    parser.add_argument("--release", action="append", choices=bulk_catalog.RELEASES)
    parser.add_argument("--period", action="append", default=[], help="Restrict inventory to this planning period")
    parser.add_argument("--pages", type=int, default=24, help="Maximum S3 folder and object pages added per batch")
    parser.add_argument("--images", type=int, default=32, help="Maximum image attempts started per batch")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent full-image downloads and measurements")
    parser.add_argument("--motion-fields", type=int, default=2, help="Maximum automatic DeepTrace fields per batch")
    parser.add_argument("--motion-workers", type=int, choices=range(1, 9), default=2,
                        help="Concurrent multi-epoch field searches")
    parser.add_argument("--motion-spacing-arcmin", type=int, choices=(5, 10, 15, 30, 60, 90, 120), default=60,
                        help="Automatic field spacing. Use a separate --motion-db to change the mesh.")
    parser.add_argument("--investigate", type=int, default=1, help="Maximum catalog investigations per batch")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--reanalyze", action="append", default=[], metavar="OBSERVATION_ID")
    parser.add_argument("--refresh-catalog", action="store_true", help="Rescan known prefixes without resetting image work")
    parser.add_argument("--watch", type=int, default=0, metavar="SECONDS",
                        help="Run another bounded batch after this interval using the same ledger")
    opts = parser.parse_args(args)
    if (not 1 <= opts.workers <= 32 or not 0 <= opts.pages <= 2000 or not 0 <= opts.images <= 5000
            or not 0 <= opts.motion_fields <= 50 or not 0 <= opts.investigate <= 10 or opts.watch < 0):
        parser.error("Check worker, inventory-page, image, field, catalog and watch bounds.")
    if any(not re.fullmatch(r"\d{4}W\d{2}_\d[A-Z]", key) for key in opts.period):
        parser.error("Planning periods use names such as 2025W20_2D.")
    opts.motion_db = opts.motion_db or opts.db.with_name("bulk-motion.sqlite")
    store = BulkSurvey(opts.db)
    try:
        if opts.seed_pilot:
            snapshot = json.loads(opts.seed_pilot.read_text(encoding="utf-8"))
            store.seed(bulk_catalog.seed_pilot(snapshot))
        store.requeue(failed=opts.retry_failed, image_ids=opts.reanalyze)
        refresh = opts.refresh_catalog
        while True:
            last_refresh = float(store.setting("last-catalog-refresh") or 0)
            refresh = refresh or bool(opts.watch and time.time() - last_refresh > 7 * 86400)
            cycle(store, opts, refresh)
            if refresh and opts.pages:
                store.save_setting("last-catalog-refresh", time.time())
            if not opts.watch:
                return
            refresh = False
            print(f"Next bounded batch in {opts.watch}s · {datetime.now(timezone.utc).isoformat()}", flush=True)
            time.sleep(opts.watch)
    except KeyboardInterrupt:
        print("Survey stopped. Completed evidence is retained in the database.", flush=True)
    finally:
        store.close()


if __name__ == "__main__":
    main()
