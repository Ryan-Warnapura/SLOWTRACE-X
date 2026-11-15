"""Reproduce checks on shipped genuine NASA pixels; --refresh also fetches new cutouts.

Run from repository root: python scripts/validate_live.py [--refresh]
Default does not contact NASA. The report states source dates and does not claim new discovery.
"""
from pathlib import Path
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from science.archive import frame, search, now, MASK_BITS, _reference_catalog
from science.analysis import analyze_stack, experiment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="query IRSA and fetch two fresh cutouts for each of the five challenge fields")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    starter = json.loads((root / "public/starter.json").read_text())
    frames = starter["frames"]
    size = frames[0]["width"]
    arrays = np.array([np.array(f["data"], float).reshape(size, size) for f in frames])
    variance = np.array([np.array(f["variance"], float).reshape(size, size) for f in frames])
    flags = np.array([np.array(f["mask"], int).reshape(size, size) for f in frames])
    bad = ~np.isfinite(arrays) | ((flags & MASK_BITS) != 0)
    metadata = [f["metadata"] for f in frames]
    science_args = (arrays, variance, bad, np.array([m["mjd"] for m in metadata]))
    kwargs = dict(pixel_arcsec=metadata[0]["pixelArcsec"], wavelengths_um=np.array([m["wavelengthCenter"] for m in metadata]),
                  detector_ids=np.array([m["detector"] for m in metadata]), velocities_arcsec_day=[[-.02, 0], [0, 0], [.02, 0]])
    analysis = analyze_stack(*science_args, **kwargs)
    injection = experiment(*science_args, **kwargs, seed=42, trials=8, injected_snr=3, motion_arcsec_day=(.02, 0))
    output = dict(runAt=now(), recordedAt=starter["recordedAt"], frames=len(frames),
                  selectedFrameIndices=analysis["selectedFrameIndices"], excludedFrameIndices=analysis["excludedFrameIndices"],
                  baselineDays=analysis.get("baselineDays"), experiment=injection,
                  observationProvenance=[f["provenance"] for f in frames])
    if args.refresh:
        results = []
        for slug, target in _reference_catalog().items():
            c = target["center"]
            try:
                found = search(c["ra"], c["dec"], 5, 1, 4)
                selected = [found["observations"][0], found["observations"][-1]]
                with ThreadPoolExecutor(2) as pool:
                    downloaded = list(pool.map(lambda o: frame(o["url"], c["ra"], c["dec"], 5, 64), selected))
                results.append(dict(target=slug, status="pass", searchStatus=found["status"], warnings=found["warnings"],
                                    frames=[dict(metadata=f["metadata"], provenance=f["provenance"], validPixels=sum(x is not None for x in f["data"])) for f in downloaded]))
            except Exception as error:
                results.append(dict(target=slug, status="failed", error=str(error)))
        output["liveTargets"] = results
    destination = root / "docs/reproduced-validation.json"
    destination.write_text(json.dumps(output, indent=2))
    print(json.dumps({"report": str(destination), "selectedFrames": output["selectedFrameIndices"],
                      "recovered": injection["recovered"], "trials": injection["trials"],
                      "liveTargets": [{"target": r["target"], "status": r["status"]} for r in output.get("liveTargets", [])]}, indent=2))


if __name__ == "__main__":
    main()
