"""Capture small, attributable NASA image packets for the challenge examples.

The input list is the preserved archive metadata credited in the repository.
Pixels are always retrieved from the official archive and processed afresh.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from science import archive
from science.analysis import RESOLVING_POWER

TARGETS = {"epsindib": 1, "wise0855": 6, "rwaur": 1, "rdra": 1}


def select_frames(frames, detector):
    """Prefer the longest near-bandpass temporal baseline, then exact epoch ends."""
    frames.sort(key=lambda item: item[1]["metadata"]["mjd"])
    pairs = []
    for i, first in enumerate(frames):
        fa = first[1]["metadata"]
        for second in frames[i+1:]:
            fb = second[1]["metadata"]
            waves = [fa["wavelengthCenter"], fb["wavelengthCenter"]]
            if any(not w for w in waves) or fa["zodiSubtracted"] != fb["zodiSubtracted"]:
                continue
            span = fb["mjd"] - fa["mjd"]
            if span >= 30 and max(waves) / min(waves) <= 1 + 1 / RESOLVING_POWER[detector]:
                pairs.append((span, first, second))
    if pairs:
        _, first, last = max(pairs, key=lambda item: item[0])
        return [first, last]
    return [frames[0], frames[-1]]


def capture(slug, detector, budget):
    catalog = archive._reference_catalog()[slug]
    centre = catalog["center"]
    ra, dec = centre["ra"], centre["dec"]
    observations = [row for row in archive._normalize(catalog["observations"]) if row["detector"] == detector]
    if len(observations) < 2:
        raise RuntimeError(f"{slug} has too few detector {detector} observations")
    indices = np.linspace(0, len(observations)-1, min(len(observations), budget)).round().astype(int)
    choices = [observations[int(i)] for i in indices]

    def read(o):
        try:
            return o, archive.frame(o["url"], ra, dec, 5, 96)
        except Exception as error:
            print(f"{slug}: {o['id']} could not be captured ({type(error).__name__})", flush=True)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        frames = [p for p in pool.map(read, choices) if p]
    if len(frames) < 2:
        raise RuntimeError(f"{slug}: fewer than two usable NASA exposures")
    selected = select_frames(frames, detector)
    recorded_at = archive.now()
    packet = {
        "recordedAt": recorded_at,
        "search": {
            "query": dict(ra=ra, dec=dec, fov=5, detector=detector),
            "source": "NASA/IPAC IRSA",
            "status": "recorded-observations",
            "queriedAt": recorded_at,
            "archiveChecked": catalog["archiveChecked"],
            "queryUrls": [],
            "totalAvailable": len(observations),
            "truncated": True,
            "warnings": ["Recorded example. Its authentic NASA pixels were captured before this session. Each frame lists its acquisition method and retrieval timestamp."],
            "observations": [item[0] for item in selected],
        },
        "frames": [item[1] for item in selected],
    }
    destination = ROOT / "public" / "examples" / f"{slug}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(packet, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(slug, [(f["metadata"]["date"], f["metadata"]["wavelengthCenter"]) for f in packet["frames"]], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="*", choices=tuple(TARGETS), default=None)
    parser.add_argument("--budget", type=int, default=6, choices=range(2, 13))
    args = parser.parse_args()
    for slug in args.targets or TARGETS:
        capture(slug, TARGETS[slug], args.budget)


if __name__ == "__main__":
    main()
