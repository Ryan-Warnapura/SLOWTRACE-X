import numpy as np
import pytest

from science import archive
from science.archive import MASK_BITS, SAT_BITS, resample, target_grid, validate_url, checked_position, aperture_measurement
from science.coverage import matching_records, read_index


def test_source_and_fullsample_not_bad():
    assert not MASK_BITS & (1 << 21)
    assert not MASK_BITS & (1 << 12)
    assert MASK_BITS & (1 << 9)
    assert MASK_BITS & (1 << 26)  # source bloom
    assert MASK_BITS & (1 << 29)  # satellite halo


def test_reprojection_variance_uses_squared_weights():
    data = np.array([[1., 2.], [3., 4.]])
    v = np.full((2, 2), 4.)
    f = np.full((2, 2), 1 << 21)
    image, variance, _ = resample(data, v, f, np.array([[.5]]), np.array([[.5]]))
    assert image[0, 0] == pytest.approx(2.5)
    assert variance[0, 0] == pytest.approx(1.)


def test_bad_neighbor_masks_scientific_pixel():
    f = np.zeros((2, 2), dtype=int)
    f[0, 0] = 1 << 9
    image, variance, mask = resample(np.ones((2, 2)), np.ones((2, 2)), f, np.array([[.5]]), np.array([[.5]]))
    assert np.isnan(image[0, 0]) and np.isnan(variance[0, 0])
    assert mask[0, 0] & (1 << 9)


def test_north_up_east_left():
    _, (ra, dec) = target_grid(100, 20, 5, 33)
    assert ra[16, 0] > ra[16, -1]
    assert dec[0, 16] > dec[-1, 16]


@pytest.mark.parametrize("url", ["http://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/a.fits", "https://example.org/a.fits", "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/../secret.fits", "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/a.fits?x=1"])
def test_reject_non_official_urls(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_invalid_coordinate_rejected():
    with pytest.raises(ValueError):
        checked_position(float("nan"), 0, 5)


def test_aperture_background_invariance_and_saturation_guard():
    wcs, _ = target_grid(100, 20, 5, 25)
    a = np.ones((25, 25))
    a[12, 12] += 10
    v, flags = np.ones_like(a), np.zeros_like(a, dtype=int)
    one = aperture_measurement(a, v, flags, 12, 12, wcs)
    two = aperture_measurement(a + 100, v, flags, 12, 12, wcs)
    assert one["fluxMicroJy"] == pytest.approx(two["fluxMicroJy"])
    flags[12, 12] = 1 << 1
    saturated = aperture_measurement(a, v, flags, 12, 12, wcs)
    assert saturated["status"] == "saturated" and saturated["fluxMicroJy"] is None


def test_real_header_index_covers_official_wise_coordinate_without_a_preset_match():
    ra, dec = 133.795129, -7.245147
    assert archive._recorded_rows(ra, dec) is None
    records, captured = matching_records(ra, dec, 1, {"dr1", "qr3"})
    assert records and captured >= read_index()["generatedAt"]
    assert max(r["mjd"] for r in records) - min(r["mjd"] for r in records) > 180
    site = archive.search(ra, dec, 5, 1, 4, indexed_only=True)
    assert site["status"] == "recorded-metadata"
    assert not site["searchCoverage"]["complete"]
    assert all(o["metadataSource"] == "nasa-fits-header-index" for o in site["observations"])
    assert all(len(o["fitsHeaderSha256"]) == 64 for o in site["observations"])


def test_index_checks_detector_and_exact_spherical_position():
    records, _ = matching_records(269.5862, 4.76883, 1, {"dr1", "qr3"})
    assert {r["url"].split("/spherex/")[1].split("/")[0] for r in records} == {"dr1", "qr3"}
    assert all(r["detector"] == 1 for r in records)
    assert matching_records(89.5862, -4.76883, 1, set())[0] == []


def test_metadata_outage_at_unindexed_position_is_not_no_coverage(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise archive.ArchiveError("upstream unavailable")

    monkeypatch.setattr(archive, "_query_collection", unavailable)
    monkeypatch.setattr(archive, "_query_tap", unavailable)
    monkeypatch.setattr(archive, "matching_records", lambda *_: ([], None))
    result = archive.search(10.0, 0.0, 3, 1, 2)
    assert result["outcome"] == "metadata-incomplete"
    assert not result["searchCoverage"]["complete"]
    assert result["observations"] == []


def test_tap_failover_clearly_reports_retrieval_protocol(monkeypatch):
    url = "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W20_2D/l2b-v27-2026-198/2/level2_2025W20_2D_0176_4D2_spx_l2b-v27-2026-198.fits"
    date = "2026-11-15T22:00:00+00:00"

    def unavailable(*_args, **_kwargs):
        raise archive.ArchiveError("SIA unavailable")

    monkeypatch.setattr(archive, "_query_collection", unavailable)
    monkeypatch.setattr(archive, "_query_tap", lambda *_: ([dict(
        access_url=url, obs_id="example", obs_collection="spherex_dr1", energy_bandpassname="SPHEREx-D2",
        t_min="60814.123", t_max="60814.124", metadataSource="irsa-tap", metadataRetrievedAt=date
    )], archive.TAP, date, False))
    response = archive.search(210.80227, 54.34895, 5, 2, 4)
    assert response["status"] == "live" and response["searchCoverage"]["complete"]
    assert response["archiveChecked"] == date and response["queryUrls"] == [archive.TAP]
    assert response["observations"][0]["metadataSource"] == "irsa-tap"


def test_observer_state_does_not_confuse_image_wcs_with_vector_orientation():
    h = dict(RADESYS="ICRS", XYZ_SC_SYSTEM="GEOCENTER", VXYZ_SC_SYSTEM="GEOCENTER",
             X_SC=1000, Y_SC=-5500, Z_SC=4000, VX_SC=-2, VY_SC=2, VZ_SC=5)
    state = archive._observer_state(h, 61234.5)
    assert state["origin"] == "GEOCENTER" and state["frame"] is None
    assert state["positionKm"] == [1000.0, -5500.0, 4000.0]
    assert archive._observer_state(dict(h, X_SC=float("nan")), 61234.5) is None
