import gzip
import json

import pytest

from science.bulk_catalog import BUCKET, product
from science.bulk_survey import BulkSurvey, CELL_AREA, NSIDE


def image(id="2025W20_2D_0176_4", detector=2, release="dr1", version="v27-2026-198"):
    return product(f"{BUCKET}{release}/level2/2025W20_2D/l2b-{version}/{detector}/"
                   f"level2_{id}D{detector}_spx_l2b-{version}.fits")


def result(job, ranges):
    return dict(id=job["id"], detector=job["detector"], cloudUrl=job["url"],
                validPixels=128, totalPixels=256, sha256="a" * 64, downloadedBytes=2880,
                coverageNside=NSIDE, coverageRanges=ranges, center=dict(ra=0, dec=0))


@pytest.fixture
def store(tmp_path):
    instance = BulkSurvey(tmp_path / "survey.sqlite")
    yield instance
    instance.close()


def test_catalog_editions_select_one_stable_observation_identity(store):
    qr = image(release="qr3")
    dr = image()
    store.seed([qr, dr, qr])
    assert store.db.execute("SELECT count(*) FROM inventory").fetchone()[0] == 2
    batch = store.begin_batch(2, 2)
    job = store.claim(batch)
    assert job["url"] == dr.url
    assert store.claim(batch) is None
    assert store.snapshot()["summary"]["uniqueProcessed"] == 0
    store.finish(job, "success", 1, result=result(job, [[10, 15]]))
    store.seed([image(version="v28-2026-199")])
    assert store.claim(batch) is None
    store.requeue(image_ids=[job["id"]])
    rerun = store.claim(batch)
    assert "v28" in rerun["url"]
    store.finish(rerun, "success", 1, result=result(rerun, [[13, 18]]))
    snapshot = store.snapshot()
    assert snapshot["summary"]["uniqueProcessed"] == 1
    assert snapshot["summary"]["successfulOperations"] == 2
    assert snapshot["summary"]["retries"] == 0
    assert snapshot["coverage"]["cells"] == 8
    assert snapshot["coverage"]["areaSquareDegrees"] == pytest.approx(8 * CELL_AREA)


def test_expired_job_can_resume_and_stale_worker_cannot_publish(store):
    store.seed([image()])
    first_batch = store.begin_batch(1, 1)
    first = store.claim(first_batch, clock=100, lease_seconds=1)
    next_batch = store.begin_batch(1, 1)
    assert store.claim(next_batch, clock=100.5) is None
    current = store.claim(next_batch, clock=102)
    assert current["attempt"] != first["attempt"]
    assert not store.finish(first, "success", 1, result=result(first, [[10, 15]]))
    assert store.finish(current, "success", 2, result=result(current, [[10, 15]]))
    snapshot = store.snapshot()
    assert snapshot["summary"]["interrupted"] == snapshot["summary"]["retries"] == 1
    assert snapshot["summary"]["uniqueProcessed"] == 1


def test_completion_cursor_is_ordered_by_commit_not_claim(store, tmp_path):
    store.seed([image(), image(detector=3)])
    batch = store.begin_batch(2, 2)
    first, second = store.claim(batch), store.claim(batch)
    store.finish(second, "success", 1, result=result(second, [[33, 35]]))
    [saved] = list(store.completed_since(0))
    with pytest.raises(ValueError):
        store.finish(first, "success", 2, result=result(first, [[31, 34], [32, 35]]))
    assert store.snapshot()["coverage"]["cells"] == 2
    store.finish(first, "success", 2, result=result(first, [[31, 34]]))
    assert [value["id"] for _, value in store.completed_since(saved[0])] == [first["id"]]
    assert store.snapshot()["coverage"]["cells"] == 4
    destination = tmp_path / "evidence.jsonl.gz"
    store.write_ledger(destination)
    with gzip.open(destination, "rt", encoding="utf-8") as handle:
        metadata, *attempts = map(json.loads, handle)
    assert metadata["goal"] == 500_000
    assert len(attempts) == 2
    assert all(event["first_success"] == 1 for event in attempts)


def test_inventory_page_and_cursor_are_transactional(store):
    store.add_scopes(["dr1/level2/2025W20_2D/"])
    scope = store.next_scope(set(), ["dr1"], [])
    items = [image()]
    assert store.record_page(scope, "/next", False, products=items)
    assert not store.record_page(scope, "/stale", True, products=[image(detector=3)])
    assert store.next_scope(set(), ["dr1"], [])["cursor"] == "/next"
    assert store.snapshot()["summary"]["discovered"] == 1


def test_two_connections_cannot_lease_the_same_work(tmp_path):
    path = tmp_path / "shared.sqlite"
    first, second = BulkSurvey(path), BulkSurvey(path)
    try:
        first.seed([image(), image(detector=3)])
        job1 = first.claim(first.begin_batch(1, 1))
        job2 = second.claim(second.begin_batch(1, 1))
        assert job1["id"] != job2["id"]
        assert second.claim(second.begin_batch(1, 1)) is None
        plan = first.db.execute("""EXPLAIN QUERY PLAN SELECT * FROM jobs INDEXED BY jobs_claim_ready
            WHERE state='queued' AND eligible<=? ORDER BY priority DESC,tries DESC,rowid LIMIT 1""", (1,))
        assert "USE TEMP" not in str([tuple(row) for row in plan])
    finally:
        first.close()
        second.close()
