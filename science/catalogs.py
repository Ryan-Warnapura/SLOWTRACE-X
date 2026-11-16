"""Bounded Gaia DR3 and NASA/JPL checks of SPHEREx candidate evidence.

Catalog proximity is an association test. Trial-track points are not independent
centroids, and catalog nonmatches never establish a discovery.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode
from xml.parsers.expat import ExpatError

import numpy as np
import requests
from astropy import units as u
from astropy.coordinates import Angle, get_body_barycentric
from astropy.io.votable import parse
from astropy.time import Time


GAIA_AIP = "https://gaia.aip.de/tap/sync"
GAIA_MAST = "https://mast.stsci.edu/vo-conesearch/api/v0.1/gaiadr3"
SB_IDENT = "https://ssd-api.jpl.nasa.gov/sb_ident.api"
HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
AU_KM = u.au.to(u.km)
MAS_TO_RAD = u.mas.to(u.rad)
MAX_GAIA_ROWS = 1000
MAX_RESPONSE_BYTES = 4_000_000
MAX_JPL_EPOCHS = 2
MAX_HORIZONS_TARGETS = 2
GAIA_COLUMNS = (
    "source_id", "ra", "dec", "ref_epoch", "pmra", "pmdec", "parallax",
    "phot_g_mean_mag", "ruwe", "radial_velocity",
)


class CatalogError(RuntimeError):
    """Catalog unavailable, invalid, or outside the response budget."""


@dataclass(frozen=True)
class Epoch:
    ra: float
    dec: float
    mjd: float
    kind: str = "predicted-track"
    observation_id: str | None = None
    observer_position_km: tuple[float, float, float] | None = None
    observer_velocity_km_s: tuple[float, float, float] | None = None
    uncertainty_arcsec: float | None = None
    observer_radius_km: float | None = None

    def json(self):
        return dict(ra=self.ra, dec=self.dec, mjd=self.mjd, positionKind=self.kind,
                    observationId=self.observation_id, positionUncertaintyArcsec=self.uncertainty_arcsec,
                    observerPositionKm=self.observer_position_km, observerVelocityKmS=self.observer_velocity_km_s,
                    observerRadiusKm=self.observer_radius_km)


def _float(value):
    if isinstance(value, bool) or np.ma.is_masked(value):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _bounded(value, name, minimum, maximum):
    result = _float(value)
    if result is None or not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return result


def _state_vector(value, max_norm):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    vector = tuple(_float(component) for component in value)
    if any(component is None for component in vector) or not 0 < math.hypot(*vector) <= max_norm:
        return None
    return vector


def _parse_epoch(point):
    ra = _bounded(point.get("ra"), "RA", 0, 360) % 360
    dec = _bounded(point.get("dec"), "Declination", -90, 90)
    mjd = _bounded(point.get("mjd"), "MJD (UTC)", 50000, 70000)
    state = point.get("observerState") or {}
    if not isinstance(state, dict):
        state = {}
    raw_position = _state_vector(state.get("positionKm"), 100_000) if state.get("origin") == "GEOCENTER" else None
    if raw_position is not None and state.get("frame") in {"ICRF", "J2000"}:
        position = raw_position
        velocity = _state_vector(state.get("velocityKmS"), 100)
    else:
        position = velocity = None
    kind = point.get("positionKind")
    kind = kind if kind in {"measured-centroid", "predicted-track", "reference-position"} else "predicted-track"
    error = _float(point.get("positionUncertaintyArcsec"))
    error = error if error is not None and 0 < error <= 120 else None
    observation_id = point.get("observationId")
    return Epoch(ra, dec, mjd, kind, str(observation_id)[:100] if observation_id else None,
                 position, velocity, error, math.hypot(*raw_position) if raw_position else None)


def _fetch(url, params, timeout=20):
    try:
        with requests.get(url, params=params, timeout=(4, timeout), stream=True,
                          allow_redirects=False, headers={"User-Agent": "SLOWTRACE-X/2.0"}) as response:
            if response.status_code != 200:
                raise CatalogError(f"Catalog returned HTTP {response.status_code}.")
            content = bytearray()
            for chunk in response.iter_content(chunk_size=16_384):
                content.extend(chunk)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise CatalogError("Catalog response exceeded the byte limit.")
            return bytes(content)
    except requests.RequestException as exc:
        raise CatalogError(f"Catalog request failed ({type(exc).__name__}).") from exc


def _url(base, params):
    return f"{base}?{urlencode(params)}"


def _unit(ra_deg, dec_deg):
    ra, dec = np.radians([ra_deg, dec_deg])
    return np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)])


def _radec(vector):
    x, y, z = vector
    return float(np.degrees(np.arctan2(y, x)) % 360), float(np.degrees(np.arctan2(z, np.hypot(x, y))))


def _separation_arcsec(ra, dec, epoch):
    first, second = _unit(ra, dec), _unit(epoch.ra, epoch.dec)
    return float(np.degrees(np.arctan2(np.linalg.norm(np.cross(first, second)), first @ second)) * 3600)


def _gaia_rows(raw):
    try:
        if raw.lstrip().startswith(b"<"):
            votable = parse(io.BytesIO(raw))
            infos = [*votable.infos, *(i for resource in votable.resources for i in resource.infos)]
            if any(i.name == "QUERY_STATUS" and i.value == "ERROR" for i in infos):
                raise CatalogError("Gaia TAP reported a query failure.")
            table = votable.get_first_table().to_table(use_names_over_ids=True)
            columns = set(table.colnames)
            overflow = any(i.name == "QUERY_STATUS" and i.value == "OVERFLOW" for i in infos)
            rows = [{k: row[k] for k in GAIA_COLUMNS if k in columns} for row in table[:MAX_GAIA_ROWS]]
            truncated = overflow or len(table) > MAX_GAIA_ROWS
        else:
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            rows = []
            truncated = False
            for row in reader:
                if len(rows) >= MAX_GAIA_ROWS:
                    truncated = True
                    break
                rows.append({k: row.get(k) for k in GAIA_COLUMNS})
            columns = set(reader.fieldnames or [])
    except (ValueError, TypeError, StopIteration, UnicodeError, AttributeError, ExpatError) as exc:
        raise CatalogError("Gaia returned an uninterpretable table.") from exc
    if not {"source_id", "ra", "dec", "pmra", "pmdec", "ref_epoch"} <= columns:
        raise CatalogError("Gaia response lacks required astrometric columns.")
    return rows, truncated


def _gaia_prediction(row, exposure_year, observer_barycentric_au):
    ra, dec = _float(row.get("ra")), _float(row.get("dec"))
    if ra is None or dec is None or not -90 <= dec <= 90:
        return None
    ref_epoch = _float(row.get("ref_epoch"))
    pmra, pmdec = _float(row.get("pmra")), _float(row.get("pmdec"))
    parallax = _float(row.get("parallax"))
    radial_velocity = _float(row.get("radial_velocity"))
    have_motion = ref_epoch is not None and pmra is not None and pmdec is not None
    have_parallax = parallax is not None and parallax > 0
    direction = _unit(ra, dec)
    a, d = np.radians([ra, dec])
    east = np.array([-np.sin(a), np.cos(a), 0.0])
    north = np.array([-np.sin(d) * np.cos(a), -np.sin(d) * np.sin(a), np.cos(d)])
    # pmra includes cos(dec). Work in Cartesian directions to handle RA wrap and the poles.
    if have_motion:
        years = exposure_year - ref_epoch
        direction += years * MAS_TO_RAD * (pmra * east + pmdec * north)
        if have_parallax and radial_velocity is not None:
            direction += (years * radial_velocity * 31_557_600 / AU_KM * parallax * MAS_TO_RAD) * _unit(ra, dec)
    if have_parallax:
        direction -= parallax * MAS_TO_RAD * observer_barycentric_au
    return (*_radec(direction), have_motion, have_parallax)


def search_gaia(epochs, tolerance_arcsec):
    """Check Gaia DR3 against each requested epoch, retaining nearby alternatives."""
    centre = epochs[len(epochs) // 2]
    times = Time([e.mjd for e in epochs], format="mjd", scale="utc")
    years = times.tcb.jyear
    track_extent = max(_separation_arcsec(e.ra, e.dec, centre) for e in epochs)
    needed_radius = float((track_extent + 12 * max(abs(years - 2016.0)) + tolerance_arcsec) / 3600)
    radius = min(0.25, max(0.005, needed_radius))
    query = (
        f"SELECT {','.join(GAIA_COLUMNS)} FROM gaiadr3.gaia_source "
        f"WHERE pos @ scircle(spoint(radians({centre.ra:.9f}),radians({centre.dec:.9f})),radians({radius:.9f})) "
        f"ORDER BY source_id LIMIT {MAX_GAIA_ROWS + 1}"
    )
    attempts = []
    for provider, endpoint, params in (
        ("Gaia@AIP TAP", GAIA_AIP, dict(REQUEST="doQuery", LANG="PostgreSQL", FORMAT="votable", QUERY=query)),
        ("MAST Gaia DR3 cone search", GAIA_MAST, dict(RA=f"{centre.ra:.9f}", DEC=f"{centre.dec:.9f}",
                                                       SR=f"{radius:.9f}", format="csv")),
    ):
        url = _url(endpoint, params)
        try:
            table, truncated = _gaia_rows(_fetch(endpoint, params, timeout=15))
        except CatalogError as exc:
            attempts.append(dict(provider=provider, url=url, status="unavailable", error=str(exc)))
            continue
        attempts.append(dict(provider=provider, url=url, status="ok", rowsRead=len(table)))
        break
    else:
        return dict(status="unavailable", source="Gaia DR3", attempts=attempts, matches=[],
                    searchRadiusArcsec=radius * 3600)

    earth = get_body_barycentric("earth", times, ephemeris="builtin").xyz.to_value(u.au).T
    positions = [pos if epoch.observer_position_km is None else pos + np.array(epoch.observer_position_km) / AU_KM
                 for pos, epoch in zip(earth, epochs)]
    matches = []
    for row in table:
        sid = str(row.get("source_id", "")).strip()
        if not sid.isdigit():
            continue
        samples = []
        for epoch, year, position in zip(epochs, years, positions):
            predicted = _gaia_prediction(row, year, position)
            if predicted is None:
                break
            ra, dec, has_motion, has_parallax = predicted
            distance = _separation_arcsec(ra, dec, epoch)
            samples.append(dict(mjd=epoch.mjd, ra=ra, dec=dec, separationArcsec=distance,
                                positionKind=epoch.kind,
                                observer="SPHEREx FITS midpoint" if epoch.observer_position_km else "Earth geocenter"))
        if len(samples) != len(epochs):
            continue
        closest = min(sample["separationArcsec"] for sample in samples)
        if closest > tolerance_arcsec:
            continue
        rms = math.sqrt(sum(sample["separationArcsec"]**2 for sample in samples) / len(samples))
        matches.append(dict(sourceId=sid, name=f"Gaia DR3 {sid}", closestArcsec=closest, rmsArcsec=rms,
                            withinTolerance=sum(sample["separationArcsec"] <= tolerance_arcsec for sample in samples),
                            properMotionApplied=has_motion, parallaxApplied=has_parallax, samples=samples,
                            refEpoch=_float(row.get("ref_epoch")), pmRaMasYr=_float(row.get("pmra")),
                            pmDecMasYr=_float(row.get("pmdec")), parallaxMas=_float(row.get("parallax")),
                            gMag=_float(row.get("phot_g_mean_mag")), ruwe=_float(row.get("ruwe")),
                            sourceUrl="https://gea.esac.esa.int/archive/"))
    matches.sort(key=lambda r: (-r["withinTolerance"], r["rmsArcsec"], r["closestArcsec"]))
    return dict(status="partial" if truncated or needed_radius > radius + 1e-9 else "ok", source="Gaia DR3",
                attempts=attempts, searchRadiusArcsec=radius * 3600, radiusCapped=needed_radius > radius + 1e-9,
                rowsRead=len(table), rowsTruncated=truncated, matchCount=len(matches), matches=matches[:8],
                method="Gaia DR3 J2016.0 positions propagated with pmRA*, pmDec, positive parallax and available radial velocity.")


def _decode_json(raw, source):
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise CatalogError(f"{source} returned an uninterpretable response.") from exc
    if not isinstance(body, dict) or body.get("error"):
        raise CatalogError(f"{source} reported a query failure.")
    return body


def _sexagesimal(value, *, hours=False):
    source = str(value).strip()
    match = re.fullmatch(r"([+-]?)(\d{1,3})[: ]+(\d{1,2})[: ']+(\d{1,2}(?:\.\d+)?)[\"]?", source)
    if not match:
        raise ValueError("Invalid sexagesimal angle.")
    sign, integer, minutes, seconds = match.groups()
    angle = int(integer) + int(minutes) / 60 + float(seconds) / 3600
    if int(minutes) >= 60 or float(seconds) >= 60 or angle > (24 if hours else 90):
        raise ValueError("Invalid sexagesimal angle.")
    return angle * (15 if hours else 1) * (-1 if sign == "-" else 1)


def _sb_rows(raw):
    body = _decode_json(raw, "JPL SB Identification")
    signature = str((body.get("signature") or {}).get("source", ""))
    count = body.get("n_first_pass")
    if "Small-Body Identification" not in signature or not str(count).isdigit():
        raise CatalogError("JPL SB Identification response lacks a result count.")
    count = int(count)
    if count == 0:
        return [], count
    names = body.get("fields_first")
    data = body.get("data_first_pass")
    if not isinstance(names, list) or not isinstance(data, list) or len(data) != count:
        raise CatalogError("JPL SB Identification returned an incomplete table.")
    fields = [str(s).lower() for s in names]
    try:
        indices = [next(i for i, field in enumerate(fields) if field.startswith(prefix))
                   for prefix in ("object name", "astrometric ra", "astrometric dec", "visual magnitude")]
    except StopIteration as exc:
        raise CatalogError("JPL SB Identification response changed its position fields.") from exc
    result = []
    for row in data:
        try:
            name, ra, dec, vmag = (row[i] for i in indices)
            ra = _sexagesimal(ra, hours=True) % 360
            dec = _sexagesimal(dec)
            if not (math.isfinite(ra) and -90 <= dec <= 90):
                continue
            result.append(dict(name=str(name)[:120], ra=ra, dec=dec, vMag=_float(vmag)))
        except (ValueError, TypeError, IndexError):
            continue
    if not result:
        raise CatalogError("JPL SB Identification returned rows without usable coordinates.")
    return result, count


def _sb_params(epoch, half_width_deg):
    params = {
        "obs-time": f"{epoch.mjd + 2400000.5:.10f}",
        "fov-ra-center": Angle(epoch.ra, unit=u.deg).to_string(unit=u.hourangle, sep="-", precision=4, pad=True),
        "fov-dec-center": Angle(epoch.dec, unit=u.deg).to_string(sep="-", precision=4, pad=True),
        "fov-ra-hwidth": f"{min(3.0, half_width_deg / math.cos(math.radians(epoch.dec))):.6f}",
        "fov-dec-hwidth": f"{half_width_deg:.6f}",
        "mag-required": "false", "two-pass": "false",
    }
    if epoch.dec < 0:
        params["fov-dec-center"] = params["fov-dec-center"].replace("-", "M", 1)
    if epoch.observer_position_km is None:
        return {**params, "lat": 0, "lon": 0, "alt": 0}, "Earth surface proxy (latitude 0°, longitude 0°)"
    vector = epoch.observer_position_km + (epoch.observer_velocity_km_s or ())
    return {**params, "xobs": ",".join(f"{component:.8f}" for component in vector)}, "SPHEREx FITS midpoint"


def _horizons_command(name):
    asteroid = re.match(r"^(\d+)\s", name)
    if asteroid:
        return asteroid.group(1) + ";"
    comet = re.match(r"^(?:(?:[CPDXAI]/\d{4}\s+[A-Z][A-Z0-9-]*)|(?:\d+[PDI](?:-[A-Z])?))(?=\s|/|$)", name)
    if comet:
        return "DES=" + comet.group(0) + ";CAP;NOFRAG"
    designation = re.search(r"\((\d{4}\s+[A-Z]{1,2}\d{0,5})\)", name)
    return ("DES=" + designation.group(1) + ";") if designation else None


def _horizons_ephemeris(raw):
    body = _decode_json(raw, "JPL Horizons")
    result = body.get("result", "")
    if not isinstance(result, str) or "$$SOE" not in result or "$$EOE" not in result:
        raise CatalogError("JPL Horizons could not resolve an unambiguous ephemeris.")
    label = next((line.split(":", 1)[1].strip().split("{")[0].strip()
                  for line in result.splitlines() if "Target body name:" in line), "JPL Horizons target")
    rows = []
    for row in csv.reader(io.StringIO(result.split("$$SOE", 1)[1].split("$$EOE", 1)[0])):
        if not row:
            continue
        if len(row) < 6:
            raise CatalogError("JPL Horizons observer-table columns changed.")
        jd, ra, dec, distance = map(_float, (row[0], row[3], row[4], row[5]))
        if jd is None or ra is None or dec is None or distance is None or distance <= 0 or not -90 <= dec <= 90:
            raise CatalogError("JPL Horizons returned invalid astrometric coordinates or range.")
        rows.append(dict(mjd=jd - 2400000.5, ra=ra % 360, dec=dec, distanceAu=distance))
    if not rows:
        raise CatalogError("JPL Horizons ephemeris had no usable samples.")
    return label, rows


def _refine_horizons(name, epochs, tolerance_arcsec):
    command = _horizons_command(name)
    if command is None:
        return dict(status="unsupported-designation", name=name, samples=[])
    params = {"format": "json", "COMMAND": f"'{command}'", "CENTER": "'500@399'", "EPHEM_TYPE": "'OBSERVER'",
              "TLIST_TYPE": "'JD'", "TIME_TYPE": "'UT'", "TLIST": " ".join(f"'{e.mjd + 2400000.5:.10f}'" for e in epochs),
              "QUANTITIES": "'1,20'", "CAL_FORMAT": "'JD'", "ANG_FORMAT": "'DEG'", "CSV_FORMAT": "'YES'",
              "RANGE_UNITS": "'AU'", "EXTRA_PREC": "'YES'", "REF_SYSTEM": "'ICRF'"}
    url = _url(HORIZONS, params)
    try:
        label, rows = _horizons_ephemeris(_fetch(HORIZONS, params, timeout=12))
        samples = []
        for epoch in epochs:
            row = min(rows, key=lambda value: abs(value["mjd"] - epoch.mjd))
            if abs(row["mjd"] - epoch.mjd) * 86400 > 0.5:
                raise CatalogError("JPL Horizons timestamps did not match the requested observation epochs.")
            ra, dec = row["ra"], row["dec"]
            if epoch.observer_position_km is not None:
                vector = _unit(ra, dec) * row["distanceAu"] - np.array(epoch.observer_position_km) / AU_KM
                ra, dec = _radec(vector)
            distance = _separation_arcsec(ra, dec, epoch)
            offset_bound = None
            if epoch.observer_position_km is not None:
                offset_bound = 0.0
            elif epoch.observer_radius_km is not None:
                ratio = epoch.observer_radius_km / (row["distanceAu"] * AU_KM)
                if ratio < 1:
                    offset_bound = math.degrees(math.asin(ratio)) * 3600
            samples.append(dict(mjd=epoch.mjd, ra=ra, dec=dec, geocentricRangeAu=row["distanceAu"],
                                separationArcsec=distance, positionKind=epoch.kind,
                                observer="Parallax-adjusted to SPHEREx" if epoch.observer_position_km else "Earth geocenter",
                                withinTolerance=distance <= tolerance_arcsec, observerOffsetUpperBoundArcsec=offset_bound,
                                observerRobust=offset_bound is not None and distance + offset_bound <= tolerance_arcsec))
        rms = math.sqrt(sum(s["separationArcsec"]**2 for s in samples) / len(samples))
        return dict(status="ok", name=name, horizonsName=label, url=url, samples=samples, rmsArcsec=rms,
                    withinTolerance=sum(s["withinTolerance"] for s in samples))
    except CatalogError as exc:
        return dict(status="unavailable", name=name, url=url, error=str(exc), samples=[])


def search_jpl(epochs, tolerance_arcsec):
    """Use at most two SBIdent epochs and two Horizons refinements, serially."""
    selected = [epochs[0], epochs[-1]] if len(epochs) >= MAX_JPL_EPOCHS else list(epochs)
    epoch_checks = []
    shortlist = {}
    half_width_deg = max(0.12, 5 * tolerance_arcsec / 3600)
    for epoch in selected:
        if abs(epoch.dec) > 89.5:
            epoch_checks.append(dict(mjd=epoch.mjd, status="unsupported-polar-geometry", matches=[]))
            continue
        params, observer = _sb_params(epoch, half_width_deg)
        detail = dict(mjd=epoch.mjd, url=_url(SB_IDENT, params), observer=observer,
                      raHalfWidthDeg=float(params["fov-ra-hwidth"]), decHalfWidthDeg=half_width_deg)
        try:
            objects, count = _sb_rows(_fetch(SB_IDENT, params, timeout=30))
        except CatalogError as exc:
            epoch_checks.append(dict(detail, status="unavailable", error=str(exc), matches=[]))
            continue
        for obj in objects:
            obj["separationArcsec"] = _separation_arcsec(obj["ra"], obj["dec"], epoch)
        nearby = sorted((o for o in objects if o["separationArcsec"] <= half_width_deg * 3600),
                        key=lambda obj: obj["separationArcsec"])
        epoch_checks.append(dict(detail, status="ok", rowsRead=count, nearbyCount=len(nearby), matches=nearby[:8]))
        for obj in nearby[:8]:
            shortlist.setdefault(obj["name"], []).append(obj["separationArcsec"])
    ordered = sorted(shortlist, key=lambda name: (-len(shortlist[name]), min(shortlist[name])))
    eligible = [name for name in ordered if _horizons_command(name) is not None]
    refined = [_refine_horizons(name, selected, tolerance_arcsec) for name in eligible[:MAX_HORIZONS_TARGETS]]
    usable = sum(row["status"] == "ok" for row in epoch_checks)
    failed_refinement = any(item["status"] != "ok" for item in refined)
    partial = usable < len(selected) or len(ordered) > len(refined) or failed_refinement
    status = "unavailable" if not usable else "partial" if partial else "ok"
    return dict(status=status, source="NASA/JPL SB Identification and Horizons", epochChecks=epoch_checks,
                shortlistedCount=len(ordered), horizons=refined, epochsChecked=usable, requestedEpochs=len(selected),
                method="SB Identification first-pass shortlist followed by Horizons astrometric positions at exact UTC epochs; midpoint spacecraft parallax adjustment when available.")


def _interpret(epochs, evidence, gaia, jpl):
    measured = [e for e in epochs if e.kind == "measured-centroid" and e.uncertainty_arcsec is not None]
    independent = len({e.observation_id for e in measured if e.observation_id})
    measured_track = len(measured) == len(epochs) and independent >= 2 and epochs[-1].mjd - epochs[0].mjd >= 1
    stellar = [match for match in gaia.get("matches", []) if match["withinTolerance"] == len(epochs)
               and match.get("properMotionApplied")]
    solar = [match for match in jpl.get("horizons", []) if match.get("status") == "ok"
             and len(match["samples"]) >= 2 and match["withinTolerance"] == len(match["samples"])
             and all(sample.get("observerRobust") for sample in match["samples"])]
    same_track = len(stellar) + len(solar)
    limited = any(part.get("status") != "ok" for part in (gaia, jpl))
    quality = evidence.get("epochMeasurements") or []
    invalid = sum(isinstance(q, dict) and (q.get("valid") is False or q.get("usable") is False) for q in quality)
    gain = _float(evidence.get("snrGainOverStatic"))
    reasons = []
    if measured_track and same_track == 1 and not limited:
        classification = "catalog-consistent"
        match = (stellar + solar)[0]
        reasons.append(f"A unique catalog association, {match['name']}, is positionally consistent at the measured epochs.")
    elif same_track > 1:
        classification = "insufficient-evidence"
        reasons.append("Several catalog associations fit the supplied track. Further astrometry is needed to distinguish them.")
    elif same_track == 0 and invalid >= 2 and invalid * 2 >= len(quality) and gain is not None and gain <= 0:
        classification = "artifact-suspect"
        reasons.append("Multiple epoch samples are unusable and the motion trial did not improve nominal S/N. Inspect the image flags and backgrounds for an instrumental explanation.")
    elif not measured_track:
        classification = "insufficient-evidence"
        reasons.append("This record lacks independent multi-epoch centroids with positional uncertainties. Catalog proximity cannot independently validate a trial track.")
    elif limited:
        classification = "insufficient-evidence"
        reasons.append("At least one catalog check was incomplete or unavailable.")
    else:
        classification = "unidentified"
        reasons.append("The catalog checks did not find a unique association within the stated limits. This does not establish a new object.")

    top = _float(evidence.get("nominalSnr"))
    if gain is None:
        motion = "The static baseline was unavailable at the same position."
    elif gain <= 0:
        motion = "The trial does not improve nominal signal-to-noise over a static stack."
    else:
        motion = f"The trial improves nominal signal-to-noise by {gain:.2f} over the static stack. This is not a trials-corrected significance."
    if same_track == 1 and not measured_track:
        reasons.append(f"{(stellar + solar)[0]['name']} is consistent with the trial positions and remains a provisional association.")
    if invalid:
        reasons.append(f"{invalid} epoch sample(s) are unusable or flagged. Inspect the individual images and flags.")
    hypotheses = [
        dict(name="Gaia catalog source or blend", evidence=f"{len(stellar)} complete positional association(s) within the tolerance, including measured or model positions."),
        dict(name="Known minor planet or comet", evidence=f"{len(solar)} Horizons track(s) close at both bounded JPL epochs after spacecraft parallax correction or a conservative angular offset bound."),
        dict(name="Stationary source or instrumental residual", evidence=motion),
        dict(name="Uncatalogued moving source", evidence="Requires repeatable centroids on independent observations, negative controls, artifact review, and broader catalog checks."),
    ]
    return classification, reasons, hypotheses, dict(nominalSnr=top, snrGainOverStatic=gain,
                                                    independentMeasuredEpochs=independent, unusableSamples=invalid)


def investigate(candidate: dict, *, tolerance_arcsec: float = 10.0):
    """Return auditable, JSON-ready association evidence from live authorities.

    Sky positions are ICRS degrees and epochs are UTC MJD, as in the SPHEREx FITS.
    The body accepts a trusted survey candidate, including its epoch measurements.
    A bare RA/Dec/referenceMjd is a positional cross-check, never identification.
    """
    radius = _bounded(tolerance_arcsec, "Association tolerance (arcsec)", 2, 30)
    evidence = candidate.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise ValueError("Candidate evidence must be an object.")
    points = evidence.get("epochMeasurements") or [{"ra": candidate.get("ra"), "dec": candidate.get("dec"),
                                                       "mjd": candidate.get("referenceMjd"), "positionKind": "reference-position"}]
    if not isinstance(points, list) or not 1 <= len(points) <= 8 or any(not isinstance(p, dict) for p in points):
        raise ValueError("Supply between one and eight candidate epochs.")
    valid_points = [p for p in points if p.get("valid") is not False and p.get("usable") is not False]
    if not valid_points:
        raise ValueError("Candidate has no usable positions for a catalog cross-check.")
    individual = sorted((_parse_epoch(point) for point in valid_points), key=lambda epoch: epoch.mjd)
    epochs = list({epoch.mjd: epoch for epoch in individual}.values())
    with ThreadPoolExecutor(max_workers=2) as pool:
        gaia_future = pool.submit(search_gaia, epochs, radius)
        jpl_future = pool.submit(search_jpl, epochs, radius)
        gaia, jpl = gaia_future.result(), jpl_future.result()
    classification, reasons, hypotheses, ranking = _interpret(epochs, evidence, gaia, jpl)
    return dict(schemaVersion="slowtrace-catalogs-v1", checkedAt=datetime.now(timezone.utc).isoformat(),
                classification=classification, reasons=reasons, hypotheses=hypotheses, evidence=ranking,
                scope=dict(frame="ICRS", epochScale="UTC MJD", toleranceArcsec=radius, epochs=[e.json() for e in epochs]),
                gaia=gaia, jpl=jpl, warnings=[
                    "Gaia DR3 is an optical catalog with finite coverage and selection limits. Apparent agreement may be a blend or chance superposition.",
                    "Gaia uses approximate linear space motion and positive catalog parallax with Earth's builtin barycentric ephemeris; covariance and photometric systematics are omitted.",
                    "SB Identification is a first-pass shortlist at only the first and last usable epochs. Objects with uncertain orbits may be omitted or appear spuriously within the search.",
                    "Horizons samples use the Earth geocenter. If spacecraft axes are verified, apply its parallax adjustment. If only a geocentric radius is verified, report an angular offset bound. Differential light-time and observer uncertainties are not fitted.",
                    "The association threshold is an angular tolerance, not a probability. Candidate positions from one DeepTrace grid trial are model samples rather than independent measurements.",
                ])
