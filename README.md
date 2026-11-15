# SLOWTRACE X

SLOWTRACE X is a public observation desk for the NASA Space Apps challenge **Planet X and SPHEREx**. Enter ICRS right ascension and declination in degrees, choose a field size and detector, then blink, subtract, or compare authentic SPHEREx observations. The opening Barnard’s Star example contains recorded NASA observations with source URLs, dates, and checksums. Choose **Search live archive** to run a fresh query.

## Run locally

Use Node.js 22.12+ and Python 3.12. From the repository root, install the dependencies and start an API terminal:

```sh
npm ci
python -m pip install -r requirements.txt
python -m uvicorn api.index:app --port 8000
```

In a second terminal, run `npm run dev` and open `http://127.0.0.1:5173`. No NASA account or API key is needed. `npm run build` produces the client and the Vercel project runs the Python API in the same domain.

## Investigate a field

1. Open Barnard’s Star or enter coordinates, then choose a detector. For the nominal WISE 0855 position, enter **133.795129°, −7.245147°**. The named presets use the field centres recorded in the validation report.
2. Play or step through the dates. Choose **Side by side** for the first and selected image, or **Difference** for selected minus first. Inspect wavelength and mask metadata and open the original FITS cutout from its source link.
3. Click a pixel to sample brightness over time and wavelength. Run **DeepTrace search** to score preliminary peaks across a bounded grid of trial velocities. The analysis chooses observations whose local wavelengths are reasonably close and lists exclusions.
4. Under **Experiment lab**, choose a seed, motion, and injection strength. Compare recovery against the stationary stack and the best individual exposure. Examine control counts alongside recoveries. This is an injection study on measured backgrounds.
5. Record a note, calculate a fixed-position dark-sky window, and export evidence with the selected coordinates, archive records, processing provenance, parameters, and results.

## Verification and scientific scope

```sh
python -m pip install pytest
python -m pytest tests -q
python scripts/validate_live.py
python scripts/validate_live.py --refresh
```

The [live validation record](docs/live-data-validation.json) documents ten NASA cutouts across two distinct observation dates for each of the five official targets. Some archive searches used a recorded observation list after an IRSA error. All ten test cutouts came from the archive. The [real-background injection record](docs/real-experiment-validation.json) used 4 compatible Barnard field exposures over 360.5 days. In 8 trials, shift-and-stack recovered 2, the stationary stack recovered 1, and the best single frame recovered 2. This small controlled run does not establish a performance advantage. The reproducible script runs the experiment on the bundled observations and writes its own report.

See the [processing methodology](docs/methodology.md), [capability limits](docs/status.md), and [judging walkthrough](docs/judging.md). This release supports exploratory wavelength samples and preliminary motion evidence. It leaves calibrated source spectroscopy, detector-specific PSF fitting, automated catalog vetting, blind performance tests, orbit inference, and shared moderation for further research.

## Sources and credit

- [NASA/IPAC IRSA SPHEREx](https://irsa.ipac.caltech.edu/Missions/spherex.html) and [DR1/QR3 access](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/) supply the authentic FITS observations and archive metadata.
- [SkyShift](https://github.com/Nsa-2026/skyshift) informed the FITS processing approach and supplies the recorded target lists. Adapted logic and data are credited in the source and [license notices](licenses/).
- [Driftnet](https://github.com/epsretriever/spherex-planet-x) informed the research flow and provenance design.
- Development used AI-assisted coding and documentation. Observation pixels and scientific outcomes come from the archive and the calculations in this repository. The laboratory labels all synthetic signals.

This publication makes use of data products from the Spectro-Photometer for the History of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of the Jet Propulsion Laboratory and the California Institute of Technology, and is funded by the National Aeronautics and Space Administration.
