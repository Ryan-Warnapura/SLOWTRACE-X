"""Build a global time-stratified metadata sample from original NASA S3 FITS.

Each product costs one bounded header read. This is an independent backup to
IRSA query services and is deliberately a sample, not an archive inventory.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import gzip
import json
from pathlib import Path
import re
import sys
from threading import local
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_coverage_index import IRSA_BASE, evenly_spaced, listing
from science.archive import cloud_url, now
from science.coverage import record

_local = local()


def products(period, budget):
    releases = sorted(key for key, prefix in listing(period) if prefix and re.search(r'/l2b-v\d', key))
    if not releases:
        return []
    parent = releases[-1]
    found = []
    for detector, count in ((1, budget), (2, budget // 2)):
        keys = sorted(key for key, prefix in listing(f"{parent}{detector}/") if not prefix and key.endswith('.fits'))
        found.extend(IRSA_BASE + key for key in evenly_spaced(keys, count))
    return found


def session():
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
    return _local.session


def get_record(url):
    # The larger range deliberately accommodates FITS keyword/header variations.
    size = 34560
    try:
        with session().get(cloud_url(url), headers={"Range": f"bytes=0-{size - 1}"}, timeout=(4, 8), stream=True,
                           allow_redirects=False) as reply:
            if reply.status_code != 206 or not reply.headers.get("Content-Range", "").startswith(f"bytes 0-{size - 1}/"):
                raise ValueError(f"Unverified byte response HTTP {reply.status_code}")
            return record(url, reply.raw.read(size), now()), None
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        return None, f"{type(error).__name__}: {error}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--per-period', type=int, default=48, choices=range(8, 97))
    parser.add_argument('--workers', type=int, default=12, choices=range(2, 17))
    parser.add_argument('--output', type=Path, default=ROOT/'science/data/archive-sample.json.gz')
    args = parser.parse_args()
    started = time.monotonic()
    periods = [p for release in ('dr1', 'qr3') for p,is_prefix in listing(f'{release}/level2/') if is_prefix]
    with ThreadPoolExecutor(min(8, args.workers)) as pool:
        items = list(pool.map(partial(products,budget=args.per_period), periods))
    urls = sorted({url for group in items for url in group})
    print(f'{len(urls)} bounded header reads across {len(periods)} planning periods.',flush=True)
    records, failures = [], []
    with ThreadPoolExecutor(args.workers) as pool:
        for i,(value,error) in enumerate(pool.map(get_record, urls), 1):
            if value:
                records.append(value)
            else:
                failures.append({'url': urls[i-1], 'problem': error})
            if i % 1000 == 0:
                print(f'{i}/{len(urls)} headers checked, {len(records)} accepted in {time.monotonic()-started:.1f}s.',flush=True)
    if not records:
        raise SystemExit('No usable archive metadata. The existing sample was preserved.')
    output = dict(schema=1, generatedAt=now(), source='NASA SPHEREx public S3 FITS headers',
                  attemptedProducts=len(urls), failedProducts=len(failures),
                  sampling={'method':'Evenly spaced product names in each available DR1 and QR3 planning period',
                            'detectors':[1,2], 'periods':periods, 'capD1':args.per_period, 'capD2':args.per_period//2},
                  failures=failures[:30], records=records)
    stage = args.output.with_suffix('.tmp')
    with gzip.open(stage, 'wt', encoding='utf-8', compresslevel=6) as file:
        json.dump(output, file, separators=(',', ':'), allow_nan=False)
    stage.replace(args.output)
    print(f'{len(records)} headers written, {len(failures)} failed; {time.monotonic()-started:.1f}s.',flush=True)


if __name__ == '__main__':
    main()
