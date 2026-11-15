# Scientific methodology and interpretation

SLOWTRACE X is an exploratory analysis environment. Observations, processed measurements, synthetic injections and preliminary hypotheses have different evidentiary status. No output establishes a Planet X discovery.

## Observations and provenance

IRSA provides SPHEREx DR1 and QR3 spectral-image metadata through [SIA2 and TAP](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/). Query coordinates are ICRS degrees. Cutouts retain their originating file URL, observation time, detector, release and processing metadata. The archive is refreshed as IRSA publishes data; an empty result or failed fetch remains explicit.

The [spectral-image products](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-products/) supply calibrated IMAGE surface brightness (MJy/sr), VARIANCE ((MJy/sr)²), FLAGS and modeled ZODI. IMAGE is not already zodiacal-background-subtracted. Keep the subtraction choice in exported provenance. Spatial WCS gives the alignment; image pixels are not interchangeable until mapped to the same sky coordinates.

The implemented frame path uses IMAGE−ZODI on a common celestial grid, with per-pixel WCS-WAVE wavelengths. The service bounds fields to 1–30 arcminutes and output grids to 32–128 pixels per side (default 96). It caches 32 frames and up to 64 query results in process memory; these are performance caches, not persistent research storage. NASA's public S3 copy supplies a fallback when the cutout service fails. No NASA API account is required.

## Quality and comparison

Pixel flags are a bitmask. **SOURCE is not an invalid-pixel flag**: it marks a known source. Data quality handling must explicitly select rejection bits, then also reject nonfinite values and invalid variance. See [Explanatory Supplement v2.1, Table 16](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf) for definitions. Masked or uncovered pixels must not become artificial zero-valued measurements.

Images from the same detector can sample different wavelengths because the linear variable filters vary across the focal plane. Differencing unmatched wavelengths can reveal source color instead of change with time. PSF differences, calibration uncertainty, background errors, undersampling and registration errors can create apparent residuals. A visual difference image alone does not establish motion or variability.

For independent measurements with variances V, inverse-variance stacking uses weights w=1/V, weighted brightness sum(wI)/sum(w), and formal variance 1/sum(w). Interpolation propagates variance with **squared interpolation weights**. Reprojection correlates nearby pixels; formal pixel errors do not fully represent these covariances or calibration systematics. [Reproject documents the interpolation tradeoffs](https://reproject.readthedocs.io/en/latest/explanation/algorithms.html).

## Spectral interpretation

WCS-WAVE identifies approximate wavelength for visualization. Precise scientific spectral fitting requires the separate CWAVE/CBAND calibration, aperture/PSF corrections and uncertainty treatment. A collection of measurements at different times is not automatically a simultaneous spectrum. DR1 all-sky cubes contain 102 numbered channels; channels 51 and 52 are blank. HiPS PNGs are display products and are not used for quantitative photometry.

## Motion searches and experiments

Shift-and-stack tests a finite grid of apparent velocities over observed timestamps. [KBMOD](https://epyc.astro.washington.edu/~kbmod/user_manual/search_space.html) is an established reference for this family of methods. Searching many positions and velocities increases the chance of noise/artifact maxima. Report the search grid, epoch count, valid coverage and formal signal-to-noise; do not convert them into an invented probability of a real object.

The implementation selects the largest same-detector wavelength subset within approximately 1/R relative width, subtracts each frame's median sky level, performs bilinear trial shifts using actual MJD differences, and applies an approximate Gaussian matched filter. It reports at most 20 local peaks. The static stack is an inverse-variance mean; pair differences propagate the sum of independent input variances. Neither median-background uncertainty nor full calibration uncertainty is included. Nearby resampled pixels are correlated, so nominal SNR can overstate significance. The wavelength gate improves comparability but does not establish exact passband equivalence.

Linear apparent motion is a local approximation. Long-baseline solar-system investigations need observer motion, parallax and curved trajectories. A linear result cannot establish distance, mass, orbital elements or Planet X status. Zero-motion and competing artifact explanations must remain visible. Gaussian smoothing, when used, is an approximate filter and must not be described as detector-calibrated ePSF matching. [IRSA's ePSF tutorial](https://caltech-ipac.github.io/irsa-tutorials/spherex-psf/) describes the more complete calibration.

Synthetic injection experiments add parameterized sources to observed backgrounds and record the random seed. Compare methods on the same frames, injection positions, fluxes and acceptance thresholds. Recovery counts are empirical measurements for the selected experiment, not a survey completeness estimate. Uninjected controls and false-alarm counts matter as much as recovery. Blind validation requires disjoint held-out observations and fixed parameters before inspection; ordinary reruns are not blind evaluations.

The current lab compares single-frame, static-stack and shift-and-stack methods and includes original/negative-image controls. Injected source positions and velocities are known to the experiment, and the true velocity is included in the trial set: this is a controlled diagnostic, **not blind discovery evaluation**. Injection adds deterministic flux without extra source Poisson noise. Methods test unequal numbers of hypotheses at a common nominal threshold, so they are not compared at equal false-alarm rates. Original controls can contain real sources; negative controls may not reproduce positive artifacts. These limitations preclude a general superiority claim.

No claim of optimal ZOGY subtraction is made: [Zackay, Ofek & Gal-Yam (2016)](https://arxiv.org/abs/1601.02655) requires accurate registration, PSF and noise assumptions that a simple image difference does not satisfy.

## Follow-up visibility

The planner calculates a fixed ICRS pointing with Astropy's ICRS→AltAz transformation at an east-positive longitude, latitude and elevation. It samples a UTC day, uses `pressure=0 hPa` (airless altitude) and Astropy's built-in Sun calculation. Suggested windows satisfy both user-selected target-altitude and solar-altitude constraints. The default Sun limit is −18°, astronomical darkness.

Window endpoints are passing grid samples, not exact rise/set solutions. Airmass is the secant approximation only above 10°. Packaged IERS Earth-orientation data avoids a runtime network dependency; precision may degrade outside its coverage. Weather, terrain, moonlight, instrumental sensitivity, proper motion and candidate orbit extrapolation are excluded. [Astropy observation-planning reference](https://docs.astropy.org/en/stable/coordinates/example_gallery_plot_obs_planning.html).

## Reproduction

Retain the source FITS URLs/files, release/version, query coordinates, field size, wavelength choice, masks, background setting, alignment grid, selected observation IDs, algorithm parameters and software revision. For experiments additionally retain the seed and synthetic-source settings. Repeat results using the same upstream files; an archive update can change a result. Exported hypotheses require independent astronomical review and follow-up before any discovery claim.
