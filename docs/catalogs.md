# Candidate catalog investigations

`science.catalogs.investigate(candidate)` compares supported candidate positions against live Gaia DR3 and JPL ephemerides. Inputs are decimal ICRS degrees and UTC MJD. The report contains the query URLs, catalog and observation epochs, candidate and predicted positions, angular residuals in arcseconds, and explicit catalog coverage limits. Each service can return `ok`, `partial`, or `unavailable`. A successful check with zero associations has a different meaning from an outage.

## Gaia DR3

The lookup uses the official Gaia@AIP DR3 mirror through its spatially indexed PostgreSQL TAP query, with the Gaia DR3 cone search at MAST as a fallback. Nearby rows are limited to 1,000. The J2016.0 search cone includes the supplied track extent and an allowance for proper motions up to approximately 12 arcseconds per year within the bounded cone. A capped cone or row set is an incomplete check. Each source ID is retained as a string to avoid losing precision in browsers.

The prediction applies Gaia's two proper-motion components in the local tangent plane. `pmra` includes `cos(dec)`. Positive catalog parallax and the built-in Astropy Earth barycentric position give an approximate observer parallax at the epoch. Available radial velocity adds perspective motion. Negative or missing parallax is omitted, and missing proper motion leaves the catalog direction stationary. A source can appear near the track through an unrelated superposition or an unresolved blend. This check does not account for Gaia's full astrometric covariance or SPHEREx point-spread-function mismatch.

## JPL SB Identification and Horizons

The first-pass SB Identification service provides a provisional small-body shortlist at the first and last usable positions. At most two targets are refined with JPL Horizons at the requested UTC epochs. The report gives residuals from the geocentric astrometric RA/Dec and range for each refinement. The bounded search and orbital uncertainties can miss objects. Returned first-pass row counts include uncertainty-expanded rows and do not count matches.

SPHEREx Level 2 FITS headers document the geocentric state and units, but the examples and explanatory supplement do not explicitly identify the Cartesian axes. The catalog tool does not use an unverified vector as ICRF. It labels the SB Identification query's Earth-surface proxy and Horizons' Earth-geocentric predictions. When the geocentric magnitude of the source FITS position is present, the report gives a conservative angular offset bound `asin(spacecraft radius / geocentric target range)`. A verified ICRF spacecraft position, if available, enables a first-order parallax adjustment. This does not refit differential light time or aberration.

## Interpretation

DeepTrace samples a trial motion grid. Agreement between a catalog prediction and the trial's sampled coordinates can guide follow-up. It cannot independently measure a trajectory. An automated `catalog-consistent` category requires a unique coherent match to positions derived from independent measurements with stated positional uncertainties. Catalog failures, unresolved ambiguity, and model-only positions retain `insufficient-evidence`. `artifact-suspect` marks unusable samples with no motion-stack improvement as a review priority. `unidentified` is scoped to the examined catalogs and the search tolerances. None of these labels confirms a discovery.

The [catalog-validation record](catalog-validation.json) describes the separate Ceres known-ephemeris control. Actual automated checks on trial peaks appear in the published survey snapshot. The Ceres control verifies the JPL query and angular comparison path using a known ephemeris position.

## Sources

- Gaia data are from ESA's Gaia mission and the Gaia Data Processing and Analysis Consortium. [Gaia DR3 documentation](https://gea.esac.esa.int/archive/documentation/GDR3/) · [Gaia@AIP query service](https://gaia.aip.de/cms/services/adql-postgresql/) · [MAST cone search](https://archive.stsci.edu/virtual-observatory)
- [NASA/JPL Small-Body Identification](https://ssd-api.jpl.nasa.gov/doc/sb_ident.html) · [NASA/JPL Horizons](https://ssd-api.jpl.nasa.gov/doc/horizons.html)
- [NASA/IPAC SPHEREx Explanatory Supplement](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf)
