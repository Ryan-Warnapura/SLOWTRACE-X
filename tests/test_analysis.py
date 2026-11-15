"""Numerical contracts, independent truth cases and input-rejection checks."""
import numpy as np
import pytest

from science.analysis import (weighted_stack, difference, matched_filter, compatible_subset,
                              analyze_stack, experiment, gaussian_psf, _sample)


def test_weighted_mean_and_mask_do_not_treat_missing_data_as_zero():
    images = np.array([np.full((12, 12), 2.0), np.full((12, 12), 10.0)])
    variance = np.array([np.full((12, 12), 1.0), np.full((12, 12), 4.0)])
    bad = np.zeros_like(images, bool)
    bad[1, 5, 5] = True
    stack, var, count = weighted_stack(images, variance, bad)
    assert stack[4, 4] == pytest.approx(3.6)
    assert var[4, 4] == pytest.approx(0.8)
    assert stack[5, 5] == 2
    assert var[5, 5] == 1
    assert count[5, 5] == 1


def test_difference_sign_and_variance():
    a, b = np.ones((12, 12))*2, np.ones((12, 12))*7
    bad = np.zeros((12, 12), bool)
    delta, variance = difference(a, a, bad, b, b, bad)
    assert np.all(delta == 5)
    assert np.all(variance == 9)


def test_bilinear_variance_uses_squared_weights_and_rejects_edges():
    image = np.arange(144).reshape((12, 12)).astype(float)
    variance = np.ones_like(image)*4
    bad = np.zeros_like(image, bool)
    result, var, invalid = _sample(image, variance, bad, 0.5, 0.5)
    assert result[5, 5] == pytest.approx(np.mean(image[5:7, 5:7]))
    assert var[5, 5] == pytest.approx(1)
    assert invalid[-1, -1]


def test_matched_filter_recovers_known_flux_with_analytic_uncertainty():
    image = np.zeros((32, 32))
    kernel = gaussian_psf(1)
    image[13:20, 13:20] = kernel * 100
    amplitude, error, snr = matched_filter(image, np.full_like(image, 4), np.zeros_like(image, bool), 1)
    expected_error = np.sqrt(4/np.sum(kernel**2))
    assert amplitude[16, 16] == pytest.approx(100)
    assert error[16, 16] == pytest.approx(expected_error)
    assert snr[16, 16] == pytest.approx(100/expected_error)


def test_wavelength_selection_rejects_cross_detector_and_mismatched_bands():
    assert compatible_subset([1.2, 1.21, 1.6, 1.205], [2, 2, 2, 3]) == [0, 1]
    data = np.zeros((2, 32, 32))
    with pytest.raises(ValueError, match="No comparable pair"):
        analyze_stack(data, np.ones_like(data), np.zeros_like(data, bool), [60000, 60001],
                      pixel_arcsec=6.15, wavelengths_um=[1.2, 1.6], detector_ids=[2, 2])


def moving_truth():
    # Independent direct PSF truth: moves 1 pixel/day; uneven times catch index-based shifting.
    times = np.array([60000, 60001, 60003, 60006])
    yy, xx = np.indices((48, 48))
    image = []
    for dt in times-times.mean():
        profile = np.exp(-((xx-(24+dt))**2+(yy-24)**2)/2)
        image.append(profile/profile.sum()*70)
    return np.asarray(image), times


def test_velocity_search_uses_actual_elapsed_time_and_reports_no_probability():
    image, times = moving_truth()
    result = analyze_stack(image, np.ones_like(image), np.zeros_like(image, bool), times,
                           pixel_arcsec=1, wavelengths_um=[1.2]*4, detector_ids=[2]*4,
                           velocities_arcsec_day=[(0, 0), (1, 0), (-1, 0)], threshold_snr=5)
    candidate = result["candidates"][0]
    assert candidate["velocityWestArcsecDay"] == 1
    assert candidate["velocitySouthArcsecDay"] == 0
    assert candidate["nominalSnr"] > candidate["staticSnr"]
    assert abs(candidate["x"]-24) <= 1 and candidate["y"] == 24
    assert "probability" not in candidate
    assert result["baselineDays"] == 6


def test_injection_is_reproducible_and_does_not_mutate_observations():
    rng = np.random.default_rng(110)
    image = rng.normal(size=(4, 40, 40))
    original = image.copy()
    args = dict(pixel_arcsec=1, wavelengths_um=[1.2]*4, detector_ids=[2]*4,
                seed=42, trials=2, injected_snr=4, motion_arcsec_day=(1, 0),
                velocities_arcsec_day=[(0, 0), (1, 0)], threshold_snr=5)
    one = experiment(image, np.ones_like(image), np.zeros_like(image, bool), [60000, 60001, 60003, 60006], **args)
    two = experiment(image, np.ones_like(image), np.zeros_like(image, bool), [60000, 60001, 60003, 60006], **args)
    assert one == two
    np.testing.assert_array_equal(image, original)
    assert one["kind"] == "synthetic injections on real observations"
    assert all(0 <= n <= 2 for n in one["recovered"].values())
    assert one["recovered"]["shiftStack"] == 2
