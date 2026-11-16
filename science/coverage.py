"""A bounded, reproducible index of authentic SPHEREx Level 2 detector footprints."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import FITSFixedWarning, WCS

INDEX_PATH = Path(__file__).parent / 'data' / 'coverage-index.json.gz'
WCS_CARD = re.compile(
    r'(?:NAXIS[12]|WCSAXES|RADESYS|EQUINOX|LONPOLE|LATPOLE|'
    r'(?:CTYPE|CUNIT|CRPIX|CRVAL|CDELT)[12]|(?:PC|CD)[12]_[12]|'
    r'(?:A|B|AP|BP)_(?:ORDER|\d+_\d+))$'
)


def _unit_points(ra, dec):
    ra, dec = np.radians(ra), np.radians(dec)
    cos_dec = np.cos(dec)
    return np.stack((np.cos(ra)*cos_dec, np.sin(ra)*cos_dec, np.sin(dec)), axis=-1)


def read_header_block(blob, offset):
    """Parse one complete FITS header without reading any image bytes."""
    for i in range(offset, len(blob)-79, 80):
        if blob[i:i+8] == b'END     ':
            end = i+80
            return fits.Header.fromstring(blob[offset:end].decode('ascii')), ((end+2879)//2880)*2880
    raise ValueError('FITS header does not fit inside the requested byte range.')


def record(url, blob, captured_at):
    """Retain the actual image WCS, times, product checksum and a footprint prefilter."""
    primary, image_start = read_header_block(blob, 0)
    if not primary.get('SIMPLE') or primary.get('NAXIS') != 0:
        raise ValueError('Unexpected SPHEREx primary HDU.')
    h, image_end = read_header_block(blob, image_start)
    if h.get('EXTNAME') != 'IMAGE' or h.get('NAXIS') != 2:
        raise ValueError('The first SPHEREx extension must be a two-dimensional IMAGE.')
    values = {k: h[k] for k in h if WCS_CARD.fullmatch(k)}
    wcs = WCS(fits.Header(values)).celestial
    nx, ny = h['NAXIS1'], h['NAXIS2']
    x = np.linspace(-.5, nx-.5, 24)
    y = np.linspace(-.5, ny-.5, 24)
    edge_x = np.r_[x, x, np.full_like(y, -.5), np.full_like(y, nx-.5)]
    edge_y = np.r_[np.full_like(x, -.5), np.full_like(x, ny-.5), y, y]
    ra, dec = wcs.all_pix2world(edge_x, edge_y, 0)
    centre = _unit_points(*wcs.all_pix2world((nx-1)/2, (ny-1)/2, 0))
    offset = _unit_points(ra, dec) @ centre
    radius = float(np.arccos(np.clip(offset.min(), -1, 1))) + math.radians(.1)
    began, mean, ended = (float(h[key]) for key in ('MJD-BEG', 'MJD-AVG', 'MJD-END'))
    if not (math.isfinite(radius) and began <= mean <= ended):
        raise ValueError('The SPHEREx header has invalid exposure time or WCS metadata.')
    return {
        'url': url, 'id': str(h['OBSID']), 'detector': int(h['DETECTOR']),
        'mjd': mean, 'startMjd': began, 'endMjd': ended,
        'centerVector': centre.tolist(), 'radiusCosine': math.cos(radius),
        'wcs': values, 'capturedAt': captured_at,
        'fitsHeaderSha256': hashlib.sha256(blob[:image_end]).hexdigest(),
        'processingVersion': str(primary.get('VERSION', 'see FITS headers')),
    }


@lru_cache(maxsize=1)
def read_index():
    if not INDEX_PATH.exists():
        return None
    with gzip.open(INDEX_PATH, 'rt', encoding='utf-8') as stream:
        return json.load(stream)


def _on_image(record, ra, dec):
    header = fits.Header(record['wcs'])
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', FITSFixedWarning)
        wcs = WCS(header).celestial
    try:
        x, y = wcs.all_world2pix(ra, dec, 0)
    except (ValueError, RuntimeError):
        return False
    return -.5 <= x < header['NAXIS1']-.5 and -.5 <= y < header['NAXIS2']-.5


def matching_records(ra, dec, detector, releases):
    """Select only footprints whose exact detector WCS covers this field centre."""
    index = read_index()
    if not index:
        return [], None
    point = _unit_points(ra, dec)
    records = []
    for r in index['records']:
        release = r['url'].split('/spherex/', 1)[1].split('/', 1)[0]
        if (r['detector'] == detector and release in releases
                and np.dot(r['centerVector'], point) >= r['radiusCosine']
                and _on_image(r, ra, dec)):
            records.append(r)
    return records, index['generatedAt']
