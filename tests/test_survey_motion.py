import math

import numpy as np
import pytest

from science import archive, survey, survey_motion as motion


def _source(n, threshold_wcs):
    obs_id = f"2025W35_1A_{n:04}_1"
    return {
        "id": obs_id + "D1",
        "sourceUrl": f"https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W35_1A/"
                     f"l2b-v27-2026-230/1/level2_{obs_id}D1_spx_l2b-v27-2026-230.fits",
        "detector": 1,
        "collection": "spherex_dr1",
        "center": {"ra": 359.9, "dec": 0.5},
        "mjd": 61000.0 + n,
        "sha256": str(n) * 64,
        "calibrationVersion": "7.0.5",
        "wcs": threshold_wcs,
    }


def test_native_manifest_resumes_unique_plans_across_ra_origin(tmp_path):
    wcs, _ = archive.target_grid(359.9, 0.5, 30, 64)
    wcs.wcs.cdelt = [-0.05, -0.05]
    cards = {**dict(wcs.to_header()), "NAXIS1": 64, "NAXIS2": 64}
    sources = [_source(i, cards) for i in range(1, 4)]
    path = tmp_path / "motion.sqlite"
    first = motion.run_motion(path, sources[:2], max_fields=0, investigate=0)
    assert first["run"]["sourcesAdded"] == first["summary"]["sourceObservations"] == 2
    assert first["summary"]["unsearched"] > 0
    second = motion.run_motion(path, sources, max_fields=0, investigate=0)
    assert second["run"]["sourcesAdded"] == 1
    store = motion.MotionStore(path)
    try:
        assert motion._plan(store, 32, 20) > 0
        assert store.db.execute("SELECT COUNT(*) FROM fields WHERE ra<1 AND status='queued'").fetchone()[0] > 0
        assert motion.ingest_sources(store, sources) == 0
        assert motion._plan(store, 32, 20) == 0
    finally:
        store.close()


def test_common_support_sums_quality_accepted_sky_cells_only():
    config = survey.SurveyConfig()
    size = config.pixels**2
    valid_frame = dict(
        data=np.full(size, 0.25), variance=np.ones(size), mask=np.zeros(size, dtype=np.int64),
        metadata=dict(maskBits=archive.MASK_BITS),
    )
    flagged = {**valid_frame, "mask": np.where(np.arange(size) % config.pixels < config.pixels / 2,
                                             archive.SAT_BITS, 0).astype(np.int64)}
    full = sum(e - s for s, e in motion.common_coverage(359.99, -35, config, [valid_frame] * 3))
    partial = sum(e - s for s, e in motion.common_coverage(359.99, -35, config, [valid_frame, flagged]))
    assert math.isclose(full * motion.MOTION_CELL_DEG2, (config.fov / 60)**2, rel_tol=0.05)
    assert 0.44 < partial / full < 0.56


def test_known_filter_rejects_incompatible_wavelengths_before_download():
    config = survey.SurveyConfig()
    rows = [{"id": str(day), "mjd": 61000 + day, "calibrationVersion": "A", "patchWavelengthUm": wave}
            for day, wave in enumerate((0.762, 0.75, 0.984, 0.773, 0.998, 1.0))]
    chosen = motion._select(rows, config)
    assert len(chosen) == 3
    assert max(row["patchWavelengthUm"] for row in chosen) - min(row["patchWavelengthUm"] for row in chosen) < .03


def test_motion_mesh_is_explicit_and_immutable(tmp_path):
    path = tmp_path / "fine.sqlite"
    result = motion.run_motion(path, (), max_fields=0, investigate=0, mesh_degrees=1/6)
    assert result["config"]["meshDegreesAtEquator"] == 1/6
    with pytest.raises(ValueError, match="different motion mesh"):
        motion.run_motion(path, (), max_fields=0, investigate=0)
