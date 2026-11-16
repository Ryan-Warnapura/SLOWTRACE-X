# SPHEREx archive survey

The archive survey runs from a durable machine with a Python process and two SQLite files. Vercel serves the resulting evidence snapshots. The two measurements are full detector images processed and area searched for motion across compatible visits. The 500,000 target counts unique Level 2 observation IDs paired with their detector.

## Run a batch

Install `requirements.txt` and run from the repository root.

```sh
python scripts/run_bulk_survey.py --db work/bulk-survey.sqlite --pages 24 --images 40 --workers 6
python scripts/run_bulk_survey.py --db work/bulk-survey.sqlite --pages 40 --images 160 --workers 8
```

The same database resumes archive cursors, image claims and pending work. The default includes DR1 and QR3 and needs no archive account. `--release` or `--period` can scope an inventory run. `--seed-pilot public/survey.json` is optional and prioritizes exact products previously used in the published pilot. Discovery proceeds through actual public bucket listings even without a prior pilot. `--refresh-catalog` starts each prefix at the beginning to find earlier additions or reprocessed products. Completed observation identities stay completed. Use `--reanalyze OBSERVATION_ID` to explicitly rerun one identity, and `--retry-failed` for exhausted transient jobs.

Set `--watch 600` to repeat bounded batches. Keep both SQLite databases on a durable local volume and back them up using SQLite’s backup mechanism. The image workers share a local queue, and the planner can run on a separate process using the same machine and files. Use a single publisher for any output destination. An expired lease is logged and reclaimed. Outcomes and coverage commit in the same transaction, and older attempts remain available. Keep a worker near the public S3 bucket in `us-east-1` for extended runs. The initial images were approximately 65–66 MB per object, so processing 500,000 full objects would transfer roughly 33 TB at those sizes before retries. Sustained throughput depends on transfer rates, disk and memory. No permanent cloud compute worker is provisioned with this release.

## Evidence and publication

```sh
python scripts/run_bulk_survey.py --db work/bulk-survey.sqlite --pages 0 --images 0 \
  --motion-fields 8 --investigate 3 --output public/bulk-survey.json \
  --ledger public/bulk-evidence.jsonl.gz --publish-findings public/survey.json
python scripts/audit_bulk_snapshot.py public/bulk-survey.json public/bulk-evidence.jsonl.gz
```

The evidence export records each attempt, exact public source URL, SHA-256 of downloaded FITS bytes, size, native WCS, observation time, detector, local calibration metadata, quality masks, and coverage ranges. At larger sizes keep the gzip ledger on bulk storage and publish the small snapshot independently. The motion database retains exact cutout observations, tested parameters, analysis products, nominal uncertainty measures and catalog history. The website loads a bounded view of investigation records and recent detector outlines. The bulk totals are computed over the complete ledger. GitHub and Vercel publish these static snapshots after a successful export.

The public source ZIP leaves the full-image attempt ledger at its separate [download URL](https://slowtrace-x.vercel.app/bulk-evidence.jsonl.gz).

## Verified initial run

Three native batches completed 40, 160 and 300 distinct images in the same database. The ledger audit reconstructed 500 successes from 32.84 GB of source FITS and 1,911.60 deg² of quality-sampled image coverage. One controlled interruption expired before download and the same identity succeeded on reclaim. Image catalog discovery listed 75,007 distinct identities, and the remaining queue is resumable on the local worker.

DeepTrace completed 11 distinct fields and recorded one incomplete field. It used seven distinct exposures and measured 0.064017 deg² of common usable sky support. It retained 200 trial peaks. Six candidates received catalog investigations, four with complete Gaia and JPL responses. No association reached catalog-consistent status.

## Scientific scope

- Inventory, downloads and in-progress jobs remain separate from completed processing. Archive versions of an observation and detector share a stable identity. A successful intentional rerun increases operations while leaving the unique count unchanged.
- The worker decodes data, variance, zodiacal background and flags over the entire native detector image. It applies the documented quality policy and measures supported pixels. The image area is the union of accepted equal-area HEALPix cell centers at Nside 1024. Sampling approximates edges and small defects. Atlas outlines are native WCS perimeters.
- A spatial index identifies an automatic mesh of fields overlapped by the verified native WCS. The default mesh is approximately one degree between centers with five-arcminute research patches. At least three sufficiently separated and compatible epochs are required. DeepTrace runs on aligned cutouts with its existing wavelength, calibration, quality and variance gates. Each selected input and version is fingerprinted. Additional compatible visits can trigger a new analysis of the same field.
- A finer campaign can use `--motion-spacing-arcmin 10 --motion-db work/dense-motion.sqlite`, or a five-arcminute mesh where resources permit. Each motion database locks its spacing. A new database can replay the retained native results without downloading the full images again. Refining the mesh increases the number of WCS checks, cutouts and motion trials.
- Reported motion area is the union of HEALPix cell centers at Nside 32768 supported by the joint quality mask of selected, aligned epochs. It measures common image support at zero shift, with limits from the sampled patches and the velocity grid. The existing injection measurements describe their tested background and motion conditions. Survey-wide completeness and sensitivity remain unmeasured.
- The catalog process checks Gaia DR3 and JPL at bounded intervals, preserving unavailable results and their retry schedule. Trial peaks can arise from stationary structure, artifacts, or the velocity search. An independently supported catalog-consistent match and an unresolved peak have different evidentiary status. The 3D Solar System can show a matched published Horizons body where available. A trial direction by itself supplies no physical distance.

Driftnet’s scheduled patch searches, parallel blocks, separate catalog work and published coverage ledger informed this architecture. Its reported image total is based on its own processing methodology. [Driftnet methods](https://spherex-planet-x.vercel.app/about/)

SPHEREx inputs are the IRSA DR1 and QR3 Level 2 spectral images in the official anonymous cloud bucket. [NASA/IPAC cloud access](https://irsa.ipac.caltech.edu/cloud_access/#spherex)
