"""Incremental inventory of public SPHEREx Level 2 objects, without FITS reads."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import zip_longest
import re
from urllib.parse import urlsplit
from xml.etree import ElementTree

import requests

from .archive import OBSERVATION_NAME, cloud_url, validate_url

BUCKET = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/"
RELEASES = ("dr1", "qr3")
VERSION = re.compile(r"l2b-v(\d+)-(\d{4})-(\d{3})")


@dataclass(frozen=True)
class Product:
    id: str
    url: str
    detector: int
    rank: int
    size: int | None = None
    etag: str | None = None


def product(url, size=None, etag=None):
    parsed = urlsplit(url)
    url = parsed._replace(query="", fragment="").geturl()
    if parsed.hostname == urlsplit(BUCKET).hostname:
        validate_url(url, cloud=True)
    else:
        url = cloud_url(url)
    path = urlsplit(url).path
    match = OBSERVATION_NAME.search(path)
    if not match:
        raise ValueError("Object is not a standard SPHEREx spectral image.")
    release, _, period, version, directory_detector, *_ = path.lstrip("/").split("/")
    suffix = VERSION.fullmatch(version)
    detector = int(match[2])
    if not suffix or directory_detector != str(detector) or not match[1].startswith(period + "_"):
        raise ValueError("SPHEREx filename, planning period and detector do not agree.")
    v, year, day = map(int, suffix.groups())
    rank = int(release == "dr1") * 10**11 + v * 10**7 + year * 1000 + day
    return Product(f"{match[1]}D{detector}", url, detector, rank, size, etag)


def list_page(session, prefix, *, folders=False, after=None, page_size=1000):
    params = {"list-type": "2", "prefix": prefix, "max-keys": page_size}
    if folders:
        params["delimiter"] = "/"
    if after:
        params["start-after"] = after
    with session.get(BUCKET, params=params, timeout=(8, 25), allow_redirects=False) as response:
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
    if root.tag.rsplit("}", 1)[-1] != "ListBucketResult" or root.findtext("{*}Prefix") != prefix:
        raise ValueError("Unexpected response from the SPHEREx bucket listing.")
    keys = [item.text for item in root.findall("{*}CommonPrefixes/{*}Prefix")]
    objects = [(item.findtext("{*}Key"), int(item.findtext("{*}Size")), item.findtext("{*}ETag"))
               for item in root.findall("{*}Contents")]
    all_keys = keys + [key for key, _, _ in objects]
    if any(not key or not key.isascii() or not key.startswith(prefix) or (after and key <= after)
           for key in all_keys):
        raise ValueError("S3 returned an invalid or already-read object key.")
    more = root.findtext("{*}IsTruncated") == "true"
    if more and not all_keys:
        raise ValueError("S3 marked an empty listing as incomplete.")
    return keys, objects, max(all_keys, default=after), not more


def spread(items):
    """Visit archive periods across the full time range before refining the gaps."""
    groups = [(0, len(items))]
    while groups:
        next_level = []
        for left, right in groups:
            if right > left:
                mid = (left + right) // 2
                yield items[mid]
                next_level.extend(((left, mid), (mid + 1, right)))
        groups = next_level


def periods(session, release):
    prefix = f"{release}/level2/"
    result = []
    cursor, done = None, False
    while not done:
        keys, _, cursor, done = list_page(session, prefix, folders=True, after=cursor)
        result.extend(key for key in keys if re.fullmatch(r"\d{4}W\d{2}_\d[A-Z]/", key.removeprefix(prefix)))
    return result


def seed_pilot(snapshot):
    """Reuse exact product identities previously analyzed in the published pilot."""
    return [product(row["url"]) for analysis in snapshot["analyses"] for row in analysis["observations"]]


def discover(store, budget, *, releases=RELEASES, selected_periods=(), refresh=False):
    """Allocate a bounded number of inventory requests, committing every page and cursor."""
    with requests.Session() as session:
        fresh = []
        for release in releases:
            try:
                fresh.append(list(spread(periods(session, release))))
            except (requests.RequestException, ElementTree.ParseError, ValueError) as error:
                store.catalog_failure({"prefix": f"{release}/level2/", "cursor": None}, error)
        store.add_scopes(prefix for group in zip_longest(*fresh) for prefix in group if prefix)
        if refresh:
            store.reset_scopes()
        visited = set()
        pages = objects = errors = 0
        for _ in range(budget):
            scope = store.next_scope(visited, releases, selected_periods)
            if scope is None:
                break
            prefix = scope["prefix"]
            visited.add(prefix)
            try:
                is_period = scope["kind"] == "period"
                prefixes, entries, cursor, done = list_page(session, prefix, folders=is_period, after=scope["cursor"])
                versions = [(tuple(map(int, match.groups())), version) for version in prefixes
                            if (match := VERSION.fullmatch(version.removeprefix(prefix).rstrip("/")))]
                children = [f"{version}{detector}/" for _, version in sorted(versions, reverse=True)
                            for detector in range(1, 7)]
                items = []
                for key, size, etag in entries:
                    if not OBSERVATION_NAME.search("/" + key):
                        continue
                    items.append(product(BUCKET + key, size, etag))
                if store.record_page(scope, cursor, done, children=children, products=list(spread(items))):
                    pages += 1
                    objects += len(items)
            except (requests.RequestException, ElementTree.ParseError, ValueError) as error:
                store.catalog_failure(scope, error)
                errors += 1
    return dict(pages=pages, listedObjects=objects, errors=errors)
