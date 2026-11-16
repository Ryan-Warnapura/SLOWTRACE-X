"""Durable, bounded SPHEREx field surveys using the existing DeepTrace engine."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid

import numpy as np

from . import analysis, archive


VERSION = "slowtrace-survey/1"
PASS_SECONDS = 1800
CHALLENGE_LABELS = {
    "barnard": "Barnard’s Star", "epsindib": "Epsilon Indi B", "wise0855": "WISE 0855−0714",
    "rwaur": "RW Aurigae", "rdra": "R Draconis",
}
LIMITATIONS = [
    "Counts describe this configured field sample. Sky between field centers has not been surveyed.",
    "A field can be analyzed with incomplete archive access. Source status and individual frame failures are retained.",
    "DeepTrace ranks nominal S/N over a finite velocity grid. Reprojection covariance, PSF mismatch and the search trials are not calibrated in the score.",
    "The candidate list is a limited review queue. Motion model coordinates are predictions, not independent centroid measurements or orbital fits.",
    "An empty analysis does not exclude motion, fainter objects or other wavelengths. No new astronomical object is confirmed.",
]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)


def identifier(prefix, value):
    return prefix + hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class SurveyConfig:
    fov: float = 5
    pixels: int = 64
    detector: int = 1
    observations: int = 8
    threshold: float = 6
    min_gain: float = 2
    min_epoch_separation_days: float = 0.5
    min_epochs: int = 3
    max_displacement_pixels: float = 3

    def __post_init__(self):
        archive.checked_position(0, 0, self.fov)
        if not 32 <= self.pixels <= 128 or not 1 <= self.detector <= 6:
            raise ValueError("Use 32–128 pixels and a detector between 1 and 6.")
        if not 3 <= self.observations <= 8 or not 3 <= self.min_epochs <= self.observations:
            raise ValueError("Choose 3–8 exposures, with at least 3 distinct epochs for a motion search.")
        if not (3 <= self.threshold <= 20 and 0 <= self.min_gain <= 20
                and .01 <= self.min_epoch_separation_days <= 30 and .5 <= self.max_displacement_pixels <= 8):
            raise ValueError("Check nominal S/N, gain, epoch separation and pixel displacement bounds.")


@dataclass(frozen=True)
class Region:
    ra: float
    dec: float
    label: str = ""

    def __post_init__(self):
        archive.checked_position(self.ra, self.dec, 5)


def challenge_regions():
    """Published example field centers, also accepted by the archive metadata fallback."""
    return [Region(**target["center"], label=CHALLENGE_LABELS[name])
            for name, target in archive._reference_catalog().items() if name in CHALLENGE_LABELS]


def grid_regions(ra, dec, spacing_arcmin, columns, rows):
    """Deterministic tangent-plane field centers, including RA wrap and high declinations."""
    archive.checked_position(ra, dec, 5)
    if not 1 <= columns <= 64 or not 1 <= rows <= 64 or not 1 <= spacing_arcmin <= 180:
        raise ValueError("Grid requires 1–64 rows and columns, with spacing 1–180 arcminutes.")
    if max(rows, columns) * spacing_arcmin > 1800:
        raise ValueError("One tangent-plane grid may span at most 30 degrees. Use multiple grids.")
    from astropy.wcs import WCS
    grid = WCS(naxis=2)
    grid.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    grid.wcs.crval = [ra, dec]
    grid.wcs.crpix = [(columns + 1) / 2, (rows + 1) / 2]
    grid.wcs.cdelt = [-spacing_arcmin / 60, -spacing_arcmin / 60]
    y, x = np.indices((rows, columns))
    longitude, latitude = grid.all_pix2world(x.ravel(), y.ravel(), 0)
    return [Region(round(float(a) % 360, 8) % 360, round(float(b), 8), f"Grid {int(j)+1}.{int(i)+1}")
            for a, b, i, j in zip(longitude, latitude, x.ravel(), y.ravel())]


SCHEMA = """
CREATE TABLE IF NOT EXISTS surveys (
    id TEXT PRIMARY KEY, label TEXT NOT NULL, created_at TEXT NOT NULL, config TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fields (
    id TEXT PRIMARY KEY, survey_id TEXT NOT NULL REFERENCES surveys(id), label TEXT NOT NULL,
    ra REAL NOT NULL, dec REAL NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 0, lease TEXT, expires REAL
);
CREATE INDEX IF NOT EXISTS field_queue ON fields(survey_id, status, expires);
CREATE TABLE IF NOT EXISTS attempts (
    field_id TEXT NOT NULL REFERENCES fields(id), number INTEGER NOT NULL,
    started_at TEXT NOT NULL, finished_at TEXT, report TEXT,
    PRIMARY KEY(field_id, number)
);
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY, field_id TEXT NOT NULL REFERENCES fields(id), payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL REFERENCES analyses(id), payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investigations (
    candidate_id TEXT NOT NULL REFERENCES candidates(id), checked_at TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY(candidate_id, checked_at)
);
"""


class SurveyStore:
    def __init__(self, database):
        file = Path(database)
        file.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(file, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self, write=True):
        self.db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def plan(self, label, config, regions):
        settings = asdict(config)
        key = identifier("sv-", [label, settings])
        fields = [(identifier("field-", [key, r.ra, r.dec]), key, r.label, r.ra, r.dec) for r in regions]
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO surveys VALUES (?, ?, ?, ?)", (key, label, archive.now(), canonical(settings)))
            self.db.executemany("INSERT OR IGNORE INTO fields (id,survey_id,label,ra,dec) VALUES (?,?,?,?,?)", fields)
        return key

    def requeue(self, survey_id, *, refresh=False):
        clause = "status IN ('complete','empty','incomplete','error')" if refresh else "status IN ('error','incomplete')"
        return self.db.execute(f"UPDATE fields SET status='queued' WHERE survey_id=? AND {clause}", (survey_id,)).rowcount

    def claim(self, survey_id, *, lease_seconds=PASS_SECONDS):
        with self.transaction():
            row = self.db.execute("""SELECT * FROM fields WHERE survey_id=? AND
                (status='queued' OR (status='running' AND expires<?)) ORDER BY attempt,rowid LIMIT 1""",
                                  (survey_id, time.time())).fetchone()
            if row is None:
                return None
            stamp = archive.now()
            if row["status"] == "running":
                report = {"status": "error", "message": "Worker lease expired before an atomic result was recorded."}
                self.db.execute("UPDATE attempts SET finished_at=?, report=? WHERE field_id=? AND number=?",
                                (stamp, canonical(report), row["id"], row["attempt"]))
            number, token = row["attempt"] + 1, uuid.uuid4().hex
            self.db.execute("UPDATE fields SET status='running',attempt=?,lease=?,expires=? WHERE id=?",
                            (number, token, time.time()+lease_seconds, row["id"]))
            self.db.execute("INSERT INTO attempts (field_id,number,started_at) VALUES (?,?,?)", (row["id"], number, stamp))
        return {**dict(row), "attempt": number, "lease": token, "status": "running", "startedAt": stamp}

    def finish(self, claim, report, product=None, candidates=()):
        with self.transaction():
            # Reject results from a worker whose lease was reclaimed while it was working.
            updated = self.db.execute("""UPDATE fields SET status=?,lease=NULL,expires=NULL
                WHERE id=? AND lease=? AND status='running'""", (report["status"], claim["id"], claim["lease"]))
            if updated.rowcount != 1:
                return False
            if product:
                self.db.execute("INSERT OR IGNORE INTO analyses VALUES (?,?,?)", (product["id"], claim["id"], canonical(product)))
                self.db.executemany("INSERT OR IGNORE INTO candidates VALUES (?,?,?)",
                                    [(c["id"], product["id"], canonical(c)) for c in candidates])
            self.db.execute("UPDATE attempts SET finished_at=?,report=? WHERE field_id=? AND number=?",
                            (archive.now(), canonical(report), claim["id"], claim["attempt"]))
        return True

    def record_investigation(self, candidate_id, result):
        self.db.execute("INSERT OR IGNORE INTO investigations VALUES (?,?,?)",
                        (candidate_id, result["checkedAt"], canonical(result)))

    def snapshot(self, survey_id, max_fields=None):
        with self.transaction(write=False):
            return self._snapshot(survey_id, max_fields)

    def _snapshot(self, survey_id, max_fields):
        survey = self.db.execute("SELECT * FROM surveys WHERE id=?", (survey_id,)).fetchone()
        if survey is None:
            raise ValueError("Survey ID not found in this database.")
        config = json.loads(survey["config"])
        fields = []
        summary = dict(planned=0, queued=0, running=0, complete=0, empty=0, incomplete=0,
                       errors=0, candidates=0, uniqueExposuresAnalyzed=0, fieldExposuresAnalyzed=0,
                       usablePixelSamples=0, trialGridPositions=0, elapsedSeconds=0)
        rows = self.db.execute(
            "SELECT * FROM fields WHERE survey_id=? ORDER BY rowid " +
            ("DESC LIMIT ?" if max_fields is not None else ""),
            (survey_id, max_fields) if max_fields is not None else (survey_id,),
        ).fetchall()
        for row in rows:
            history = []
            for a in self.db.execute("SELECT * FROM attempts WHERE field_id=? ORDER BY number DESC", (row["id"],)):
                report = json.loads(a["report"]) if a["report"] else {"status": "running"}
                history.append(dict(attempt=a["number"], startedAt=a["started_at"], finishedAt=a["finished_at"], **report))
                summary["elapsedSeconds"] += report.get("elapsedSeconds", 0)
            fields.append(dict(id=row["id"], label=row["label"], ra=row["ra"], dec=row["dec"],
                               fov=config["fov"], detector=config["detector"], status=row["status"],
                               latest=history[0] if history else None, history=history))
            summary["errors" if row["status"] == "error" else row["status"]] += 1
        unique_sources = set()
        products = {}
        args = [survey_id]
        filter_fields = ""
        if max_fields is not None:
            filter_fields = " AND f.id IN (" + ",".join("?" for _ in rows) + ")"
            args.extend(row["id"] for row in rows)
        for row in self.db.execute("""SELECT a.* FROM analyses a JOIN fields f ON f.id=a.field_id
                WHERE f.survey_id=?""" + filter_fields, args):
            product = json.loads(row["payload"])
            products[product["id"]] = product
            unique_sources.update(o["url"] for o in product["observations"])
            summary["fieldExposuresAnalyzed"] += len(product["observations"])
            summary["usablePixelSamples"] += product["usablePixelSamples"]
            summary["trialGridPositions"] += product["trialGridPositions"]
        candidates = []
        for row in self.db.execute("""SELECT c.* FROM candidates c JOIN analyses a ON c.analysis_id=a.id
                JOIN fields f ON a.field_id=f.id WHERE f.survey_id=?""" + filter_fields, args):
            candidate = json.loads(row["payload"])
            checks = [json.loads(i["payload"]) for i in self.db.execute(
                "SELECT payload FROM investigations WHERE candidate_id=? ORDER BY checked_at", (candidate["id"],))]
            if checks:
                candidate["catalogInvestigation"] = checks[-1]
                candidate["classification"] = checks[-1]["classification"]
                candidate["history"].extend(dict(at=c["checkedAt"], classification=c["classification"],
                                                  action="Catalog investigation", reasons=c.get("reasons", [])) for c in checks)
            candidates.append(candidate)
        candidates.sort(key=lambda c: (-c["evidence"]["snrGainOverStatic"], -c["evidence"]["nominalSnr"], c["id"]))
        summary.update(planned=len(fields), candidates=len(candidates), uniqueExposuresAnalyzed=len(unique_sources),
                       elapsedSeconds=round(summary["elapsedSeconds"], 2))
        summary["fieldsAnalyzed"] = len({a["fieldId"] for a in products.values()})
        return dict(schemaVersion=1, pipelineVersion=VERSION, surveyId=survey_id, label=survey["label"],
                    createdAt=survey["created_at"], generatedAt=archive.now(), config=config, summary=summary, fields=fields,
                    candidates=candidates, analyses=list(products.values()), limitations=LIMITATIONS)


def publish_snapshot(store, survey_id, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = store.snapshot(survey_id)
    fd, temporary = tempfile.mkstemp(prefix=f"{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            file.write(canonical(snapshot) + "\n")
            file.flush()
            os.fsync(file.fileno())
        # A Windows reader can briefly lock the currently published file.
        for attempt in range(6):
            try:
                os.replace(temporary, output)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (2 ** attempt))
    finally:
        Path(temporary).unlink(missing_ok=True)
    return snapshot


def _quality(frame):
    metadata = frame["metadata"]
    return dict(badFraction=metadata.get("badFraction"), saturatedFraction=metadata.get("saturatedFraction"),
                zodiSubtracted=metadata.get("zodiSubtracted"), calibrationVersion=metadata.get("calibrationVersion"),
                flagsPresent=metadata.get("flagsPresent", []), psfMatched=metadata.get("psfMatched", False))


def _observation(source, frame, input_kind):
    metadata = frame["metadata"]
    return dict(id=source["id"], fitsObservationId=metadata["id"], url=source["url"], collection=source["collection"],
                mjd=metadata["mjd"], date=metadata["date"], wavelengthUm=metadata.get("wavelengthCenter"),
                detector=metadata["detector"], observerState=metadata.get("observerState"), quality=_quality(frame),
                metadataSource=source.get("metadataSource"), metadataRetrievedAt=source.get("metadataRetrievedAt"),
                inputKind=input_kind, provenance=frame["provenance"])


def _compatible_frames(items, config):
    """Choose comparable calibration/background, wavelength and independent timestamps."""
    groups = {}
    for item in items:
        metadata = item[1]["metadata"]
        wave = metadata.get("wavelengthCenter")
        if (metadata["detector"] != config.detector or wave is None or not math.isfinite(wave) or wave <= 0
                or not math.isfinite(metadata["mjd"]) or metadata.get("badFraction", 1) > .35):
            continue
        key = (metadata.get("calibrationVersion"), metadata.get("zodiSubtracted"))
        groups.setdefault(key, []).append(item)
    best = []
    best_score = (0, 0)
    tolerance = 1 + 1 / analysis.RESOLVING_POWER[config.detector]
    for group in groups.values():
        for _, base, _ in group:
            wave = base["metadata"]["wavelengthCenter"]
            window = [i for i in group if wave <= i[1]["metadata"]["wavelengthCenter"] <= wave * tolerance]
            distinct = []
            for item in sorted(window, key=lambda i: i[1]["metadata"]["mjd"]):
                if not distinct or item[1]["metadata"]["mjd"] - distinct[-1][1]["metadata"]["mjd"] >= config.min_epoch_separation_days:
                    distinct.append(item)
            if distinct:
                span = distinct[-1][1]["metadata"]["mjd"] - distinct[0][1]["metadata"]["mjd"]
                score = (len(distinct), span)
                if score > best_score:
                    best, best_score = distinct, score
    return best


def _measure_epochs(peak, selected, values, variances, masks, grid, scale, reference_mjd, backgrounds):
    epochs = []
    vx, vy = peak["velocityWestArcsecDay"], peak["velocitySouthArcsecDay"]
    for i, (source, frame, _) in enumerate(selected):
        metadata = frame["metadata"]
        dt = metadata["mjd"] - reference_mjd
        x, y = peak["x"] + dt * vx / scale, peak["y"] + dt * vy / scale
        ra, dec = (float(v) for v in grid.all_pix2world(x, y, 0))
        xp, yp = round(x), round(y)
        epoch = dict(observationId=source["id"], mjd=metadata["mjd"], ra=ra, dec=dec,
                     positionKind="predicted-track", observerState=metadata.get("observerState"),
                     wavelengthUm=None, surfaceBrightnessMjySr=None, variance=None, flagBits=None,
                     backgroundMjySr=backgrounds[i], sampleValid=False, valid=False)
        if 0 <= yp < values.shape[1] and 0 <= xp < values.shape[2]:
            index = yp * values.shape[2] + xp
            epoch.update(flagBits=int(frame["mask"][index]), wavelengthUm=frame["wavelength"][index])
            if not masks[i, yp, xp]:
                epoch.update(surfaceBrightnessMjySr=float(values[i, yp, xp]), variance=float(variances[i, yp, xp]), sampleValid=True, valid=True)
        epochs.append(epoch)
    return epochs


def process_field(field, config, *, search=archive.search, fetch=archive.frame, fetch_workers=2, recorded_packet=None):
    """Process a bounded field atomically. The caller handles storage and retry scheduling."""
    start = time.monotonic()
    report = dict(status="error", observationsFetched=0, observationsAnalyzed=0, usablePixelSamples=0,
                  archiveTotal=None, searchStatus=None, message="", notes=[], frameFailures=[], observations=[])

    def finish(status, message, product=None, candidates=()):
        report.update(status=status, message=message, elapsedSeconds=round(time.monotonic()-start, 2))
        return report, product, candidates

    ra, dec = field["ra"], field["dec"]
    if recorded_packet is not None:
        q = recorded_packet["search"]["query"]
        if (q["ra"], q["dec"], q["fov"], q["detector"]) != (ra, dec, config.fov, config.detector):
            recorded_packet = None
    try:
        result = search(ra, dec, config.fov, config.detector, config.observations)
    except (archive.ArchiveError, OSError) as error:
        if recorded_packet is None:
            return finish("error", str(error)[:500])
        result = recorded_packet["search"]
        report["notes"].append("Live metadata unavailable. Using the explicitly selected recorded NASA observation packet.")
    report.update(searchStatus=result["status"], archiveTotal=result["totalAvailable"],
                  searchCoverage=result.get("searchCoverage"),
                  queryUrls=result.get("queryUrls", []), archiveChecked=result.get("archiveChecked"),
                  searchQueriedAt=result.get("queriedAt"), observationSampleTruncated=result.get("truncated", False))
    report["notes"].extend(result.get("warnings", []))
    sources = list({s["url"]: s for s in result["observations"]}.values())[:config.observations]
    incomplete_lookup = result["status"] != "live" or (result.get("searchCoverage") or {}).get("complete") is False
    if not sources:
        if incomplete_lookup:
            return finish("incomplete", "Available archive portions returned no exposures. The search was incomplete.")
        return finish("empty", "The archive returned no exposures in the requested detector at this field center.")
    cached = {} if recorded_packet is None else {f["provenance"]["sourceUrl"]: f for f in recorded_packet["frames"]
                                                if f["width"] == config.pixels and f["height"] == config.pixels}

    def load(source):
        try:
            frame = fetch(source["url"], ra, dec, config.fov, config.pixels)
            return source, frame, "archive-retrieval", None
        except Exception as error:
            if source["url"] in cached:
                return source, cached[source["url"]], "recorded-observation-pixels", type(error).__name__
            return source, None, None, type(error).__name__

    with ThreadPoolExecutor(max_workers=min(3, max(1, fetch_workers))) as pool:
        responses = list(pool.map(load, sources))
    items = [(s, f, k) for s, f, k, _ in responses if f is not None]
    report["frameFailures"] = [dict(id=s["id"], url=s["url"], error=err, usedRecordedPixels=f is not None)
                               for s, f, _, err in responses if err]
    report["observationsFetched"] = sum(k == "archive-retrieval" for _, _, k in items)
    report["recordedFramesUsed"] = sum(k == "recorded-observation-pixels" for _, _, k in items)
    report["observations"] = [_observation(s, f, k) for s, f, k in items]
    selected = _compatible_frames(items, config)
    report["comparableEpochs"] = len(selected)
    if len(selected) < config.min_epochs:
        return finish("incomplete", f"Only {len(selected)} independent comparable epochs; {config.min_epochs} are required for a motion search.")

    values = np.asarray([f["data"] for _, f, _ in selected], dtype=float).reshape(-1, config.pixels, config.pixels)
    variance = np.asarray([f["variance"] for _, f, _ in selected], dtype=float).reshape(values.shape)
    flags = np.asarray([f["mask"] for _, f, _ in selected], dtype=np.int64).reshape(values.shape)
    mask_bits = np.asarray([f["metadata"].get("maskBits", archive.MASK_BITS) for _, f, _ in selected])[:, None, None]
    masks = ((flags & mask_bits) != 0) | ~np.isfinite(values) | ~np.isfinite(variance) | (variance <= 0)
    observations = [_observation(s, f, k) for s, f, k in selected]
    mjds = [o["mjd"] for o in observations]
    span, scale = mjds[-1]-mjds[0], config.fov*60/config.pixels
    max_speed = config.max_displacement_pixels*scale/span
    axis = (0, -max_speed, -max_speed/2, max_speed/2, max_speed)
    vectors = [(x, y) for y in axis for x in axis]
    input_signatures = []
    for index, observation in enumerate(observations):
        digest = hashlib.sha256()
        for array in (values[index], variance[index], flags[index]):
            digest.update(np.asarray(array, dtype=array.dtype.newbyteorder("<")).tobytes())
        metadata = dict(source=observation["url"], mjd=observation["mjd"], wavelengthUm=observation["wavelengthUm"],
                        detector=observation["detector"], quality=observation["quality"])
        input_signatures.append([metadata, digest.hexdigest()])
    analysis_id = identifier("an-", [VERSION, field["id"], asdict(config), input_signatures])
    try:
        result = analysis.analyze_stack(values, variance, masks, mjds, pixel_arcsec=scale,
                                        wavelengths_um=[o["wavelengthUm"] for o in observations],
                                        detector_ids=[config.detector]*len(observations), velocities_arcsec_day=vectors,
                                        threshold_snr=config.threshold)
    except ValueError as error:
        return finish("incomplete", str(error))
    report.update(observationsAnalyzed=len(observations), usablePixelSamples=int(np.count_nonzero(~masks)),
                  baselineDays=result["baselineDays"], analysisId=analysis_id)
    product = dict(id=analysis_id, fieldId=field["id"], method=result["method"], parameters=asdict(config),
                   observations=observations, inputSignatures=input_signatures, referenceMjd=result["referenceMjd"],
                   baselineDays=result["baselineDays"], usablePixelSamples=report["usablePixelSamples"],
                   trialGridPositions=len(vectors)*config.pixels**2, velocitiesArcsecDay=result["velocitiesArcsecDay"],
                   retainedSourceIds=[o["id"] for o in observations], notes=result["notes"],
                   peakCountFromEngine=len(result["candidates"]), peakCountCappedAt=20)
    grid, _ = archive.target_grid(ra, dec, config.fov, config.pixels)
    candidates = []
    for peak in result["candidates"]:
        vx, vy = peak["velocityWestArcsecDay"], peak["velocitySouthArcsecDay"]
        gain = peak["snrGainOverStatic"]
        displacement = math.hypot(vx, vy)*span/scale
        if gain is None or gain < config.min_gain or displacement < .5:
            continue
        candidate_ra, candidate_dec = (float(v) for v in grid.all_pix2world(peak["x"], peak["y"], 0))
        epochs = _measure_epochs(peak, selected, values, variance, masks, grid, scale, result["referenceMjd"], result["backgroundsMjySr"])
        evidence = dict(peak, displacementPixels=displacement, baselineDays=span, selectedFrameCount=len(observations),
                        epochMeasurements=epochs, validTrackSamples=sum(e["sampleValid"] for e in epochs),
                        measurementCaveat="Nearest valid resampled pixel at predicted motion-grid position. Neither centroid astrometry nor calibrated point-source flux.")
        candidate_id = identifier("stx-", [analysis_id, peak["x"], peak["y"], vx, vy])
        candidates.append(dict(id=candidate_id, fieldId=field["id"], analysisId=analysis_id, ra=candidate_ra, dec=candidate_dec,
                               field=dict(ra=ra, dec=dec, fov=config.fov, detector=config.detector), analysisPixels=config.pixels,
                               referenceMjd=result["referenceMjd"], detector=config.detector, fov=config.fov,
                               classification="insufficient-evidence", evidence=evidence, observations=observations,
                               history=[dict(at=archive.now(), classification="insufficient-evidence", action="Extracted from DeepTrace trial grid")]))
    report["candidateCount"] = len(candidates)
    message = f"Analyzed {len(observations)} comparable epochs and retained {len(candidates)} motion-trial peaks for review."
    limited = incomplete_lookup or report["frameFailures"]
    if limited:
        message += " Some archive data were unavailable or came from a recorded list."
    return finish("incomplete" if limited else "complete", message, product, candidates)


def run_pending(store, survey_id, config, max_fields, *, fetch_workers=2, recorded_packet=None, on_start=None, on_finish=None):
    """Resume queued work. The limit is per invocation, not a goal or a claim of coverage."""
    for _ in range(max_fields):
        field = store.claim(survey_id)
        if field is None:
            break
        if on_start:
            on_start(field)
        try:
            report, product, candidates = process_field(field, config, fetch_workers=fetch_workers, recorded_packet=recorded_packet)
        except Exception as error:
            report = dict(status="error", message=f"{type(error).__name__}: {str(error)[:400]}")
            product, candidates = None, ()
        if store.finish(field, report, product, candidates) and on_finish:
            on_finish(field, report)
