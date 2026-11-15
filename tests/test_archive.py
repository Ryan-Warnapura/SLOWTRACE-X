import numpy as np
import pytest

from science.archive import MASK_BITS, SAT_BITS, resample, target_grid, validate_url, checked_position, _normalize, aperture_measurement


def test_source_and_fullsample_not_bad():
    assert not MASK_BITS & (1 << 21)
    assert not MASK_BITS & (1 << 12)
    assert MASK_BITS & (1 << 9)


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
