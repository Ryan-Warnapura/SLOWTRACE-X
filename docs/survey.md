# SPHEREx field surveys

The survey worker uses the same NASA archive access and DeepTrace engine as the observation desk. It builds a queue from a fixed challenge list, individual coordinates, or a deterministic tangent-plane grid. Field centers are ICRS degrees. A grid is a set of requests, and coverage between centers is not counted. Each field uses a bounded sample of up to eight exposures from one chosen detector. Add a different named survey to search another detector or image scale.

## Run and resume

Install `requirements.txt`, then run from the project root:

```sh
python scripts/run_survey.py --name "Challenge fields" --challenge --pixels 96 --max-fields 5
python scripts/run_survey.py --name "Northern field grid" --grid 269.5862 4.76883 3 3 3 --max-fields 3
```

`--grid` takes RA, declination, spacing in arcminutes, columns, and rows. Each `--field RA DEC` adds another center. Grid points can cross the RA origin without jumping across the sky. Set `--max-fields 0` to plan or export without downloading data. Use `--survey-id` with the ID printed by the worker to resume the same configuration, append grid fields, or export an existing state.

```sh
python scripts/run_survey.py --survey-id <survey-id> --max-fields 5
python scripts/run_survey.py --survey-id <survey-id> --retry --max-fields 3
python scripts/run_survey.py --survey-id <survey-id> --refresh --max-fields 5 --investigate 3
```

`--retry` queues errors and incomplete attempts again. `--refresh` queues previously finished fields for a new archive lookup as data releases change. Both preserve the earlier history. `--investigate` hands a bounded number of previously unchecked peaks to the catalog investigation code and persists each checked interpretation with its time, reasons, and query evidence. The release includes no credentials for scheduled infrastructure. For unattended use, run the same command from a scheduler or a dedicated process with an enduring local `--db` path and post or deploy the new read-only `--output` snapshot after each successful export. Keep a single publisher per snapshot path. The website reports the snapshot time and does not imply that a worker is running on Vercel.

The default database is `work/survey.sqlite`. Atomic transactions bind a field's attempt, observation summary, analysis and peak records. Workers claim fields with a time-limited lease. A replacement worker records an expired attempt and safely retries it. Analysis identities incorporate the survey method version, analysis configuration, original exposure URLs, observation time and wavelength, quality metadata, and SHA-256 digests over processed science, variance and flags. Identical inputs keep the same analysis and candidate IDs after a retry. Updated inputs generate a distinct record. Intersections of nearby fields can produce separate detections of the same apparent feature, so one record is not one unique object.

`public/survey.json` is an atomic export of the database. Preserve the SQLite database to resume its exact history. The export includes processing parameters, observation URLs, header-derived metadata, and input checksums for reproducing the processing. Host a distinct snapshot for each modest project. Larger surveys will need a paginated or partitioned public read model.

## How a field is evaluated

1. Query the IRSA DR1 and QR3 catalogs. Record live, partial, or recorded metadata status and any incomplete archive coverage. Retrieve authentic FITS from IRSA or its public S3 mirror and retain per-frame provenance, timestamps, wavelength and quality metadata. An explicitly chosen `--recorded-packet` can supply recorded observation pixels only for its exact field and raster, with that input type and its original capture timestamp included in the record.
2. Group quality-eligible exposures by detector, calibration version, and zodiacal subtraction state. Pick the largest same-band set within one nominal detector resolution element with exposures separated by at least half a day. Choose the longer time baseline on ties. Skip the motion analysis with fewer than three compatible epochs or invalid variance/mask support. The bandpass and PSF are still approximate.
3. Pass the selected reprojected pixels, variances, mask policy, and physical timestamps to DeepTrace. Search 25 west/south velocity pairs, including a stationary control. The default grid extends to three output pixels of end-to-end displacement along either image axis. Speed resolution in angular units therefore depends on the time baseline and pixel scale. This search fits linear trial motion; it does not solve for orbital acceleration or parallax.
4. Select review peaks from the engine's capped list where the trial motion gains at least the configured nominal S/N over the stationary trial and moves at least half an output pixel over the baseline. Store measured nominal S/N, stationary S/N, gain, flux proxy and variance, predicted position at each epoch, and the closest resampled pixel's brightness, wavelength, variance, and mask. The predicted positions are not independent celestial centroids. Nearby flux gradients, interpolation covariance, saturation, variable stars, and PSF changes can all create gain over the stationary control.

The review queue prioritizes larger nominal S/N gain, then larger nominal S/N. These are investigation priorities, not calibrated false-alarm probabilities. Peak extraction is limited to 20 raw peaks per analysis. Catalog consistency or an unresolved search does not confirm an object's identity. Candidate records carry the original exposures and versioned history; the dashboard can reopen those exposures with the same raster.

## Read the counts

- `planned`, `complete`, `empty`, `incomplete`, `errors`, `queued`, and `running` describe field jobs. `complete` requires an unqualified metadata response, successful bounded pixel retrieval and analysis. `empty` requires an available metadata query that actually returned zero observations. `incomplete` can still contain a scientific result from part of the requested data. A successful analysis with no retained peaks reports zero candidates explicitly.
- `fieldsAnalyzed` counts fields with an analysis, including those that encountered partial archive access. `uniqueExposuresAnalyzed` deduplicates official source URLs. `fieldExposuresAnalyzed` counts exposures contributing to distinct saved analyses across fields, configurations and refreshes. Reused inputs do not inflate this number.
- `usablePixelSamples` counts valid resampled science, variance and mask pixels in the selected exposures. Reprojected pixels are correlated. `trialGridPositions` is the number of configured shifts times output grid cells across distinct analyses, including cells without sufficient support. It is not a number of independent statistical trials.
- `elapsedSeconds` totals per-attempt elapsed time when available. It includes archive I/O as well as computation. It should not be interpreted as telescope exposure time or CPU time.
