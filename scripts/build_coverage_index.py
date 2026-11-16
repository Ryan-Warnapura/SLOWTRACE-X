"""Index actual SPHEREx WCS metadata with bounded NASA S3 byte-range reads.

Example: python scripts/build_coverage_index.py --workers 8 --s3-periods 12 --per-period 12
The standard index starts from the five recorded target lists and M101 tutorial
paths. Optionally extend it with an explicitly sampled set of S3 exposure paths.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from science.archive import _reference_catalog, cloud_url, now, validate_url
from science.coverage import INDEX_PATH, record

IRSA_BASE = 'https://irsa.ipac.caltech.edu/ibe/data/spherex/'
BUCKET = 'https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/'
TUTORIAL_PRODUCTS = (
    'dr1/level2/2025W20_2D/l2b-v27-2026-198/2/level2_2025W20_2D_0176_4D2_spx_l2b-v27-2026-198.fits',
    'dr1/level2/2025W21_2C/l2b-v27-2026-199/2/level2_2025W21_2C_0401_1D2_spx_l2b-v27-2026-199.fits',
    'dr1/level2/2025W22_1B/l2b-v27-2026-199/2/level2_2025W22_1B_0584_1D2_spx_l2b-v27-2026-199.fits',
    'dr1/level2/2025W49_2A/l2b-v27-2026-209/2/level2_2025W49_2A_0426_2D2_spx_l2b-v27-2026-209.fits',
    'dr1/level2/2025W50_1A/l2b-v27-2026-209/2/level2_2025W50_1A_0223_1D2_spx_l2b-v27-2026-209.fits',
    'qr3/level2/2026W20_2A/l2b-v27-2026-267/2/level2_2026W20_2A_0464_4D2_spx_l2b-v27-2026-267.fits',
    'qr3/level2/2026W21_2A/l2b-v27-2026-268/1/level2_2026W21_2A_0001_2D1_spx_l2b-v27-2026-268.fits',
)


def evenly_spaced(items, count):
    if count == 0 or not items:
        return []
    if len(items) <= count:
        return list(items)
    return [items[int(i)] for i in np.linspace(0, len(items)-1, count).round()]


def listing(prefix, delimiter='/', *, max_pages=8):
    token = None
    for _ in range(max_pages):
        params = {'list-type': 2, 'prefix': prefix, 'delimiter': delimiter}
        if token:
            params['continuation-token'] = token
        response = requests.get(BUCKET, params=params, timeout=(8, 20))
        response.raise_for_status()
        tree = ElementTree.fromstring(response.content)
        yield from ((x.text, True) for x in tree.findall('{*}CommonPrefixes/{*}Prefix'))
        yield from ((x.text, False) for x in tree.findall('{*}Contents/{*}Key'))
        token = tree.findtext('{*}NextContinuationToken')
        if not token:
            return


def from_period(period, per_period):
    versions = sorted(key for key, is_prefix in listing(period) if is_prefix and '/l2b-v' in key)
    if not versions:
        return []
    # D1 by default, sampled across ordered exposure products in each interval.
    products = sorted(key for key, is_prefix in listing(versions[-1]+'1/') if not is_prefix and key.endswith('.fits'))
    return [IRSA_BASE + key for key in evenly_spaced(products, per_period)]


def fetch_record(url):
    try:
        cloud = cloud_url(validate_url(url))
        with requests.get(cloud, headers={'Range':'bytes=0-34559'}, timeout=(6, 15), stream=True, allow_redirects=False) as response:
            response.raise_for_status()
            if response.status_code != 206 or not response.headers.get('Content-Range','').startswith('bytes 0-34559/'):
                raise ValueError('S3 did not return the requested byte range.')
            return record(url, response.raw.read(34560), now()), None
    except (requests.RequestException, ValueError, RuntimeError, KeyError) as error:
        return None, f'{type(error).__name__}: {error}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, choices=range(1,17), default=8)
    parser.add_argument('--target-per-detector',type=int, default=36)
    parser.add_argument('--s3-periods', type=int, default=0, help='Evenly spaced archive planning periods to sample per release')
    parser.add_argument('--per-period', type=int, default=8, help='Max sampled D1 products in each selected S3 planning period')
    parser.add_argument('--output', type=Path, default=INDEX_PATH)
    args = parser.parse_args()
    if not 0 <= args.s3_periods <= 100 or not 1 <= args.per_period <= 300 or not 1 <= args.target_per_detector <= 150:
        parser.error('Use bounded sample counts: 0–100 periods, 1–300 per period, and 1–150 per target detector.')
    urls = {IRSA_BASE+p for p in TUTORIAL_PRODUCTS}
    for target in _reference_catalog().values():
        for detector in range(1,7):
            candidates = [row for row in target['observations'] if row['energy_bandpassname'].endswith(f'-D{detector}')]
            candidates.sort(key=lambda r:float(r['t_min']))
            urls.update(row['access_url'] for row in evenly_spaced(candidates, args.target_per_detector))
    periods = []
    if args.s3_periods:
        for release in ('dr1','qr3'):
            choices = sorted(key for key, is_prefix in listing(f'{release}/level2/') if is_prefix)
            periods.extend(evenly_spaced(choices, args.s3_periods))
        with ThreadPoolExecutor(min(args.workers, 8)) as pool:
            for found in pool.map(lambda p:from_period(p,args.per_period), periods):
                urls.update(found)
    records, failures = [], []
    urls = sorted(urls)
    print(f'Inspecting {len(urls)} genuine FITS headers in the public NASA S3 mirror.', flush=True)
    with ThreadPoolExecutor(args.workers) as pool:
        for i,(found,error) in enumerate(pool.map(fetch_record, urls), 1):
            if found:
                records.append(found)
            else:
                failures.append({'url':urls[i-1], 'problem':error})
            if i%100==0:
                print(f'Checked {i} of {len(urls)} headers · {len(records)} valid', flush=True)
    if not records:
        raise SystemExit('No valid FITS headers found. Existing index was preserved.')
    index = {'schema':1, 'generatedAt':now(), 'source':BUCKET,
             'attemptedProducts':len(urls), 'sampling':{'targetPerDetector':args.target_per_detector,
             's3Periods':periods, 'perPeriod':args.per_period}, 'failures':failures, 'records':records}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    stage = args.output.with_suffix('.tmp')
    with gzip.open(stage, 'wt', encoding='utf-8', compresslevel=9) as out:
        json.dump(index, out, ensure_ascii=True, separators=(',',':'), allow_nan=False)
    stage.replace(args.output)
    print(f'Saved {len(records)} verified FITS headers ({len(failures)} failures) to {args.output}')


if __name__ == '__main__':
    main()
