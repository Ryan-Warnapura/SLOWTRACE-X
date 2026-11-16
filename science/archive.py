"""Real SPHEREx discovery and calibrated cutouts. No generated observational data.

Wavelength-table interpolation and flag policy adapted from SkyShift (Apache-2.0),
see licenses/skyshift-APACHE-2.0.txt. Coordinate reprojection, squared-weight
variance propagation, upstream validation and API representation are SLOWTRACE X.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlencode

import numpy as np
import requests
from astropy.io import fits
from astropy.wcs import NoConvergence, WCS

from science.coverage import matching_records

SIA = "https://irsa.ipac.caltech.edu/SIA/"
TAP = "https://irsa.ipac.caltech.edu/TAP/sync"
COLLECTIONS = ("spherex_dr1", "spherex_qr3")
OBSERVATION_NAME = re.compile(r"/level2_([\w]+_[1-4])D([1-6])_spx_[^/]+\.fits$")
# SPHEREx Explanatory Supplement §3.4.3 mosaic exclusions, plus saturated OVERFLOW.
# SOURCE, FULLSAMPLE and OUTLIER remain reported as informational flags.
MASK_BITS = sum(1 << bit for bit in (0, 1, 2, 6, 7, 9, 10, 11, 14, 15, 17, 20, 22, 23, 24, 25, 26, 27, 28, 29))
SAT_BITS = 0x00008002
MISSING = 1 << 9
BIT_NAMES = {0: "TRANSIENT", 1: "OVERFLOW", 2: "SUR_ERROR", 6: "NONFUNC",
             7: "DICHROIC", 9: "MISSING_DATA", 10: "HOT", 11: "COLD",
             12: "FULLSAMPLE", 14: "PHANMISS", 15: "NONLINEAR", 17: "PERSIST",
             19: "OUTLIER", 20: "CROSSTALK", 21: "SOURCE", 22: "GHOST",
             23: "GHOST_FPA", 24: "GHOST_EXT", 25: "STREAK", 26: "BLOOM",
             27: "SNOWBALL", 28: "HALO", 29: "SATELLITE_HALO"}


class ArchiveError(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def date_mjd(mjd):
    return datetime.fromtimestamp((float(mjd) - 40587) * 86400, timezone.utc).isoformat()


def checked_position(ra, dec, fov):
    if not all(math.isfinite(x) for x in (ra, dec, fov)):
        raise ValueError("Coordinates and field of view must be finite.")
    if not 0 <= ra < 360 or not -90 <= dec <= 90 or not 1 <= fov <= 30:
        raise ValueError("Use RA 0–360°, declination −90–90°, and a field 1–30 arcminutes.")


def validate_url(url, cloud=False):
    p = urlsplit(url)
    host = "nasa-irsa-spherex.s3.us-east-1.amazonaws.com" if cloud else "irsa.ipac.caltech.edu"
    prefix = "/" if cloud else "/ibe/data/spherex/"
    path = p.path[len(prefix):]
    if (p.scheme != "https" or p.hostname != host or p.port not in (None, 443)
            or p.username or p.password or p.query or p.fragment
            or not p.path.startswith(prefix) or not path.startswith(("dr1/level2/", "qr3/level2/"))
            or not p.path.endswith(".fits") or ".." in p.path or "%" in p.path):
        raise ValueError("Only official IRSA DR1/QR3 Level 2 FITS URLs are accepted.")
    return url


def cloud_url(url):
    validate_url(url)
    return "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/" + url.split("/spherex/", 1)[1]


def _normalize(rows):
    seen = {}
    for r in rows:
        try:
            if r.get("dataproduct_type", "image") != "image" or r.get("dataproduct_subtype", "science") != "science":
                continue
            collection = r["obs_collection"].removesuffix("_deep")
            if collection not in COLLECTIONS:
                continue
            det = int(r["energy_bandpassname"].split("-D")[-1])
            url = validate_url(r["access_url"])
            start, end = float(r["t_min"]), float(r["t_max"])
            mjd = float(r.get("t_center", (start + end) / 2))
            if not all(math.isfinite(x) for x in (start, mjd, end)) or not start <= mjd <= end or not 1 <= det <= 6:
                continue
            match = OBSERVATION_NAME.search(url)
            key = f"{match[1] if match else r['obs_id']}D{det}"
            item = dict(id=key, collection=collection, detector=det, mjd=mjd,
                        startMjd=start, endMjd=end, date=date_mjd(mjd),
                        url=url, cloudUrl=cloud_url(url), footprint=r.get("s_region"),
                        metadataSource=r.get("metadataSource"), metadataRetrievedAt=r.get("metadataRetrievedAt"))
            if r.get("fitsHeaderSha256"):
                item["fitsHeaderSha256"] = r["fitsHeaderSha256"]
            preferred = {"recorded-sia": 0, "nasa-fits-header-index": 1, "irsa-tap": 2, "irsa-sia": 2}
            old = seen.get(key)
            rank = (collection == "spherex_dr1", preferred.get(item["metadataSource"], 0))
            old_rank = (old["collection"] == "spherex_dr1", preferred.get(old["metadataSource"], 0)) if old else (-1, -1)
            if rank > old_rank:
                seen[key] = item
        except (ValueError, TypeError, KeyError):
            continue
    return sorted(seen.values(), key=lambda x: (x["mjd"], x["detector"]))


def _csv_response(response, columns):
    response.raise_for_status()
    table = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff\r\n")))
    if not set(columns).issubset(table.fieldnames or ()):
        raise ArchiveError("IRSA returned an unexpected search response.")
    return list(table)


@lru_cache(maxsize=64)
def _query_collection(ra, dec, collection, window):
    params = [("COLLECTION", collection), ("COLLECTION", collection + "_deep"),
              ("POS", f"CIRCLE {ra:.8f} {dec:.8f} 0.000277778"), ("RESPONSEFORMAT", "CSV"), ("MAXREC", "12001")]
    response = requests.get(SIA, params=params, timeout=(5, 30), headers={"User-Agent": "SLOWTRACE-X/1.1"})
    rows = _csv_response(response, ("obs_collection", "obs_id", "energy_bandpassname", "access_url", "t_min", "t_max"))
    captured = now()
    return [dict(row, metadataSource="irsa-sia", metadataRetrievedAt=captured) for row in rows], response.url, captured, len(rows) >= 12001


@lru_cache(maxsize=64)
def _query_tap(ra, dec, detector, releases, window):
    paths = " OR ".join(f"a.uri LIKE '%spherex/{c.removeprefix('spherex_')}/level2/%'" for c in releases)
    sql = ("SELECT TOP 4001 a.uri, p.time_bounds_lower, p.time_bounds_upper "
           "FROM spherex.artifact a JOIN spherex.plane p ON a.planeid = p.planeid "
           f"WHERE 1 = CONTAINS(POINT('ICRS', {ra:.8f}, {dec:.8f}), p.poly) "
           f"AND p.energy_bandpassname = 'SPHEREx-D{detector}' AND ({paths}) ORDER BY p.time_bounds_lower")
    response = requests.get(TAP, params={"REQUEST":"doQuery", "LANG":"ADQL", "FORMAT":"CSV", "QUERY":sql},
                            timeout=(5, 24), headers={"User-Agent":"SLOWTRACE-X/1.1"})
    rows = _csv_response(response, ("uri", "time_bounds_lower", "time_bounds_upper"))
    retrieved_at = now()
    normalized = []
    for row in rows:
        uri = row["uri"]
        url = uri if uri.startswith("https://") else "https://irsa.ipac.caltech.edu/" + uri.lstrip("/")
        match = OBSERVATION_NAME.search(url)
        if not match or int(match[2]) != detector or "/spherex/" not in url:
            continue
        release = url.split("/spherex/", 1)[1].split("/", 1)[0]
        normalized.append(dict(access_url=url, obs_id=match[1], obs_collection=f"spherex_{release}",
                               energy_bandpassname=f"SPHEREx-D{detector}", t_min=row["time_bounds_lower"],
                               t_max=row["time_bounds_upper"], metadataSource="irsa-tap", metadataRetrievedAt=retrieved_at))
    return normalized, response.url, retrieved_at, len(rows) >= 4001


@lru_cache(maxsize=1)
def _reference_catalog():
    return json.loads((Path(__file__).parent / "data/reference-photolists.json").read_text())


def _recorded_rows(ra, dec):
    # Narrow match only: never use another field's observations as arbitrary search results.
    for target in _reference_catalog().values():
        c = target["center"]
        dra = ((ra - c["ra"] + 180) % 360 - 180) * math.cos(math.radians(dec))
        if math.hypot(dra, dec - c["dec"]) * 3600 < 1:
            return target
    return None


def search(ra, dec, fov=5, detector=1, limit=12, *, indexed_only=False):
    checked_position(ra, dec, fov)
    if detector not in range(1, 7) or not 2 <= limit <= 24:
        raise ValueError("Choose detector 1–6 and 2–24 observations.")
    rows, query_urls, notes, live_releases, indexed_releases, recorded_releases, checked_times = [], [], [], [], [], [], []
    missing = list(COLLECTIONS)
    window = int(time.time() // 600)
    upstream_capped = False
    if not indexed_only:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {c: pool.submit(_query_collection, ra, dec, c, window) for c in COLLECTIONS}
            for c, future in futures.items():
                try:
                    part, url, checked, capped = future.result()
                    rows.extend(part)
                    query_urls.append(url)
                    checked_times.append(checked)
                    live_releases.append(c)
                    missing.remove(c)
                    upstream_capped |= capped
                except (requests.RequestException, ArchiveError) as error:
                    notes.append(f"{c}: IRSA SIA unavailable ({type(error).__name__}).")
        if missing:
            try:
                part, url, checked, capped = _query_tap(ra, dec, detector, tuple(missing), window)
                rows.extend(part)
                query_urls.append(url)
                checked_times.append(checked)
                live_releases.extend(missing)
                missing.clear()
                upstream_capped |= capped
                notes.append("IRSA TAP supplied metadata for releases that could not be queried through SIA.")
            except (requests.RequestException, ArchiveError) as error:
                notes.append(f"IRSA TAP fallback unavailable ({type(error).__name__}).")
    index_date = None
    if missing:
        records, index_date = matching_records(ra, dec, detector, {c.removeprefix("spherex_") for c in missing})
        for r in records:
            release = r["url"].split("/spherex/", 1)[1].split("/", 1)[0]
            collection = f"spherex_{release}"
            rows.append(dict(access_url=r["url"], obs_id=r["id"], obs_collection=collection,
                             energy_bandpassname=f"SPHEREx-D{r['detector']}", t_min=r["startMjd"], t_max=r["endMjd"], t_center=r["mjd"],
                             metadataSource="nasa-fits-header-index", metadataRetrievedAt=r["capturedAt"],
                             fitsHeaderSha256=r["fitsHeaderSha256"]))
            if collection not in indexed_releases:
                indexed_releases.append(collection)
        if records:
            checked_times.append(index_date)
            notes.append("Some observations were located using recorded NASA FITS headers and tested against their detector footprints. This sample does not cover the entire archive. Pixels are retrieved separately.")
        recorded = _recorded_rows(ra, dec)
        if recorded:
            for row in recorded["observations"]:
                collection = row["obs_collection"]
                if collection in missing and row["energy_bandpassname"].endswith(f"-D{detector}"):
                    rows.append(dict(row, metadataSource="recorded-sia", metadataRetrievedAt=recorded["archiveChecked"]))
                    if collection not in recorded_releases:
                        recorded_releases.append(collection)
            if recorded_releases:
                checked_times.append(recorded["archiveChecked"])
                notes.append(f"Search includes a recorded IRSA observation list from SkyShift, checked {recorded['archiveChecked']}. Pixel data are retrieved separately.")
    if upstream_capped:
        notes.append("The live archive reached its response row limit. The reported total is a lower bound.")
    status = "live" if not missing else "partial-live" if live_releases else "recorded-metadata"
    observations = [x for x in _normalize(rows) if x["detector"] == detector]
    if not live_releases and not observations and not indexed_only:
        raise ArchiveError("NASA IRSA search is temporarily unavailable and the recorded index has no verified match at this position and detector. This is not evidence of absent coverage. Retry later or choose one of the five target fields.")
    total = len(observations)
    if total > limit:
        # Preserve temporal extent; the response explicitly discloses bounded sampling.
        indices = np.linspace(0, total - 1, limit).round().astype(int)
        observations = [observations[i] for i in indices]
        notes.append(f"Showing {limit} time-spaced observations out of {total}; this is a bounded sample, not the entire archive.")
    return dict(query=dict(ra=ra, dec=dec, fov=fov, detector=detector), observations=observations,
                totalAvailable=total, truncated=total > limit or upstream_capped, queriedAt=now(),
                archiveChecked=max(checked_times, default=None), source="NASA/IPAC IRSA", status=status, warnings=notes,
                queryUrls=query_urls, searchCoverage=dict(complete=not missing and not upstream_capped,
                    liveCollections=live_releases, indexedCollections=indexed_releases,
                    recordedCollections=recorded_releases, indexGeneratedAt=index_date))


def target_grid(ra, dec, fov, pixels):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(pixels + 1) / 2] * 2
    w.wcs.cdelt = [-fov / 60 / pixels] * 2  # raster row zero is north, column zero east
    y, x = np.indices((pixels, pixels), dtype=float)
    return w, w.all_pix2world(x, y, 0)


def wavelength_map(header, table, x, y, component=1):
    """FITS Paper III WCS-WAVE bilinear table; adapted from SkyShift WaveTable."""
    cx, cy = np.asarray(table["X"][0]), np.asarray(table["Y"][0])
    values = np.asarray(table["VALUES"][0], dtype=float)[..., int(header.get(f"PV{component}_3W", component)) - 1]
    px = header.get("CRVAL1W", 1) + header.get("CDELT1W", 1) * (x + 1 - header.get("CRPIX1W", 1))
    py = header.get("CRVAL2W", 1) + header.get("CDELT2W", 1) * (y + 1 - header.get("CRPIX2W", 1))
    px, py = np.clip(px, cx[0], cx[-1]), np.clip(py, cy[0], cy[-1])
    ix = np.clip(np.searchsorted(cx, px, side="right") - 1, 0, len(cx) - 2)
    iy = np.clip(np.searchsorted(cy, py, side="right") - 1, 0, len(cy) - 2)
    fx, fy = (px - cx[ix]) / (cx[ix + 1] - cx[ix]), (py - cy[iy]) / (cy[iy + 1] - cy[iy])
    return values[iy, ix] * (1-fx)*(1-fy) + values[iy, ix+1]*fx*(1-fy) + values[iy+1, ix]*(1-fx)*fy + values[iy+1, ix+1]*fx*fy


def resample(data, variance, flags, x, y):
    """Mask-aware bilinear intensity; sum(w² variance)/sum(w)². No covariance claim."""
    shape = x.shape
    ny, nx = data.shape
    finite = np.isfinite(x) & np.isfinite(y)
    x, y = np.where(finite, x, -1), np.where(finite, y, -1)
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - ix, y - iy
    total, num, varnum = np.zeros(shape), np.zeros(shape), np.zeros(shape)
    mask = np.zeros(shape, dtype=np.int64)
    for dx, dy, weight in ((0, 0, (1-fx)*(1-fy)), (1, 0, fx*(1-fy)), (0, 1, (1-fx)*fy), (1, 1, fx*fy)):
        xx, yy = ix+dx, iy+dy
        inside = finite & (xx >= 0) & (xx < nx) & (yy >= 0) & (yy < ny) & (weight > 1e-12)
        xx, yy = np.clip(xx, 0, nx-1), np.clip(yy, 0, ny-1)
        d, v, f = data[yy, xx], variance[yy, xx], flags[yy, xx]
        valid = inside & np.isfinite(d) & np.isfinite(v) & (v > 0) & ((f & MASK_BITS) == 0)
        w = np.where(valid, weight, 0)
        num += w * np.where(valid, d, 0)
        varnum += w*w * np.where(valid, v, 0)
        total += w
        mask |= np.where(inside, f, 0).astype(np.int64)
    good = total > 0.99  # conservative: no interpolation through rejected/missing neighbors
    mask[~good] |= MISSING
    image = np.full(shape, np.nan)
    var = np.full(shape, np.nan)
    image[good] = num[good] / total[good]
    var[good] = varnum[good] / total[good]**2
    return image, var, mask


def aperture_measurement(data, variance, flags, x, y, native_wcs):
    """Uncorrected fixed-position aperture, native pixels (not the resampled raster)."""
    yy, xx = np.indices(data.shape)
    radius = np.hypot(xx-x, yy-y)
    aperture, annulus = radius <= 2, (radius >= 4) & (radius <= 7)
    good = np.isfinite(data) & np.isfinite(variance) & (variance > 0) & ((flags & MASK_BITS) == 0)
    saturated = bool(np.any(aperture & ((flags & SAT_BITS) != 0)))
    n, nsky = int(np.sum(aperture & good)), int(np.sum(annulus & good))
    expected = int(aperture.sum())
    result = dict(fluxMicroJy=None, errorMicroJy=None, backgroundMJySr=None, saturated=saturated,
                  apertureRadiusNativePixels=2, apertureCorrectionApplied=False, validPixels=n,
                  status="unavailable", method="Native-pixel fixed-coordinate aperture sum minus local annular median; no recentering or PSF/aperture correction.",
                  limitations=["May underestimate total flux or blend neighboring sources.", "No correction for subpixel phase, background gradients, calibration systematics, or motion away from the fixed coordinate."])
    if saturated:
        result["status"] = "saturated"
    elif expected > 0 and n >= expected*0.9 and nsky >= 20:
        bg = float(np.median(data[annulus & good]))
        omega = abs(np.linalg.det(native_wcs.pixel_scale_matrix)) * (np.pi/180)**2
        conversion = omega * 1e12  # MJy/sr -> microJy per native pixel
        bgvar = float(np.median(variance[annulus & good])) * np.pi / (2*nsky)
        flux = float(np.sum(data[aperture & good]-bg))*conversion
        error = float(np.sqrt(np.sum(variance[aperture & good]) + n*n*bgvar))*conversion
        result.update(fluxMicroJy=flux, errorMicroJy=error, backgroundMJySr=bg, status="preliminary-aperture-measurement")
    return result


def _get_cutout(url, ra, dec, fov):
    cutout = url + "?" + urlencode(dict(center=f"{ra:.9f},{dec:.9f}", size=f"{fov / 60 * 1.5:.8f}"))
    with requests.get(cutout, timeout=(6, 25), headers={"User-Agent": "SLOWTRACE-X/1.1"},
                      allow_redirects=False, stream=True) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ArchiveError("The archive did not return a complete FITS cutout.")
        raw = bytearray()
        for chunk in response.iter_content(chunk_size=256*1024):
            raw.extend(chunk)
            if len(raw) > 30_000_000:
                raise ArchiveError("Cutout exceeds the processing budget; choose a smaller field.")
    if not raw.startswith(b"SIMPLE  ="):
        raise ArchiveError("The archive did not return a FITS file.")
    return fits.open(io.BytesIO(raw), memmap=False), cutout, hashlib.sha256(raw).hexdigest()


def _number_or_none(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _observer_state(header, mjd):
    """Keep documented origin and units; RADESYS describes image WCS, not these vectors."""
    if header.get("XYZ_SC_SYSTEM") != "GEOCENTER" or header.get("VXYZ_SC_SYSTEM") != "GEOCENTER":
        return None
    position = [_number_or_none(header.get(f"{axis}_SC")) for axis in "XYZ"]
    velocity = [_number_or_none(header.get(f"V{axis}_SC")) for axis in "XYZ"]
    if None in position + velocity:
        return None
    return dict(positionKm=position, velocityKmS=velocity, origin="GEOCENTER", frame=None,
                epochMjd=mjd, source="SPHEREx Level 2 IMAGE FITS header")


def _read_frame(url, ra, dec, fov, pixels):
    validate_url(url)
    checked_position(ra, dec, fov)
    if not 32 <= pixels <= 128:
        raise ValueError("Image size must be 32–128 pixels.")
    notices = ["Reprojection correlates adjacent pixels. Reported variance propagates independent input-pixel variances; it excludes covariance and systematic calibration errors.",
               "Different exposures can observe different wavelengths within a detector. Brightness changes and residuals may reflect spectral differences or PSF changes, rather than motion."]
    errors = (requests.RequestException, ValueError, KeyError, RuntimeError, OSError, NoConvergence)
    try:
        hdul, cutout_url, raw_hash = _get_cutout(url, ra, dec, fov)
        return _process_frame(hdul, url, ra, dec, fov, pixels, cutout_url, raw_hash, "IRSA cutout", notices.copy())
    except errors as first_error:
        notices.append(f"IRSA cutout could not be used ({type(first_error).__name__}); reading the same NASA exposure from its public S3 mirror.")
    try:
        hdul = fits.open(cloud_url(url), use_fsspec=True,
                         fsspec_kwargs={"block_size": 64*1024, "cache_type": "readahead",
                                        "client_kwargs": {"trust_env": True}}, memmap=False)
        return _process_frame(hdul, url, ra, dec, fov, pixels, None, None, "NASA public S3 range reads", notices)
    except ArchiveError:
        raise
    except errors as error:
        raise ArchiveError(f"Neither source returned a usable NASA exposure ({type(error).__name__}). Try another time or a smaller field.") from error


def _process_frame(hdul, url, ra, dec, fov, pixels, cutout_url, raw_hash, source, notices):
    with hdul:
        header = hdul["IMAGE"].header.copy()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            native = WCS(header).celestial
        _, sky = target_grid(ra, dec, fov, pixels)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            x, y = native.all_world2pix(*sky, 0, quiet=True)
        valid_xy = np.isfinite(x) & np.isfinite(y)
        if not valid_xy.any():
            raise ArchiveError("The requested sky region does not overlap this exposure.")
        nx, ny = int(header["NAXIS1"]), int(header["NAXIS2"])
        x0 = max(0, int(np.floor(x[valid_xy].min()))-2)
        y0 = max(0, int(np.floor(y[valid_xy].min()))-2)
        x1 = min(nx, int(np.ceil(x[valid_xy].max()))+3)
        y1 = min(ny, int(np.ceil(y[valid_xy].max()))+3)
        if x1 <= x0 or y1 <= y0:
            raise ArchiveError("The requested sky region does not overlap this exposure.")
        region = np.s_[y0:y1, x0:x1]
        data = np.asarray(hdul["IMAGE"].section[region], dtype=float)
        var = np.asarray(hdul["VARIANCE"].section[region], dtype=float)
        flags = np.asarray(hdul["FLAGS"].section[region], dtype=np.int64)
        zodi_subtracted = "ZODI" in hdul
        if zodi_subtracted:
            data -= np.asarray(hdul["ZODI"].section[region], dtype=float)
        else:
            notices.append("No ZODI extension: zodiacal-light model was not subtracted.")
        wave_table = hdul["WCS-WAVE"].data if "WCS-WAVE" in hdul else None
        wave = wavelength_map(header, wave_table, x, y) if wave_table is not None else np.full(x.shape, np.nan)
        center_x, center_y = native.all_world2pix(ra, dec, 0, quiet=True)
        center_wave, center_bandwidth = None, None
        if wave_table is not None and -.5 <= center_x < nx-.5 and -.5 <= center_y < ny-.5:
            center_wave = _number_or_none(wavelength_map(header, wave_table, center_x, center_y))
            if "PV2_3W" in header:
                center_bandwidth = _number_or_none(wavelength_map(header, wave_table, center_x, center_y, 2))
        if wave_table is None:
            notices.append("No WCS-WAVE extension; wavelength is unavailable for this exposure.")
        photometry = aperture_measurement(data, var, flags, float(center_x)-x0, float(center_y)-y0, native)
        image, variance, mask = resample(data, var, flags, x-x0, y-y0)
        covered = np.isfinite(image)
        if not covered.any():
            raise ArchiveError("No valid science pixels remain after contamination and coverage masking.")
        wave[~covered] = np.nan
        measured_waves = wave[np.isfinite(wave)]
        mjd = float(header["MJD-AVG"])
        fine = header.get("FINAST")
        if fine is not None and fine != 0:
            notices.append(f"SPHEREx fine astrometry quality flag is {fine}; apparent offsets may reflect astrometric error.")
        provenance = dict(sourceUrl=url, cloudUrl=cloud_url(url), cutoutUrl=cutout_url, retrievedAt=now(),
                          sha256=raw_hash, method=source, pipelineVersion="archive-1.1",
                          pipeline=f"{'IMAGE minus ZODI' if zodi_subtracted else 'IMAGE (no ZODI extension)'}; SPHEREx quality masking; celestial TAN-SIP to common TAN grid; bilinear sampling")
        array_hash = hashlib.sha256(np.nan_to_num(image, nan=-1e30).astype("<f4").tobytes()).hexdigest()
        provenance["processedSha256"] = array_hash
        metadata = dict(id=str(header.get("OBSID", "")), detector=int(header["DETECTOR"]), mjd=mjd, date=date_mjd(mjd),
                        unit=str(header.get("BUNIT", "MJy/sr")).strip(), pixelArcsec=fov*60/pixels,
                        center=dict(ra=ra, dec=dec), wavelengthCenter=center_wave, bandwidthCenter=center_bandwidth,
                        wavelengthMin=float(measured_waves.min()) if len(measured_waves) else None,
                        wavelengthMax=float(measured_waves.max()) if len(measured_waves) else None,
                        badFraction=float(1-covered.mean()), saturatedFraction=float(np.mean((mask & SAT_BITS) != 0)),
                        zodiSubtracted=zodi_subtracted, calibrationVersion=str(hdul[0].header.get("VERSION", header.get("VERSION", "see FITS headers"))),
                        psfAvailable="EPSF" in hdul, psfMatched=False,
                        maskBits=MASK_BITS, flagsPresent=[name for bit,name in BIT_NAMES.items() if np.any(mask & (1<<bit))],
                        flagPixelCounts={name:int(np.count_nonzero(mask & (1<<bit))) for bit,name in BIT_NAMES.items() if np.any(mask & (1<<bit))},
                        centerPixelX=(pixels-1)/2, centerPixelY=(pixels-1)/2,
                        fineAstrometryFlag=fine, l1Quality=header.get("L1DQAFLG"),
                        observerState=_observer_state(header, mjd), startMjd=_number_or_none(header.get("MJD-BEG")),
                        endMjd=_number_or_none(header.get("MJD-END")))
    return dict(width=pixels, height=pixels, data=as_list(image), variance=as_list(variance),
                mask=mask.ravel().tolist(), wavelength=as_list(wave), metadata=metadata,
                provenance=provenance, photometry=photometry, warnings=notices, dataKind="processed-observation")


def as_list(array):
    return [float(x) if np.isfinite(x) else None for x in np.asarray(array).ravel()]


@lru_cache(maxsize=32)
def frame(url, ra, dec, fov=5, pixels=96):
    return _read_frame(url, ra, dec, fov, pixels)
