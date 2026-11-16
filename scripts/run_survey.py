"""Run, resume, or export a bounded SPHEREx field survey."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from science.survey import (
    Region, SurveyConfig, SurveyStore, challenge_regions, grid_regions, publish_snapshot, run_pending,
)


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "work/survey.sqlite")
    parser.add_argument("--output", type=Path, default=ROOT / "public/survey.json")
    parser.add_argument("--name", default="SPHEREx field survey")
    parser.add_argument("--survey-id", help="Resume or export an existing immutable survey configuration")
    parser.add_argument("--challenge", action="store_true", help="Add the five reference challenge field centers")
    parser.add_argument("--field", nargs=2, type=float, action="append", metavar=("RA", "DEC"), default=[])
    parser.add_argument("--grid", nargs=5, type=float, action="append", default=[], metavar=("RA", "DEC", "ARCMIN", "COLS", "ROWS"))
    parser.add_argument("--detector", type=int, default=1)
    parser.add_argument("--fov", type=float, default=5)
    parser.add_argument("--pixels", type=int, default=64)
    parser.add_argument("--observations", type=int, default=8)
    parser.add_argument("--threshold", type=float, default=6)
    parser.add_argument("--min-gain", type=float, default=2)
    parser.add_argument("--max-fields", type=int, default=5, help="0 exports/plans only; 1–50 processes pending fields")
    parser.add_argument("--fetch-workers", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--retry", action="store_true", help="Requeue errors and incomplete fields")
    parser.add_argument("--refresh", action="store_true", help="Requeue all finished fields; keep previous analyses/history")
    parser.add_argument("--recorded-packet", type=Path, help="Optional same-field, same-grid NASA pixel fallback with explicit provenance")
    parser.add_argument("--investigate", type=int, default=0, help="Number of highest-ranked pending candidates to check against catalogs (0–10)")
    opts = parser.parse_args(args)
    if not 0 <= opts.max_fields <= 50 or not 0 <= opts.investigate <= 10:
        parser.error("Bound each invocation to 0–50 fields and 0–10 catalog investigations.")
    regions = challenge_regions() if opts.challenge else []
    regions.extend(Region(ra, dec, f"Field {ra:.5f}, {dec:+.5f}") for ra, dec in opts.field)
    for ra, dec, spacing, columns, rows in opts.grid:
        if not columns.is_integer() or not rows.is_integer():
            parser.error("Grid rows and columns must be integers.")
        regions.extend(grid_regions(ra, dec, spacing, int(columns), int(rows)))
    if not regions and not opts.survey_id:
        parser.error("Choose --challenge, --field, --grid, or an existing --survey-id.")
    if len(regions) > 4096:
        parser.error("Add up to 4096 field centers per invocation.")
    store = SurveyStore(opts.db)
    try:
        if opts.survey_id:
            existing = store.snapshot(opts.survey_id)
            config = SurveyConfig(**existing["config"])
            survey_id = store.plan(existing["label"], config, regions)
        else:
            config = SurveyConfig(fov=opts.fov, pixels=opts.pixels, detector=opts.detector,
                                  observations=opts.observations, threshold=opts.threshold, min_gain=opts.min_gain)
            survey_id = store.plan(opts.name, config, regions)
        print(f"Survey {survey_id} · persistent state {opts.db}", flush=True)
        if opts.refresh or opts.retry:
            store.requeue(survey_id, refresh=opts.refresh)
        packet = None
        if opts.recorded_packet:
            packet = json.loads(opts.recorded_packet.read_text(encoding="utf-8"))
        publish_snapshot(store, survey_id, opts.output)

        def log(field, report):
            print(f"{field['label']} · {report['status']} · {report['message']}", flush=True)
            publish_snapshot(store, survey_id, opts.output)

        run_pending(store, survey_id, config, opts.max_fields, fetch_workers=opts.fetch_workers,
                    recorded_packet=packet, on_start=lambda _: publish_snapshot(store, survey_id, opts.output), on_finish=log)
        if opts.investigate:
            from science.archive import now
            from science.catalogs import investigate
            pending = [c for c in store.snapshot(survey_id)["candidates"] if not c.get("catalogInvestigation")]
            for candidate in pending[:opts.investigate]:
                try:
                    outcome = investigate(candidate)
                except (OSError, ValueError, RuntimeError) as error:
                    message = f"Catalog investigation did not finish: {type(error).__name__}: {str(error)[:300]}"
                    outcome = dict(checkedAt=now(), classification="insufficient-evidence", reasons=[message],
                                   hypotheses=[], warnings=[message], status="error")
                store.record_investigation(candidate["id"], outcome)
                print(f"{candidate['id']} · {outcome['classification']}", flush=True)
        snapshot = publish_snapshot(store, survey_id, opts.output)
        print(json.dumps(snapshot["summary"], indent=2), flush=True)
    finally:
        store.close()


if __name__ == "__main__":
    main()
