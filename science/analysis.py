"""Bounded, inspectable research calculations on real, aligned SPHEREx cutouts.

No statistic here is a discovery probability. The nominal S/N assumes independent
pixels; interpolation, calibration and background systematics violate that ideal.
The module deliberately does not infer an orbit or a physical object class.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np
from scipy import ndimage

RESOLVING_POWER = {1: 39, 2: 41, 3: 41, 4: 35, 5: 112, 6: 128}
NOTES = [
    "Research measurements, not a discovery confirmation or calibrated probability.",
    "Nominal S/N assumes independent Gaussian pixel errors; resampling correlates pixels, so significance can be overstated.",
    "Per-frame median backgrounds are removed. Background-estimation and calibration uncertainties are not propagated.",
    "A Gaussian PSF is an explicit approximation, not the detector's calibrated effective PSF.",
    "Wavelengths from WCS-WAVE are approximate visualization metadata; matching does not establish identical bandpasses.",
    "Velocity trials and source peaks involve multiple comparisons. Listed S/N values have no trials correction.",
]


@dataclass
class Cube:
    image: np.ndarray
    variance: np.ndarray
    bad: np.ndarray
    times: np.ndarray
    selected: list[int]
    excluded: list[int]
    wavelength: list[float]
    detector: int
    backgrounds: list[float]


def _number(value: float, name: str, lo: float, hi: float) -> float:
    value = float(value)
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}.")
    return value


def compatible_subset(wavelengths_um: Sequence[float], detector_ids: Sequence[int]) -> list[int]:
    """Largest same-detector subset within one nominal resolution element.

    The full max/min wavelength ratio must be <= 1+1/R, not just agreement
    with a possibly unrepresentative mean. Missing wavelengths are not guessed.
    """
    wave = np.asarray(wavelengths_um, dtype=float)
    detector = np.asarray(detector_ids)
    if wave.ndim != 1 or detector.shape != wave.shape:
        raise ValueError("One wavelength and detector ID are required per image.")
    best: list[int] = []
    for d, resolving in RESOLVING_POWER.items():
        idx = np.flatnonzero((detector == d) & np.isfinite(wave) & (wave > 0))
        idx = idx[np.argsort(wave[idx])]
        for start in range(len(idx)):
            subset = [int(i) for i in idx[start:] if wave[i] / wave[idx[start]] <= 1 + 1 / resolving]
            if len(subset) > len(best):
                best = sorted(subset)
    return best


def _prepare(frames, variances, masks, times_mjd, wavelengths_um, detector_ids) -> Cube:
    image = np.asarray(frames, dtype=float)
    var = np.asarray(variances, dtype=float)
    bad = np.asarray(masks, dtype=bool)
    times = np.asarray(times_mjd, dtype=float)
    if image.ndim != 3 or not 2 <= image.shape[0] <= 8 or not all(12 <= n <= 128 for n in image.shape[1:]):
        raise ValueError("Analysis requires 2–8 aligned images, each between 12 and 128 pixels per side.")
    if var.shape != image.shape or bad.shape != image.shape or times.shape != (len(image),):
        raise ValueError("Image, variance, mask and timestamp dimensions disagree.")
    if not np.isfinite(times).all():
        raise ValueError("Every observation needs a finite MJD timestamp.")
    if len(wavelengths_um) != len(image) or len(detector_ids) != len(image):
        raise ValueError("Every observation needs measured wavelength and detector metadata.")
    indices = compatible_subset(wavelengths_um, detector_ids)
    if len(indices) < 2 or np.ptp(times[indices]) <= 0:
        raise ValueError("No comparable pair: load at least two different observation times from one detector within one spectral resolution element.")
    excluded = [i for i in range(len(image)) if i not in indices]
    order = np.argsort(times[indices])
    indices = [indices[int(i)] for i in order]
    image, var, bad, times = image[indices].copy(), var[indices].copy(), bad[indices].copy(), times[indices]
    bad |= ~np.isfinite(image) | ~np.isfinite(var) | (var <= 0)
    backgrounds = []
    for i in range(len(image)):
        if np.count_nonzero(~bad[i]) < 25:
            raise ValueError("An observation has fewer than 25 usable pixels after flag and variance masking.")
        bg = float(np.median(image[i][~bad[i]]))
        image[i] -= bg
        image[i][bad[i]] = np.nan
        var[i][bad[i]] = np.nan
        backgrounds.append(bg)
    return Cube(image, var, bad, times, indices, excluded,
                [float(wavelengths_um[i]) for i in indices], int(detector_ids[indices[0]]), backgrounds)


def _sample(image, variance, bad, dx, dy):
    """Sample at (x+dx,y+dy), propagating bilinear variance with squared weights.

    All contributing nonzero-weight pixels must be usable. This rejects holes
    and edges rather than zero filling them or treating masks as measurements.
    """
    h, w = image.shape
    yy, xx = np.indices((h, w), dtype=float)
    xx += dx
    yy += dy
    x0, y0 = np.floor(xx).astype(int), np.floor(yy).astype(int)
    tx, ty = xx - x0, yy - y0
    value = np.zeros((h, w))
    error = np.zeros((h, w))
    valid = np.ones((h, w), dtype=bool)
    for ox, oy, weight in ((0, 0, (1-tx)*(1-ty)), (1, 0, tx*(1-ty)), (0, 1, (1-tx)*ty), (1, 1, tx*ty)):
        x, y = x0 + ox, y0 + oy
        inside = (x >= 0) & (y >= 0) & (x < w) & (y < h)
        xc, yc = np.clip(x, 0, w-1), np.clip(y, 0, h-1)
        useful = weight > 1e-12
        good = inside & ~bad[yc, xc] & np.isfinite(image[yc, xc]) & np.isfinite(variance[yc, xc]) & (variance[yc, xc] > 0)
        valid &= ~useful | good
        value += np.where(useful & good, image[yc, xc], 0) * weight
        error += np.where(useful & good, variance[yc, xc], 0) * weight**2
    return np.where(valid, value, np.nan), np.where(valid, error, np.nan), ~valid


def weighted_stack(frames, variances, masks, offsets=None):
    """Inverse-variance mean plus its nominal variance and per-pixel support."""
    frames, variances, masks = np.asarray(frames), np.asarray(variances), np.asarray(masks, dtype=bool)
    offsets = offsets if offsets is not None else [(0.0, 0.0)] * len(frames)
    numerator = np.zeros(frames.shape[1:])
    denominator = np.zeros_like(numerator)
    count = np.zeros_like(numerator, dtype=int)
    for image, variance, bad, (dx, dy) in zip(frames, variances, masks, offsets):
        image, variance, bad = _sample(image, variance, bad, dx, dy)
        ok = ~bad & np.isfinite(image) & np.isfinite(variance) & (variance > 0)
        weight = np.divide(1, variance, out=np.zeros_like(variance), where=ok)
        numerator += np.where(ok, image, 0) * weight
        denominator += weight
        count += ok
    return (np.divide(numerator, denominator, out=np.full_like(numerator, np.nan), where=denominator > 0),
            np.divide(1, denominator, out=np.full_like(numerator, np.nan), where=denominator > 0), count)


def difference(image_a, variance_a, mask_a, image_b, variance_b, mask_b):
    """Later minus earlier; independent exposure variances add."""
    a, b = np.asarray(image_a), np.asarray(image_b)
    va, vb = np.asarray(variance_a), np.asarray(variance_b)
    good = (~np.asarray(mask_a, bool) & ~np.asarray(mask_b, bool) & np.isfinite(a) & np.isfinite(b)
            & np.isfinite(va) & np.isfinite(vb) & (va > 0) & (vb > 0))
    return np.where(good, b-a, np.nan), np.where(good, va+vb, np.nan)


def gaussian_psf(sigma: float):
    sigma = _number(sigma, "PSF sigma", 0.6, 2.0)
    radius = int(math.ceil(3 * sigma))
    y, x = np.mgrid[-radius:radius+1, -radius:radius+1]
    kernel = np.exp(-(x*x+y*y)/(2*sigma*sigma))
    return kernel / kernel.sum()


def matched_filter(image, variance, bad, sigma=1.0):
    """Maximum-likelihood flux and S/N for a unit-integral Gaussian template."""
    image, variance, bad = np.asarray(image), np.asarray(variance), np.asarray(bad, bool)
    psf = gaussian_psf(sigma)
    good = ~bad & np.isfinite(image) & np.isfinite(variance) & (variance > 0)
    inverse = np.divide(1, variance, out=np.zeros_like(variance), where=good)
    numerator = ndimage.convolve(np.where(good, image, 0)*inverse, psf, mode="constant", cval=0)
    denominator = ndimage.convolve(inverse, psf**2, mode="constant", cval=0)
    coverage = ndimage.convolve(good.astype(float), psf, mode="constant", cval=0)
    valid = (coverage >= 0.95) & (denominator > 0)
    amplitude = np.divide(numerator, denominator, out=np.full_like(numerator, np.nan), where=valid)
    error = np.sqrt(np.divide(1, denominator, out=np.full_like(numerator, np.nan), where=valid))
    return amplitude, error, np.divide(amplitude, error, out=np.full_like(amplitude, np.nan), where=valid)


def _velocity_grid(velocities_arcsec_day, pixel_arcsec, span, shape):
    if velocities_arcsec_day is None:
        # One-pixel total-displacement spacing; the real time baseline fixes speed.
        step = pixel_arcsec / max(span, 1e-9)
        velocities_arcsec_day = [(x*step, y*step) for y in (-2, -1, 0, 1, 2) for x in (-2, -1, 0, 1, 2)]
    vectors = np.asarray(velocities_arcsec_day, dtype=float)
    if vectors.ndim != 2 or vectors.shape[1] != 2 or not 1 <= len(vectors) <= 49 or not np.isfinite(vectors).all():
        raise ValueError("Supply 1–49 finite two-component velocity trials.")
    if np.max(np.abs(vectors)) * span / pixel_arcsec > min(shape) / 3:
        raise ValueError("A trial moves beyond one third of the field. Widen the field or reduce the speed.")
    if not np.any(np.all(vectors == 0, axis=1)):
        if len(vectors) == 49:
            raise ValueError("Include the zero-velocity control within the maximum 49 trials.")
        vectors = np.vstack([[0, 0], vectors])
    return vectors


def _search(cube, vectors, pixel_arcsec, sigma, threshold):
    best = np.full(cube.image.shape[1:], -np.inf)
    best_index = np.zeros(best.shape, int)
    best_amplitude = np.full(best.shape, np.nan)
    best_error = np.full(best.shape, np.nan)
    reference_time = float(np.mean(cube.times))
    static = None
    min_support = max(2, math.ceil(len(cube.image)*0.75))
    for j, velocity in enumerate(vectors):
        offsets = np.outer(cube.times-reference_time, velocity/pixel_arcsec)
        stack, variance, count = weighted_stack(cube.image, cube.variance, cube.bad, offsets)
        amplitude, error, snr = matched_filter(stack, variance, count < min_support, sigma)
        if np.all(velocity == 0):
            static = (stack, variance, count, amplitude, error, snr)
        use = np.isfinite(snr) & (snr > best)
        best[use], best_index[use] = snr[use], j
        best_amplitude[use], best_error[use] = amplitude[use], error[use]
    best[~np.isfinite(best)] = np.nan
    finite = np.where(np.isfinite(best), best, -np.inf)
    peak = (finite == ndimage.maximum_filter(finite, size=5, mode="constant", cval=-np.inf)) & (finite >= threshold)
    yx = np.argwhere(peak)
    yx = sorted(yx, key=lambda p: -best[p[0], p[1]])[:20]
    candidates = []
    for y, x in yx:
        velocity = vectors[best_index[y, x]]
        static_snr = float(static[5][y, x]) if np.isfinite(static[5][y, x]) else None
        candidates.append({"x": int(x), "y": int(y), "nominalSnr": float(best[y, x]),
                           "fluxPixelSum": float(best_amplitude[y, x]), "fluxPixelSumError": float(best_error[y, x]),
                           "velocityWestArcsecDay": float(velocity[0]), "velocitySouthArcsecDay": float(velocity[1]),
                           "staticSnr": static_snr, "snrGainOverStatic": float(best[y, x])-static_snr if static_snr is not None else None,
                           "status": "unverified peak", "knownObjectCheck": "not performed"})
    return best, static, candidates, reference_time


def _json_array(array):
    return [float(v) if np.isfinite(v) else None for v in np.asarray(array).ravel()]


def _finite_peak(array):
    values = np.asarray(array)
    values = values[np.isfinite(values)]
    return float(np.max(values)) if len(values) else None


def analyze_stack(frames, variances, masks, times_mjd, *, pixel_arcsec, wavelengths_um,
                  detector_ids, velocities_arcsec_day=None, threshold_snr=5.0, psf_sigma_pixels=1.0):
    """JSON-ready stack, temporal difference, trial search, and measurable evidence."""
    pixel_arcsec = _number(pixel_arcsec, "Pixel scale (arcseconds)", 0.1, 120)
    threshold_snr = _number(threshold_snr, "S/N threshold", 3, 20)
    cube = _prepare(frames, variances, masks, times_mjd, wavelengths_um, detector_ids)
    vectors = _velocity_grid(velocities_arcsec_day, pixel_arcsec, np.ptp(cube.times), cube.image.shape[1:])
    best, static, candidates, reference_time = _search(cube, vectors, pixel_arcsec, psf_sigma_pixels, threshold_snr)
    delta, delta_var = difference(cube.image[0], cube.variance[0], cube.bad[0], cube.image[-1], cube.variance[-1], cube.bad[-1])
    return {"kind": "processed observations", "method": "inverse-variance Gaussian shift-and-stack v1",
            "width": int(best.shape[1]), "height": int(best.shape[0]),
            "selectedFrameIndices": cube.selected, "excludedFrameIndices": cube.excluded,
            "detector": cube.detector, "wavelengthsUm": cube.wavelength,
            "referenceMjd": reference_time, "baselineDays": float(np.ptp(cube.times)),
            "backgroundsMjySr": cube.backgrounds, "velocitiesArcsecDay": vectors.tolist(),
            "velocityAxes": ["west (+image x)", "south (+image y)"],
            "thresholdSnr": threshold_snr, "psfSigmaPixels": psf_sigma_pixels,
            "stack": _json_array(static[0]), "stackVariance": _json_array(static[1]),
            "support": static[2].ravel().astype(int).tolist(), "difference": _json_array(delta),
            "differenceVariance": _json_array(delta_var), "searchSnr": _json_array(best),
            "candidates": candidates, "notes": NOTES + [
                "Differences compare the first and last selected images; their PSFs are not matched, so residuals can be instrumental.",
                "The best velocity is a grid maximum, not a fitted trajectory; static stars and artifacts can also win a nonzero trial.",
                "fluxPixelSum is summed surface brightness in MJy/sr·pixel, not calibrated point-source flux in Jy."]}


def _add_source(cube, x, y, velocity, flux, pixel_arcsec, sigma):
    signal = cube.image.copy()
    yy, xx = np.indices(signal.shape[1:])
    reference = float(np.mean(cube.times))
    for i, t in enumerate(cube.times):
        cx, cy = np.array([x, y]) + np.asarray(velocity)*(t-reference)/pixel_arcsec
        psf = np.exp(-((xx-cx)**2+(yy-cy)**2)/(2*sigma*sigma))
        psf /= psf.sum()
        signal[i] += flux*psf
    return Cube(signal, cube.variance, cube.bad, cube.times, cube.selected, cube.excluded,
                cube.wavelength, cube.detector, cube.backgrounds)


def experiment(frames, variances, masks, times_mjd, *, pixel_arcsec, wavelengths_um,
               detector_ids, seed=42, trials=8, injected_snr=3.0, motion_arcsec_day=(10.0, 0.0),
               velocities_arcsec_day=None, threshold_snr=5.0, psf_sigma_pixels=1.0):
    """Seeded additive source recovery on supplied real backgrounds, with controls.

    Compare methods at the same preselected threshold. The control peak count
    is not called a false-positive rate: true sources remain in the real sky.
    """
    pixel_arcsec = _number(pixel_arcsec, "Pixel scale (arcseconds)", 0.1, 120)
    trials = int(_number(trials, "Trials", 1, 16))
    seed = int(_number(seed, "Seed", 0, 2**32-1))
    injected_snr = _number(injected_snr, "Injected single-frame nominal S/N", 0.1, 15)
    threshold_snr = _number(threshold_snr, "Threshold S/N", 3, 20)
    psf = gaussian_psf(psf_sigma_pixels)
    cube = _prepare(frames, variances, masks, times_mjd, wavelengths_um, detector_ids)
    span = float(np.ptp(cube.times))
    vectors = _velocity_grid(velocities_arcsec_day, pixel_arcsec, span, cube.image.shape[1:])
    motion = np.asarray(motion_arcsec_day, dtype=float)
    if motion.shape != (2,) or not np.isfinite(motion).all():
        raise ValueError("Injection motion requires two finite arcseconds/day components.")
    if np.max(np.abs(motion))*span/pixel_arcsec > min(cube.image.shape[1:])/3:
        raise ValueError("Injected source would travel too far across this field.")
    # Include the user-selected true velocity, explicitly documented as an oracle-grid trial.
    if not np.any(np.all(np.isclose(vectors, motion), axis=1)):
        if len(vectors) >= 49:
            raise ValueError("Experiment needs space in the grid for the injected velocity (maximum 49 trials).")
        vectors = np.vstack([vectors, motion])
    control, static, peaks, _ = _search(cube, vectors, pixel_arcsec, psf_sigma_pixels, threshold_snr)
    median_variance = float(np.nanmedian(cube.variance))
    flux = float(injected_snr * math.sqrt(median_variance / np.sum(psf**2)))
    margin = int(math.ceil(3*psf_sigma_pixels + np.max(np.abs(motion))*span/(2*pixel_arcsec) + 3))
    h, w = control.shape
    if 2*margin >= min(h, w):
        raise ValueError("Field too small for this injection motion and PSF. Increase the field or reduce motion.")
    eligible = np.isfinite(control) & np.isfinite(static[5]) & (control < threshold_snr)
    eligible[:margin] = eligible[-margin:] = False
    eligible[:, :margin] = eligible[:, -margin:] = False
    spots = np.argwhere(eligible)
    if len(spots) < trials:
        raise ValueError("Not enough valid, below-threshold locations for an unbiased local recovery experiment.")
    rng = np.random.default_rng(seed)
    chosen = spots[rng.choice(len(spots), size=trials, replace=False)]
    results = []
    for y, x in chosen:
        injected = _add_source(cube, x, y, motion, flux, pixel_arcsec, psf_sigma_pixels)
        search, static_injected, _, _ = _search(injected, vectors, pixel_arcsec, psf_sigma_pixels, threshold_snr)
        moving_snr = _finite_peak(search[y-1:y+2, x-1:x+2])
        stack_snr = _finite_peak(static_injected[5][y-1:y+2, x-1:x+2])
        singles = []
        for i, t in enumerate(cube.times):
            cx, cy = np.rint(np.array([x, y])+motion*(t-np.mean(cube.times))/pixel_arcsec).astype(int)
            s = matched_filter(injected.image[i], injected.variance[i], injected.bad[i], psf_sigma_pixels)[2]
            peak = _finite_peak(s[cy-1:cy+2, cx-1:cx+2])
            if peak is not None:
                singles.append(peak)
        best_single = max(singles) if singles else None
        results.append({"x": int(x), "y": int(y), "injectedFluxPixelSum": flux,
                        "shiftStackSnr": moving_snr, "staticStackSnr": stack_snr, "bestSingleFrameSnr": best_single,
                        "shiftStackRecovered": moving_snr is not None and moving_snr >= threshold_snr,
                        "staticStackRecovered": stack_snr is not None and stack_snr >= threshold_snr,
                        "singleFrameRecovered": best_single is not None and best_single >= threshold_snr,
                        "unInjectedControlSnr": float(control[y, x])})
    counts = {method: sum(row[key] for row in results) for method, key in [
        ("shiftStack", "shiftStackRecovered"), ("staticStack", "staticStackRecovered"), ("bestSingleFrame", "singleFrameRecovered")]}
    # Sign inversion retains correlated noise; negative real structures can remain.
    negative = Cube(-cube.image, cube.variance, cube.bad, cube.times, cube.selected, cube.excluded,
                    cube.wavelength, cube.detector, cube.backgrounds)
    _, _, negative_peaks, _ = _search(negative, vectors, pixel_arcsec, psf_sigma_pixels, threshold_snr)
    return {"kind": "synthetic injections on real observations", "method": "seeded additive Gaussian injection recovery v1",
            "seed": seed, "trials": trials, "injectedSingleFrameNominalSnr": injected_snr,
            "injectedFluxPixelSum": flux, "motionArcsecDay": motion.tolist(), "velocityAxes": ["west", "south"],
            "velocitiesArcsecDay": vectors.tolist(), "thresholdSnr": threshold_snr, "psfSigmaPixels": psf_sigma_pixels,
            "selectedFrameIndices": cube.selected, "excludedFrameIndices": cube.excluded,
            "baselineDays": span, "recovered": counts,
            "recoveryFraction": {k: v/trials for k, v in counts.items()},
            "unInjectedControlPeaks": len(peaks), "negativeControlPeaks": len(negative_peaks),
            "controlPeakCountCappedAt": 20, "measurements": results,
            "notes": NOTES + [
                "Synthetic sources are added to the supplied real sky images; original observations are unchanged.",
                "The true injected velocity is included in the search grid. This is a controlled sensitivity study, not a blind evaluation.",
                "Injection adds flux but no extra Poisson noise. The experiment applies to weak sources dominated by background noise.",
                "Both injector and detector assume a Gaussian PSF; this optimistic model match does not test PSF mismatch.",
                "All methods use the same threshold; unequal trial counts mean this is not an equal-false-alarm comparison.",
                "Control counts include real celestial structure and are not a calibrated false-positive rate.",
                "Recovery means a threshold crossing within one pixel of the known injected location. No independent held-out observations were used."]}
