"""Schedule repeatable DeepTrace pointings from completed native SPHEREx exposures."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import lru_cache
import json
import math
import time
import uuid
import warnings

import numpy as np
from astropy import units as u
from astropy.io import fits
from astropy.wcs import FITSFixedWarning, NoConvergence, WCS
from astropy_healpix import HEALPix

from . import archive, survey
from .coverage import _unit_points


METHOD = "archive-overlap/1"
FOV_ARCMIN = 5
MESH_DEG = 1
MOTION_NSIDE = 32768
MOTION_CELL_DEG2 = 360 * 360 / (math.pi * 12 * MOTION_NSIDE**2)
SPHERE = HEALPix(nside=MOTION_NSIDE, order="nested")

SCHEMA = """
CREATE TABLE IF NOT EXISTS motion_sources (
    row_id INTEGER PRIMARY KEY, source_id TEXT NOT NULL UNIQUE, detector INTEGER NOT NULL,
    mjd REAL NOT NULL, sha256 TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS motion_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS motion_source_rtree
    USING rtree(row_id,x_min,x_max,y_min,y_max,z_min,z_max);
CREATE TABLE IF NOT EXISTS motion_anchors (
    id TEXT PRIMARY KEY, ra REAL NOT NULL, dec REAL NOT NULL, detector INTEGER NOT NULL,
    label TEXT NOT NULL, priority INTEGER NOT NULL, dirty INTEGER NOT NULL,
    state TEXT NOT NULL, checked_at TEXT, field_id TEXT
);
CREATE INDEX IF NOT EXISTS motion_planner_queue ON motion_anchors(dirty,priority,checked_at);
CREATE TABLE IF NOT EXISTS motion_plans (
    field_id TEXT PRIMARY KEY REFERENCES fields(id), version TEXT NOT NULL, sources TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS motion_selections (
    field_id TEXT NOT NULL REFERENCES fields(id), version TEXT NOT NULL,
    PRIMARY KEY(field_id,version)
);
CREATE TABLE IF NOT EXISTS motion_catalog_jobs (
    candidate_id TEXT PRIMARY KEY REFERENCES candidates(id),
    lease TEXT NOT NULL, next_run REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS motion_coverage (
    cell_start INTEGER PRIMARY KEY, cell_end INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS motion_coverage_applied (
    analysis_id TEXT PRIMARY KEY REFERENCES analyses(id)
);
CREATE INDEX IF NOT EXISTS motion_field_analyses ON analyses(field_id);
CREATE INDEX IF NOT EXISTS motion_analysis_candidates ON candidates(analysis_id);
"""


class MotionStore(survey.SurveyStore):
    def __init__(self, database):
        super().__init__(database)
        self.db.executescript(SCHEMA)


def _config(detector):
    return survey.SurveyConfig(detector=detector, fov=FOV_ARCMIN)


@lru_cache(maxsize=256)
def _wcs(cards):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        return WCS(fits.Header(json.loads(cards))).celestial


def _prepare_source(record):
    url = archive.validate_url(record["sourceUrl"])
    match = archive.OBSERVATION_NAME.search(url)
    center = record["center"]
    detector = int(record["detector"])
    archive.checked_position(center["ra"], center["dec"], FOV_ARCMIN)
    sha256 = record["sha256"]
    if (not match or f"{match[1]}D{match[2]}" != record["id"] or int(match[2]) != detector
            or len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256)
            or not math.isfinite(float(record["mjd"]))):
        raise ValueError("A motion input must describe a verified NASA Level 2 detector exposure.")
    return {
        "id": record["id"], "url": url, "collection": record["collection"], "detector": detector,
        "mjd": record["mjd"], "center": center, "wcs": record["wcs"], "sha256": sha256,
        "metadataSource": "verified-native-fits",
        "metadataRetrievedAt": record.get("retrievedAt") or record.get("processedAt"),
        "calibrationVersion": record.get("calibrationVersion"),
        "fineAstrometryFlag": record.get("fineAstrometryFlag"),
        "wavelengthGrid": record.get("wavelengthGrid"),
    }


def _bound(source):
    cards = source["wcs"]
    wcs = _wcs(survey.canonical(cards))
    nx, ny = cards["NAXIS1"], cards["NAXIS2"]
    x = np.linspace(-0.5, nx - 0.5, 16)
    y = np.linspace(-0.5, ny - 0.5, 16)
    ra, dec = wcs.all_pix2world(
        np.r_[x, x, np.full_like(y, -0.5), np.full_like(y, nx - 0.5)],
        np.r_[np.full_like(x, -0.5), np.full_like(x, ny - 0.5), y, y], 0,
    )
    center = _unit_points(source["center"]["ra"], source["center"]["dec"])
    diagonal = float(np.arccos(np.clip(np.nanmin(_unit_points(ra, dec) @ center), -1, 1)))
    if not 0 < diagonal < math.radians(10):
        raise ValueError("Unexpected detector footprint in the SPHEREx WCS.")
    return center, diagonal + math.radians(0.05)


def _detector_pixels(source, ra, dec):
    try:
        return _wcs(survey.canonical(source["wcs"])).all_world2pix(ra, dec, 0, quiet=True)
    except (ValueError, RuntimeError, NoConvergence):
        return np.full_like(ra, np.nan), np.full_like(dec, np.nan)


def _anchors(source, radius, mesh_degrees):
    """Fixed ICRS latitude rings with longitude spacing scaled by latitude."""
    ra = source["center"]["ra"]
    dec = source["center"]["dec"]
    radius_deg = math.degrees(radius)
    named = [(r.ra, r.dec, r.label, 0) for r in survey.challenge_regions()]
    grid = []
    start = max(0, math.floor((dec + 90 - radius_deg) / mesh_degrees))
    stop = min(round(180 / mesh_degrees), math.ceil((dec + 90 + radius_deg) / mesh_degrees))
    for row in range(start, stop):
        latitude = -90 + (row + 0.5) * mesh_degrees
        columns = max(1, round(360 * math.cos(math.radians(latitude)) / mesh_degrees))
        step = 360 / columns
        # Include every possible longitude when the cone intersects a pole.
        if abs(dec) + radius_deg >= 90:
            offsets = range(columns)
        else:
            extent = math.degrees(math.asin(min(1, math.sin(radius) / math.cos(math.radians(dec)))))
            half = math.ceil(extent / step) + 1
            middle = math.floor(ra / step)
            offsets = range(columns) if 2 * half + 1 >= columns else range(middle - half, middle + half + 1)
        for col in offsets:
            longitude = round(((col % columns + 0.5) * step), 9)
            grid.append((longitude, latitude, f"ICRS {longitude:.4f}°, {latitude:+.4f}°", 1))
    choices = named + grid
    longitude, latitude = np.asarray([(a, d) for a, d, _, _ in choices]).T
    x, y = _detector_pixels(source, longitude, latitude)
    width, height = source["wcs"]["NAXIS1"], source["wcs"]["NAXIS2"]
    return [row for row, keep in zip(choices, (x >= 0) & (x < width) & (y >= 0) & (y < height)) if keep]


def ingest_sources(store, observations, mesh_degrees=MESH_DEG):
    """Add newly completed images; an unchanged observation never dirties a patch."""
    ingested = 0
    for record in observations:
        current = store.db.execute("SELECT sha256 FROM motion_sources WHERE source_id=?", (record["id"],)).fetchone()
        if current and current["sha256"] == record["sha256"]:
            continue
        source = _prepare_source(record)
        pos, radius = _bound(source)
        chord = 2 * math.sin(radius / 2)
        bounds = [value for axis in pos for value in (float(axis - chord), float(axis + chord))]
        anchors = _anchors(source, radius, mesh_degrees)
        detector = source["detector"]
        with store.transaction():
            cursor = store.db.execute(
                """INSERT INTO motion_sources(source_id,detector,mjd,sha256,payload) VALUES (?,?,?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET mjd=excluded.mjd,sha256=excluded.sha256,payload=excluded.payload
                WHERE sha256<>excluded.sha256 RETURNING row_id""",
                (source["id"], detector, source["mjd"], source["sha256"], survey.canonical(source)),
            ).fetchone()
            if cursor is None:
                continue
            store.db.execute("INSERT OR REPLACE INTO motion_source_rtree VALUES (?,?,?,?,?,?,?)",
                             (cursor["row_id"], *bounds))
            store.db.executemany(
                """INSERT INTO motion_anchors(id,ra,dec,detector,label,priority,dirty,state)
                VALUES (?,?,?,?,?,?,1,'unsearched') ON CONFLICT(id) DO UPDATE SET dirty=dirty+1""",
                [(survey.identifier("ma-", [lon, lat, detector]), lon, lat, detector, label, priority)
                 for lon, lat, label, priority in anchors],
            )
            ingested += 1
    return ingested


def _within_visit(source, coords):
    x, y = _detector_pixels(source, *coords)
    cards = source["wcs"]
    covered = bool(np.all((x >= 0) & (x < cards["NAXIS1"] - 1) & (y >= 0) & (y < cards["NAXIS2"] - 1)))
    return covered, x[-1], y[-1]


def _available_sources(store, anchor, config):
    ra, dec = anchor["ra"], anchor["dec"]
    x, y, z = map(float, _unit_points(ra, dec))
    grid, _ = archive.target_grid(ra, dec, config.fov, 32)
    coords = grid.all_pix2world([-.5, -.5, 31.5, 31.5, 15.5], [-.5, 31.5, -.5, 31.5, 15.5], 0)
    candidates = store.db.execute(
        """SELECT s.payload FROM motion_source_rtree r JOIN motion_sources s ON s.row_id=r.row_id
        WHERE r.x_min<=? AND r.x_max>=? AND r.y_min<=? AND r.y_max>=? AND r.z_min<=? AND r.z_max>=?
          AND s.detector=?
        ORDER BY s.mjd,s.source_id""",
        (x, x, y, y, z, z, anchor["detector"]),
    )
    out = []
    for row in candidates:
        source = json.loads(row["payload"])
        if source["fineAstrometryFlag"] not in (None, 0, "0"):
            continue
        covered, x, y = _within_visit(source, coords)
        if covered:
            source["patchWavelengthUm"] = _patch_wavelength(source.get("wavelengthGrid"), x, y)
            source.pop("wavelengthGrid", None)
            out.append(source)
    return out


def _distinct_epochs(sources, separation):
    accepted = []
    for exposure in sources:
        if not accepted or exposure["mjd"] - accepted[-1]["mjd"] >= separation:
            accepted.append(exposure)
    return len(accepted)


def _select(sources, config):
    by_calibration = {}
    for source in sources:
        by_calibration.setdefault(source["calibrationVersion"], []).append(source)
    options = []
    log_spacing = math.log1p(1 / survey.analysis.RESOLVING_POWER[config.detector])
    for group in by_calibration.values():
        no_wave = [s for s in group if s["patchWavelengthUm"] is None]
        if no_wave:
            options.append((False, group))
        measured = [(math.log(s["patchWavelengthUm"]) / log_spacing, s) for s in group
                    if s["patchWavelengthUm"] is not None]
        for shift in (0, 1/3, 2/3):
            bands = {}
            for band_position, source in measured:
                bands.setdefault(math.floor(band_position + shift), []).append(source)
            for compatible in bands.values():
                # The cutoff is checked again from actual cutout wavelengths. Earlier native products
                # may predate the compact wavelength grid, so include some for bounded verification.
                options.append((True, sorted(compatible + archive._spread(no_wave, config.observations),
                                             key=lambda s: (s["mjd"], s["id"]))))
    chosen = []
    score = None
    for band_selected, group in options:
        epochs = _distinct_epochs(group, config.min_epoch_separation_days)
        if epochs < config.min_epochs:
            continue
        scoring = (band_selected, min(epochs, config.observations), group[-1]["mjd"] - group[0]["mjd"])
        if score is None or scoring > score:
            chosen, score = group, scoring
    return archive._sample_observations(chosen, config.observations)[0]


def _patch_wavelength(calibration, x, y):
    if calibration is None:
        return None
    # The compact grid has already selected the wavelength component.
    table = {
        "X": [calibration["x"]],
        "Y": [calibration["y"]],
        "VALUES": [np.asarray(calibration["values"], dtype=float)[..., None]],
    }
    wave = archive.wavelength_map({**calibration["header"], "PV1_3W": 1}, table, x, y)
    return float(wave) if math.isfinite(wave) and wave > 0 else None


def _plan(store, max_scan, max_new):
    scheduled = 0
    # Materialize a bounded planner round before releasing read state. Claiming a field and
    # replacing a plan both take the same SQLite writer lock.
    to_check = store.db.execute(
        """SELECT * FROM motion_anchors WHERE dirty>0 ORDER BY priority,checked_at, rowid LIMIT ?""",
        (max_scan,),
    ).fetchall()
    for anchor in to_check:
        config = _config(anchor["detector"])
        available = _available_sources(store, anchor, config)
        inputs = _select(available, config)
        with store.transaction():
            active = store.db.execute(
                """SELECT f.status,a.dirty FROM motion_anchors a LEFT JOIN fields f ON f.id=a.field_id
                   WHERE a.id=?""", (anchor["id"],),
            ).fetchone()
            if active["dirty"] != anchor["dirty"] or active["status"] in ("queued", "running"):
                continue
            state = "waiting-epochs" if not inputs else "planned"
            store.db.execute("UPDATE motion_anchors SET dirty=0,state=?,checked_at=? WHERE id=?",
                             (state, archive.now(), anchor["id"]))
            if not inputs:
                continue
            label = f"Bulk SPHEREx motion survey · detector {config.detector}"
            settings = asdict(config)
            survey_id = survey.identifier("sv-", [label, settings])
            field_id = survey.identifier("field-", [survey_id, anchor["ra"], anchor["dec"]])
            fingerprint = survey.identifier("sources-", [METHOD, [(s["id"], s["sha256"]) for s in inputs]])
            prior = store.db.execute(
                "SELECT 1 FROM motion_selections WHERE field_id=? AND version=?", (field_id, fingerprint),
            ).fetchone()
            if prior:
                continue
            store.db.execute("INSERT OR IGNORE INTO surveys VALUES (?,?,?,?)",
                             (survey_id, label, archive.now(), survey.canonical(settings)))
            store.db.execute("""INSERT INTO fields(id,survey_id,label,ra,dec) VALUES (?,?,?,?,?)
                             ON CONFLICT(id) DO UPDATE SET status='queued'""",
                             (field_id, survey_id, anchor["label"], anchor["ra"], anchor["dec"]))
            store.db.execute("INSERT OR REPLACE INTO motion_plans VALUES (?,?,?)",
                             (field_id, fingerprint, survey.canonical(inputs)))
            store.db.execute("INSERT INTO motion_selections VALUES (?,?)", (field_id, fingerprint))
            store.db.execute("UPDATE motion_anchors SET field_id=? WHERE id=?", (field_id, anchor["id"]))
            scheduled += 1
        if scheduled >= max_new:
            break
    return scheduled


def _ranges(ids):
    if len(ids) == 0:
        return []
    divides = np.flatnonzero(np.diff(ids) > 1)
    starts = np.r_[ids[0], ids[divides + 1]]
    ends = np.r_[ids[divides], ids[-1]] + 1
    return np.column_stack((starts, ends)).tolist()


def common_coverage(ra, dec, config, frames):
    """Sample common accepted epoch pixels on an equal-area sky grid."""
    grid, _ = archive.target_grid(ra, dec, config.fov, config.pixels)
    cells = SPHERE.cone_search_lonlat(ra * u.deg, dec * u.deg, config.fov / 60 * u.deg)
    lon, lat = SPHERE.healpix_to_lonlat(cells)
    x, y = grid.all_world2pix(lon.degree, lat.degree, 0)
    p = config.pixels
    steps = np.rint([x, y]).astype(int)
    x, y = steps
    on_image = (0 <= x) & (x < p) & (0 <= y) & (y < p)
    locations = y[on_image] * p + x[on_image]
    good = np.ones(len(locations), dtype=bool)
    for frame in frames:
        data = np.asarray(frame["data"], dtype=float)[locations]
        variance = np.asarray(frame["variance"], dtype=float)[locations]
        flags = np.asarray(frame["mask"], dtype=np.int64)[locations]
        excluded = frame["metadata"].get("maskBits", archive.MASK_BITS)
        good &= np.isfinite(data) & np.isfinite(variance) & (variance > 0) & ((flags & excluded) == 0)
    return _ranges(np.sort(cells[on_image][good]))


def _process(field, config, plan):
    inputs = json.loads(plan["sources"])
    by_url = {source["url"]: source for source in inputs}
    fetched = {}

    def exact_inputs(*_):
        return {"status": "verified-image-selection", "totalAvailable": None, "observations": inputs,
                "searchCoverage": {"complete": False}, "truncated": True,
                "warnings": ["This bounded search uses overlapping products already processed by the bulk survey. Other archive epochs may exist."]}

    def fetch(url, ra, dec, fov, pixels):
        native_sha = by_url[url]["sha256"]
        image = archive.frame(url, ra, dec, fov, pixels, native_sha=native_sha)
        frame = {**image, "provenance": {**image["provenance"], "nativeSourceSha256AtSelection": native_sha}}
        retrieved_id = frame["metadata"]["id"]
        detector = frame["metadata"]["detector"]
        if retrieved_id not in (by_url[url]["id"], by_url[url]["id"].removesuffix(f"D{detector}")):
            raise ValueError("Retrieved cutout does not match the original detector exposure.")
        fetched[url] = frame
        return frame

    report, product, candidates = survey.process_field(field, config, search=exact_inputs, fetch=fetch)
    report["selectionVersion"] = plan["version"]
    report["selectedNativeSources"] = [{"id": s["id"], "url": s["url"], "sha256": s["sha256"]} for s in inputs]
    if product is not None:
        selected = [fetched[s["url"]] for s in product["observations"]]
        supported = common_coverage(field["ra"], field["dec"], config, selected)
        area = MOTION_CELL_DEG2 * sum(end - start for start, end in supported)
        product.update(motionCoverageRanges=supported, motionCoverageNside=MOTION_NSIDE, motionAreaDeg2=area)
        report["motionAreaDeg2"] = area
        report["message"] = report["message"].split(" Some archive data were unavailable", 1)[0]
        if report["frameFailures"]:
            report["message"] += " Some selected NASA images could not be cut out."
        else:
            report["status"] = "complete"
    return report, product, candidates


def _research_field(database, survey_id):
    store = MotionStore(database)
    try:
        field = store.claim(survey_id)
        if field is None:
            return None
        plan = store.db.execute("SELECT * FROM motion_plans WHERE field_id=?", (field["id"],)).fetchone()
        config = survey.SurveyConfig(**json.loads(store.db.execute(
            "SELECT config FROM surveys WHERE id=?", (survey_id,),
        ).fetchone()["config"]))
        try:
            report, product, candidates = _process(field, config, plan)
        except Exception as error:
            report = {"status": "error", "message": f"{type(error).__name__}: {str(error)[:350]}",
                      "selectionVersion": plan["version"]}
            product, candidates = None, ()
        store.finish(field, report, product, candidates)
        return report
    finally:
        store.close()


def _union_coverage(store):
    """Fold new immutable analyses into an interval union once, including after interruptions."""
    while True:
        with store.transaction():
            rows = store.db.execute(
                """SELECT a.id,a.payload FROM analyses a JOIN motion_plans p ON p.field_id=a.field_id
                LEFT JOIN motion_coverage_applied c ON c.analysis_id=a.id
                WHERE c.analysis_id IS NULL LIMIT 32""",
            ).fetchall()
            if not rows:
                break
            for row in rows:
                for start, end in json.loads(row["payload"]).get("motionCoverageRanges", []):
                    predecessor = store.db.execute(
                        "SELECT * FROM motion_coverage WHERE cell_start<=? ORDER BY cell_start DESC LIMIT 1",
                        (start,),
                    ).fetchone()
                    overlaps = store.db.execute("SELECT * FROM motion_coverage WHERE cell_start>? AND cell_start<=?",
                                                (start, end)).fetchall()
                    if predecessor and predecessor["cell_end"] >= start:
                        overlaps.insert(0, predecessor)
                    if overlaps:
                        start = min(start, overlaps[0]["cell_start"])
                        end = max(end, overlaps[-1]["cell_end"])
                        store.db.execute("DELETE FROM motion_coverage WHERE cell_start BETWEEN ? AND ?",
                                         (overlaps[0]["cell_start"], overlaps[-1]["cell_start"]))
                    store.db.execute("INSERT INTO motion_coverage VALUES (?,?)", (start, end))
                store.db.execute("INSERT INTO motion_coverage_applied VALUES (?)", (row["id"],))


def _investigate_one(store):
    from .catalogs import investigate

    timestamp = time.time()
    with store.transaction():
        row = store.db.execute(
            """SELECT c.id,c.payload,j.attempts FROM candidates c
            LEFT JOIN motion_catalog_jobs j ON j.candidate_id=c.id
            WHERE j.candidate_id IS NULL OR j.next_run<=?
            ORDER BY COALESCE(j.attempts,0),json_extract(c.payload,'$.evidence.snrGainOverStatic') DESC,c.id
            LIMIT 1""", (timestamp,),
        ).fetchone()
        if row is None:
            return None
        claim = uuid.uuid4().hex
        store.db.execute(
            """INSERT INTO motion_catalog_jobs(candidate_id,lease,next_run) VALUES (?,?,?)
            ON CONFLICT(candidate_id) DO UPDATE SET lease=excluded.lease,next_run=excluded.next_run,attempts=attempts+1""",
            (row["id"], claim, timestamp + survey.PASS_SECONDS),
        )
    try:
        result = investigate(json.loads(row["payload"]))
        complete = result["gaia"]["status"] == "ok" and result["jpl"]["status"] == "ok"
    except (OSError, ValueError, RuntimeError) as error:
        message = f"Catalog check did not finish: {type(error).__name__}: {str(error)[:300]}"
        result = {"checkedAt": archive.now(), "classification": "insufficient-evidence",
                  "reasons": [message], "warnings": [message], "status": "error"}
        complete = False
    with store.transaction():
        retry_days = 30 if result["classification"] == "catalog-consistent" else 7 if complete else 1
        changed = store.db.execute(
            "UPDATE motion_catalog_jobs SET next_run=? WHERE candidate_id=? AND lease=?",
            (time.time() + retry_days * 86400, row["id"], claim),
        )
        if changed.rowcount:
            store.record_investigation(row["id"], result)
    return row["id"]


def _snapshot(store, mesh_degrees):
    # Legacy-compatible fields and candidates are a bounded view keyed by survey detector.
    # The full history and exact totals remain in SQLite; only the view is clipped.
    snapshots = [store.snapshot(row["id"], max_fields=25) for row in
                 store.db.execute("SELECT id FROM surveys ORDER BY created_at").fetchall()]
    cells = store.db.execute("SELECT COALESCE(SUM(cell_end-cell_start),0) FROM motion_coverage").fetchone()[0]
    totals = dict(store.db.execute(
        """SELECT (SELECT COUNT(*) FROM motion_anchors) AS planned,
                  (SELECT COUNT(*) FROM motion_anchors WHERE dirty>0 AND field_id IS NULL) AS unsearched,
                  (SELECT COUNT(*) FROM motion_anchors WHERE dirty=0 AND field_id IS NULL) AS waitingEpochs,
                  (SELECT COUNT(*) FROM analyses) AS operations,
                  (SELECT COUNT(DISTINCT field_id) FROM analyses) AS fieldsAnalyzed,
                  (SELECT COUNT(*) FROM (SELECT DISTINCT f.ra,f.dec FROM fields f JOIN analyses a ON a.field_id=f.id))
                    AS skyRegionsAnalyzed,
                  (SELECT COUNT(DISTINCT json_extract(o.value,'$.id'))
                    FROM analyses a JOIN json_each(a.payload,'$.observations') o) AS exposuresAnalyzed,
                  (SELECT COUNT(*) FROM analyses a WHERE NOT EXISTS
                    (SELECT 1 FROM candidates c WHERE c.analysis_id=a.id)) AS zeroPeakAnalyses,
                  (SELECT COUNT(*) FROM fields f JOIN attempts t ON t.field_id=f.id AND t.number=f.attempt
                    WHERE f.status='complete' AND json_extract(t.report,'$.candidateCount')=0) AS zeroPeakFields,
                  (SELECT COUNT(*) FROM candidates) AS candidates,
                  (SELECT COUNT(DISTINCT candidate_id) FROM investigations) AS investigated,
                  (SELECT COALESCE(SUM(attempts),0) FROM motion_catalog_jobs) AS catalogAttempts,
                  (SELECT COUNT(*) FROM investigations) AS catalogRecords,
                  (SELECT COUNT(*) FROM fields WHERE status='complete') AS complete,
                  (SELECT COUNT(*) FROM fields WHERE status='incomplete') AS incomplete,
                  (SELECT COUNT(*) FROM fields WHERE status='error') AS errors,
                  (SELECT COUNT(*) FROM fields WHERE status='queued') AS queued,
                  (SELECT COUNT(*) FROM fields WHERE status='running') AS running,
                  (SELECT COUNT(*) FROM motion_sources) AS sourceObservations"""
    ).fetchone())
    totals.update(dict(store.db.execute(
        """WITH latest AS (
            SELECT i.payload FROM investigations i WHERE i.checked_at=(
                SELECT MAX(other.checked_at) FROM investigations other WHERE other.candidate_id=i.candidate_id))
        SELECT COUNT(CASE WHEN json_extract(payload,'$.classification')='catalog-consistent' THEN 1 END) AS knownMatches,
               COUNT(CASE WHEN json_extract(payload,'$.classification')='unidentified' THEN 1 END) AS unidentified,
               COUNT(CASE WHEN json_extract(payload,'$.gaia.status')='ok'
                           AND json_extract(payload,'$.jpl.status')='ok' THEN 1 END) AS catalogCompleted
        FROM latest"""
    ).fetchone()))
    totals.update(coverageSquareDegrees=cells * MOTION_CELL_DEG2, coverageCells=cells,
                  coverageNside=MOTION_NSIDE, unresolved=totals["candidates"] - totals["knownMatches"])
    candidates = [item for snap in snapshots for item in snap["candidates"]]
    candidates.sort(key=lambda c: (not bool(c.get("catalogInvestigation")), -c["evidence"]["snrGainOverStatic"],
                                   -c["evidence"]["nominalSnr"], c["id"]))
    return {
        "schemaVersion": 1, "pipelineVersion": METHOD, "surveyId": "bulk-motion",
        "label": "Bulk SPHEREx motion survey", "generatedAt": archive.now(),
        "config": {"meshDegreesAtEquator": mesh_degrees, "fov": FOV_ARCMIN, "minEpochs": 3},
        "summary": totals, "fields": [item for snap in snapshots for item in snap["fields"]],
        "analyses": [item for snap in snapshots for item in snap["analyses"]],
        "candidates": candidates[:500],
        "limitations": [
            f"Motion searches use sampled 5-arcminute patches on a {mesh_degrees * 60:g}-arcminute mesh plus the validation fields. Full detector image processing and sky coverage are tracked separately.",
            "Motion area is the unique equal-area pixel sum on a HEALPix Nside 32768 grid whose centers land on accepted resampled pixels in every selected epoch. It describes common zero-shift support, not sensitivity for all trial velocities.",
            "Catalog comparisons of trial positions are provisional. An orbit requires independent multi-epoch astrometry, and a successful patch search does not establish an absence of other moving objects.",
            "The website shows up to 25 recent fields per detector and 500 peaks, prioritizing catalog-reviewed evidence and nominal DeepTrace gain. The worker database retains the full history.",
        ],
    }


def run_motion(database, observations, *, max_fields=2, investigate=1, workers=2, retry=False,
               mesh_degrees=MESH_DEG, on_event=None):
    """Ingest completed native products and resume bounded field and catalog work."""
    if not 0 <= max_fields <= 100 or not 0 <= investigate <= 20 or not 1 <= workers <= 8:
        raise ValueError("Choose up to 100 motion fields, 20 catalog checks and 1–8 field workers per run.")
    if not 5/60 <= mesh_degrees <= 2 or not math.isclose(180 / mesh_degrees, round(180 / mesh_degrees)):
        raise ValueError("The motion mesh must evenly divide 180 degrees with 5–120 arcminute patches between centers.")
    store = MotionStore(database)
    try:
        with store.transaction():
            prior = store.db.execute("SELECT value FROM motion_settings WHERE key='mesh'").fetchone()
            if prior is None and store.db.execute("SELECT 1 FROM motion_sources LIMIT 1").fetchone():
                saved_mesh = MESH_DEG
            else:
                saved_mesh = mesh_degrees if prior is None else float(prior["value"])
            if not math.isclose(saved_mesh, mesh_degrees):
                raise ValueError("This database already has a different motion mesh. Use a separate database for another mesh.")
            store.db.execute("INSERT OR IGNORE INTO motion_settings VALUES ('mesh',?)", (str(saved_mesh),))
        ingested = ingest_sources(store, observations, mesh_degrees)
        scheduled = _plan(store, max(32, max_fields * 32), max_fields) if max_fields else 0
        if retry:
            store.db.execute(
                """UPDATE fields SET status='queued' WHERE status='error' OR
                   (status='incomplete' AND EXISTS(SELECT 1 FROM attempts a
                    WHERE a.field_id=fields.id AND a.number=fields.attempt
                      AND json_array_length(a.report,'$.frameFailures')>0))""",
            )
        if max_fields:
            jobs = store.db.execute(
                """SELECT survey_id FROM fields WHERE status='queued' OR (status='running' AND expires<?)
                   ORDER BY attempt,rowid LIMIT ?""", (time.time(), max_fields),
            ).fetchall()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for report in pool.map(lambda job: _research_field(database, job["survey_id"]), jobs):
                    if report and on_event:
                        on_event(report["status"], report["message"])
        for _ in range(investigate):
            candidate_id = _investigate_one(store)
            if not candidate_id:
                break
            if on_event:
                on_event("catalog", candidate_id)
        _union_coverage(store)
        snapshot = _snapshot(store, mesh_degrees)
        snapshot["run"] = {"sourcesAdded": ingested, "fieldsScheduled": scheduled}
        return snapshot
    finally:
        store.close()
