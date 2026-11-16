"""Deterministic survey tests. Synthetic science fixtures never enter the public snapshot."""
from dataclasses import replace
import json

import numpy as np

from science import archive, survey


def test_grid_is_deterministic_and_wraps_ra_near_pole():
    fields = survey.grid_regions(359.97, 85, 4, 3, 3)
    assert len(fields) == 9
    assert fields == survey.grid_regions(359.97, 85, 4, 3, 3)
    assert len({(r.ra, r.dec) for r in fields}) == 9
    assert any(r.ra < 5 for r in fields)
    assert (fields[4].ra, fields[4].dec) == (359.97, 85)


def test_lease_recovery_and_deduplicated_expansion(tmp_path):
    first = survey.SurveyStore(tmp_path / "survey.sqlite")
    second = survey.SurveyStore(tmp_path / "survey.sqlite")
    config = survey.SurveyConfig()
    regions = [survey.Region(135, 20, "One")]
    key = first.plan("Test", config, regions)
    assert second.plan("Test", config, regions) == key
    claim = first.claim(key, lease_seconds=-1)
    recovered = second.claim(key)
    assert recovered["id"] == claim["id"] and recovered["attempt"] == 2
    assert first.finish(claim, {"status": "complete"}) is False
    assert second.finish(recovered, {"status": "empty", "message": "Fixture returned no exposures"})
    assert first.plan("Test", config, [*regions, survey.Region(140, 25, "Two")]) == key
    snapshot = first.snapshot(key)
    assert snapshot["summary"]["queued"] == snapshot["summary"]["empty"] == 1
    assert snapshot["fields"][0]["history"][1]["status"] == "error"
    assert first.requeue(key) == 0
    assert first.requeue(key, refresh=True) == 1
    first.close()
    second.close()


def test_recorded_empty_is_incomplete_but_live_empty_is_empty():
    field = dict(id="test", ra=10, dec=12)
    def attempt(status):
        def search(*args):
            return dict(status=status, observations=[], totalAvailable=0)
        report, product, peaks = survey.process_field(field, survey.SurveyConfig(), search=search)
        assert product is None and not peaks and report["observationsAnalyzed"] == 0
        return report["status"]
    assert attempt("recorded-metadata") == "incomplete"
    assert attempt("live") == "empty"


def test_search_failure_preserves_error_without_computing():
    field = dict(id="test", ra=10, dec=12)
    def offline(*args):
        raise archive.ArchiveError("Fixture archive outage")
    report, product, candidates = survey.process_field(field, survey.SurveyConfig(), search=offline, fetch=offline)
    assert report["status"] == "error" and "outage" in report["message"]
    assert product is None and not candidates


def _synthetic_source(ra, dec, size):
    items = []
    y, x = np.indices((size, size), dtype=float)
    for index, (day, offset, wave, calibration, zodi) in enumerate([
        (0.0, -1.5, 0.89, "v1", True), (0.01, -1.5, 0.89, "v1", True),
        (10.0, 0, 0.893, "v1", True), (20.0, 1.5, 0.894, "v1", True),
        (50.0, 9, 0.98, "v1", True), (65.0, 10, 0.893, "v2", True), (72.0, 10, 0.893, "v1", False),
    ]):
        source = dict(id=f"fixture-{index}", url=f"fixture-{index}", collection="spherex_dr1")
        mjd = 60000 + day
        metadata = dict(id=source["id"], mjd=mjd, date=archive.date_mjd(mjd), detector=1,
                        calibrationVersion=calibration, zodiSubtracted=zodi, badFraction=0.03,
                        wavelengthCenter=wave, maskBits=archive.MASK_BITS)
        values = 0.15 + 6*np.exp(-((x-16-offset)**2 + (y-18)**2)/2)
        mask = np.zeros((size, size), dtype=int)
        mask[1, 1] = 1 << 9
        frame = dict(width=size, height=size, data=values.ravel().tolist(), variance=[.04]*size**2,
                     mask=mask.ravel().tolist(), wavelength=[wave]*size**2, metadata=metadata,
                     provenance=dict(sourceUrl=source["url"], input="synthetic fixture"), warnings=[])
        items.append((source, frame))
    return items


def test_real_engine_pipeline_selects_compatible_epochs_and_persists_evidence(tmp_path):
    ra, dec, n = 10, 12, 32
    config = survey.SurveyConfig(pixels=n)
    items = _synthetic_source(ra, dec, n)
    def lookup(*args):
        return dict(status="live", observations=[s for s, _ in items], totalAvailable=len(items))
    index = {s["url"]: f for s, f in items}
    def fetch(url, *_):
        return index[url]
    store = survey.SurveyStore(tmp_path / "survey.sqlite")
    key = store.plan("Synthetic unit test", config, [survey.Region(ra, dec)])
    for _ in range(2):
        field = store.claim(key)
        report, product, peaks = survey.process_field(field, config, search=lookup, fetch=fetch)
        assert report["status"] == "complete"
        assert report["observationsFetched"] == 7 and report["observationsAnalyzed"] == 3
        assert report["usablePixelSamples"] == 3*(n*n-1)
        assert product["retainedSourceIds"] == ["fixture-0", "fixture-2", "fixture-3"]
        assert peaks and all(c["classification"] == "insufficient-evidence" for c in peaks)
        assert all(p["positionKind"] == "predicted-track" for p in peaks[0]["evidence"]["epochMeasurements"])
        assert store.finish(field, report, product, peaks)
        store.requeue(key, refresh=True)
    snapshot = survey.publish_snapshot(store, key, tmp_path / "public.json")
    assert snapshot == json.loads((tmp_path / "public.json").read_text(encoding="utf-8"))
    assert len(snapshot["analyses"]) == 1 and len(snapshot["fields"][0]["history"]) == 2
    assert snapshot["summary"]["uniqueExposuresAnalyzed"] == 3
    assert snapshot["summary"]["candidates"] == len(peaks)
    id_ = snapshot["candidates"][0]["id"]
    store.record_investigation(id_, dict(checkedAt="2026-11-15T22:15:00Z", classification="catalog-consistent", reasons=["Test result"] ))
    updated = store.snapshot(key)["candidates"][0]
    assert updated["id"] == id_ and updated["classification"] == "catalog-consistent"
    assert [r["classification"] for r in updated["history"]] == ["insufficient-evidence", "catalog-consistent"]
    store.close()
