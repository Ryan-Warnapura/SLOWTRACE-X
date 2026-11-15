# Capability and verification status

This document distinguishes implementation scope from validation. A UI label or successful request is not scientific validation. See the repository's recorded test results for measured runs; results are not pre-filled here.

| Area | Scope and interpretation |
| --- | --- |
| Official challenge | Coordinate search, genuine SPHEREx cutouts and temporal comparison are the primary workflow |
| Spectral exploration | Observed samples with wavelength metadata; no claim of a complete calibrated 102-channel source spectrum |
| DeepTrace / motion search | Experimental bounded shift-and-stack; formal evidence, no calibrated discovery probability |
| Candidate verification | Provenance, quality and competing explanations; automated catalog vetting is not implemented |
| Experiment lab | Seeded synthetic sources on real backgrounds; empirical per-run outcomes only |
| Follow-up planner | Implemented fixed-ICRS geometric visibility and UTC darkness calculation; 11 unit tests passed locally |
| Citizen participation | Public observation inspection; no claim of a staffed moderation or scientific confirmation network |
| Atlas | Sky navigation/context; display imagery is not quantitative scientific evidence |
| Reports | Reproducible parameters/provenance and explicitly preliminary interpretation |

## Incomplete research capabilities

Production detector-aware ePSF fitting, full calibration-systematic covariance, automated star/galaxy subtraction, validated machine-learning artifact classification, orbital determination, parallax-aware distant-planet searches, calibrated population-level false-discovery rates, blind independent holdout validation and a peer-reviewed discovery-verification process remain outside the validated scope. Do not infer these capabilities from the product's research vision.

No detection-performance improvement, confirmed new object, Planet X probability or survey completeness is asserted without recorded measurements. Known-target retrieval validates data access; it does not by itself validate motion, variability or source recovery.

Planner verification: `python -m pytest tests/test_planner.py -q` passed 11 tests on November 15, 2026. Tests cover the celestial-pole altitude invariant, an invisible opposite pole, UTC boundaries, darkness/altitude windows, finite JSON values and invalid input. This validates geometric behavior, not an observational discovery or telescope feasibility assessment.

## References and licensing

- [SPHEREx Planet X](https://github.com/epsretriever/spherex-planet-x), MIT ©2026 epsretriever: reviewed reference project; any reused metadata/source must retain its notice.
- [SkyShift](https://github.com/Nsa-2026/skyshift), Apache-2.0: reviewed reference and source of adapted wavelength-table/quality-flag handling. See `licenses/` for the retained license.
- [NASA/IPAC IRSA SPHEREx](https://irsa.ipac.caltech.edu/Missions/spherex.html): observational data and archive documentation.
- Astropy, NumPy, SciPy, FastAPI, Vite, React and the listed UI packages: dependencies, not scientific endorsements.

The application is an independent Space Apps project and is not endorsed by NASA, IPAC or the reference projects. Code/documentation were developed with AI assistance; observational data are supplied by the cited archive.
