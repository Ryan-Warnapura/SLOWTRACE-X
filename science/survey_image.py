"""Full-frame SPHEREx Level 2 processing for the offline survey worker.

The measured area is an equal-area HEALPix centre-sampling estimate. A cell
is accepted if its ICRS centre falls on a usable native pixel under the FITS
WCS. This permits overlap-free unions across exposures at the stated NSIDE.
It does not imply that all sky within each cell is unmasked or motion-searched.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import tempfile
from threading import local
from urllib.parse import urlsplit
import warnings

import numpy as np
import requests
from astropy import units as u
from astropy.io import fits
from astropy.io.fits.verify import VerifyError
from astropy.wcs import FITSFixedWarning, WCS
from astropy_healpix import HEALPix

from .archive import (
    BIT_NAMES, MASK_BITS, OBSERVATION_NAME, SAT_BITS, date_mjd, now, validate_url, wavelength_map,
)
from .coverage import WCS_CARD, _unit_points


VERSION = "slowtrace-survey-image/1"
COVERAGE_NSIDE = 1024
MAX_DOWNLOAD_BYTES = 160 * 1024 * 1024
_thread = local()


class ImageRejected(ValueError):
    """The product cannot satisfy deterministic FITS identity or quality checks."""


def _session():
    if not hasattr(_thread, "session"):
        _thread.session = requests.Session()
        _thread.session.headers.update({
            "User-Agent": "SLOWTRACE-X/3 (SPHEREx full-image research survey)",
            "Accept-Encoding": "identity",
        })
    return _thread.session


def _download(url, destination):
    digest = hashlib.sha256()
    size = 0
    with _session().get(url, stream=True, allow_redirects=False, timeout=(8, 45)) as response:
        response.raise_for_status()
        if response.status_code != 200 or "Content-Range" in response.headers:
            raise requests.RequestException("NASA S3 did not return a full FITS response.")
        declared = response.headers.get("Content-Length")
        expected_bytes = int(declared) if declared and declared.isdecimal() else None
        if expected_bytes is not None and expected_bytes > MAX_DOWNLOAD_BYTES:
            raise ImageRejected("The NASA FITS object exceeds the configured full-frame byte limit.")
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            size += len(chunk)
            if size > MAX_DOWNLOAD_BYTES:
                raise ImageRejected("The NASA FITS object exceeds the configured full-frame byte limit.")
            digest.update(chunk)
            destination.write(chunk)
        if not size or (expected_bytes is not None and size != expected_bytes):
            raise requests.RequestException("The NASA S3 FITS transfer was incomplete.")
        etag = response.headers.get("ETag")
    return size, digest.hexdigest(), etag


def _perimeter(wcs, shape):
    ny, nx = shape
    side_count = 16
    x = np.linspace(-0.5, nx - 0.5, side_count, endpoint=False)
    y = np.linspace(-0.5, ny - 0.5, side_count, endpoint=False)
    edge_x = np.concatenate([x, np.full(side_count, nx - 0.5), nx - 1 - x, np.full(side_count, -0.5)])
    edge_y = np.concatenate([np.full(side_count, -0.5), y, np.full(side_count, ny - 0.5), ny - 1 - y])
    ra, dec = wcs.all_pix2world(edge_x, edge_y, 0)
    return np.asarray(ra) % 360, np.asarray(dec)


def _coverage_ranges(wcs, valid, ra, dec, edge_ra, edge_dec):
    """Return half-open, sorted NESTED intervals with usable sky sample centres."""
    grid = HEALPix(nside=COVERAGE_NSIDE, order="nested")
    rays = _unit_points(edge_ra, edge_dec)
    center_ray = _unit_points(ra, dec)
    radius = np.arccos(np.clip((rays @ center_ray).min(), -1, 1)) * u.rad + 0.01 * u.deg
    indices = grid.cone_search_lonlat(ra * u.deg, dec * u.deg, radius)
    lon, lat = grid.healpix_to_lonlat(indices)
    x, y = wcs.all_world2pix(lon.deg, lat.deg, 0, quiet=True)
    ny, nx = valid.shape
    inside = np.isfinite(x) & np.isfinite(y) & (x >= -0.5) & (x < nx - 0.5) & (y >= -0.5) & (y < ny - 0.5)
    accepted = valid[np.floor(y[inside] + 0.5).astype(int), np.floor(x[inside] + 0.5).astype(int)]
    selected = np.sort(indices[inside][accepted])
    if not selected.size:
        return []
    seams = np.flatnonzero(np.diff(selected) != 1)
    starts = np.concatenate((selected[:1], selected[seams + 1]))
    ends = np.concatenate((selected[seams] + 1, selected[-1:] + 1))
    return np.column_stack((starts, ends)).tolist()


def _array(hdu, dtype, shape):
    data = np.asarray(hdu.data, dtype=dtype)
    if data.shape != shape:
        raise ImageRejected(f"The {hdu.name} array does not match the native IMAGE dimensions.")
    del hdu.data
    return data


def _measure(hdul, observation_id, detector):
    """Read every native science pixel and compute quality-masked image measurements."""
    image = hdul["IMAGE"]
    header = image.header.copy()
    if str(header["OBSID"]).strip() != observation_id or int(header["DETECTOR"]) != detector:
        raise ImageRejected("The FITS observation ID or detector differs from the listed NASA product.")
    if header["NAXIS"] != 2:
        raise ImageRejected("A two-dimensional native spectral image is required.")
    nx, ny = int(header["NAXIS1"]), int(header["NAXIS2"])
    if min(nx, ny) < 32 or max(nx, ny) > 4096:
        raise ImageRejected("The native IMAGE dimensions are outside supported bounds.")
    began, mjd, ended = (float(header[key]) for key in ("MJD-BEG", "MJD-AVG", "MJD-END"))
    if not all(map(math.isfinite, (began, mjd, ended))) or not began <= mjd <= ended:
        raise ImageRejected("Invalid observation time metadata in the native IMAGE header.")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        wcs = WCS(header).celestial
    if not wcs.has_celestial or wcs.wcs.radesys != "ICRS" or (wcs.wcs.lng, wcs.wcs.lat) != (0, 1):
        raise ImageRejected("An equatorial ICRS IMAGE WCS with RA/Dec axes is required.")
    x_center, y_center = (nx - 1) / 2, (ny - 1) / 2
    ra, dec = (float(coord) for coord in wcs.all_pix2world(x_center, y_center, 0))
    ra %= 360
    edge_ra, edge_dec = _perimeter(wcs, (ny, nx))
    if not all(map(math.isfinite, (ra, dec))) or not np.all(np.isfinite(edge_ra) & np.isfinite(edge_dec)):
        raise ImageRejected("The IMAGE WCS does not project its native footprint.")

    shape = (ny, nx)
    data = _array(image, np.float32, shape)
    variance = _array(hdul["VARIANCE"], np.float32, shape)
    flags = _array(hdul["FLAGS"], np.uint32, shape)
    zodiacal = "ZODI" in hdul
    if zodiacal:
        data -= _array(hdul["ZODI"], np.float32, shape)
    valid = np.isfinite(data) & np.isfinite(variance) & (variance > 0) & ((flags & MASK_BITS) == 0)
    valid_pixels = int(valid.sum())
    if not valid_pixels:
        raise ImageRejected("No usable native science pixels remain after variance and quality masking.")

    quantiles = np.quantile(data[valid], [0.05, 0.5, 0.95], overwrite_input=True)
    variance_median = float(np.median(variance[valid], overwrite_input=True))
    union_flags = int(np.bitwise_or.reduce(flags, axis=None))
    flag_counts = {name: int(np.count_nonzero(flags & (1 << bit)))
                   for bit, name in BIT_NAMES.items() if union_flags & (1 << bit)}
    center_wave = None
    if "WCS-WAVE" in hdul:
        value = float(wavelength_map(header, hdul["WCS-WAVE"].data, x_center, y_center))
        if math.isfinite(value) and value > 0:
            center_wave = value
    return dict(
        mjd=mjd, startMjd=began, endMjd=ended, date=date_mjd(mjd), center=dict(ra=ra, dec=dec),
        boundary=[dict(ra=float(a), dec=float(d)) for a, d in zip(edge_ra[::4], edge_dec[::4])],
        wcs={key: header[key] for key in header if WCS_CARD.fullmatch(key)},
        coverageNside=COVERAGE_NSIDE, coverageRanges=_coverage_ranges(wcs, valid, ra, dec, edge_ra, edge_dec),
        width=nx, height=ny, validPixels=valid_pixels, totalPixels=valid.size,
        brightnessQuantiles=dict(zip(("p05", "median", "p95"), map(float, quantiles))),
        medianPixelVariance=variance_median, unit=str(header.get("BUNIT", "unknown")).strip(),
        zodiSubtracted=zodiacal, maskBits=MASK_BITS, flagPixelCounts=flag_counts,
        saturatedPixels=int(np.count_nonzero(flags & SAT_BITS)), fineAstrometryFlag=header.get("FINAST"),
        l1Quality=header.get("L1DQAFLG"), wavelengthCenter=center_wave, psfAvailable="EPSF" in hdul,
        calibrationVersion=str(hdul[0].header.get("VERSION", header.get("VERSION", "see FITS headers"))),
    )


def process_image(url: str, expected_id: str, detector: int) -> dict:
    """Download, hash and measure the exact listed public NASA spectral image."""
    try:
        validate_url(url, cloud=True)
    except ValueError as exc:
        raise ImageRejected(str(exc)) from exc
    key = urlsplit(url).path.strip("/")
    match = OBSERVATION_NAME.search(url)
    if not match or expected_id != f"{match[1]}D{match[2]}" or detector != int(match[2]):
        raise ImageRejected("Expected observation identity does not match the NASA FITS path.")
    with tempfile.TemporaryDirectory(prefix="slowtrace-frame-") as temporary:
        attachment = Path(temporary) / "exposure.fits"
        with attachment.open("wb") as destination:
            size, digest, etag = _download(url, destination)
        try:
            with fits.open(attachment, memmap=False, lazy_load_hdus=True) as hdul:
                if not hdul[0].header.get("SIMPLE") or hdul[0].header.get("NAXIS") != 0:
                    raise ImageRejected("An authentic multi-extension SPHEREx spectral FITS image is required.")
                measurement = _measure(hdul, match[1], detector)
        except ImageRejected:
            raise
        except (OSError, ValueError, KeyError, IndexError, TypeError, OverflowError, VerifyError) as exc:
            raise ImageRejected(f"The full native FITS science image could not be measured: {exc}") from exc
    return dict(
        id=expected_id, detector=detector, collection="spherex_" + key.split("/", 1)[0],
        sourceUrl="https://irsa.ipac.caltech.edu/ibe/data/spherex/" + key, cloudUrl=url,
        sha256=digest, downloadedBytes=size, etag=etag, processedAt=now(),
        pipelineVersion=VERSION, **measurement,
    )
