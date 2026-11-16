"""Recompute the published unique, successful-operation and image-area totals."""
from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path
import re

import numpy as np


def audit(snapshot_path, ledger_path):
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    summary = snapshot["summary"]
    with gzip.open(ledger_path, "rt", encoding="utf-8") as handle:
        metadata = json.loads(next(handle))
        nside = metadata["coverageNside"]
        assert nside == snapshot["coverage"]["nside"]
        sky = np.zeros(12 * nside**2, dtype=bool)
        unique = set()
        completed = downloaded = 0
        for line in handle:
            attempt = json.loads(line)
            if attempt["status"] != "success":
                assert not attempt["first_success"]
                continue
            image = attempt["result"]
            assert image["id"] == attempt["id"]
            assert image["cloudUrl"] == attempt["url"]
            assert image["cloudUrl"].startswith("https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/")
            assert re.fullmatch(r"[0-9a-f]{64}", image["sha256"])
            assert 0 < image["validPixels"] <= image["totalPixels"] == image["width"] * image["height"]
            assert image["coverageNside"] == nside
            if attempt["first_success"]:
                assert image["id"] not in unique
                unique.add(image["id"])
            completed += 1
            downloaded += image["downloadedBytes"]
            for start, end in image["coverageRanges"]:
                assert 0 <= start < end <= len(sky)
                sky[start:end] = True
    cells = int(sky.sum())
    area = cells * (4 * math.pi * (180 / math.pi) ** 2 / len(sky))
    assert len(unique) == summary["uniqueProcessed"]
    assert completed == summary["successfulOperations"]
    assert cells == snapshot["coverage"]["cells"]
    assert math.isclose(area, snapshot["coverage"]["areaSquareDegrees"], rel_tol=0, abs_tol=1e-8)
    return dict(uniqueProcessed=len(unique), successfulOperations=completed,
                successfulDownloadBytes=downloaded, acceptedCells=cells, areaSquareDegrees=area)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("ledger", type=Path)
    options = parser.parse_args()
    print(json.dumps(audit(options.snapshot, options.ledger), indent=2))


if __name__ == "__main__":
    main()
