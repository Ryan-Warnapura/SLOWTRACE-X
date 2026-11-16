"""Capture geometric heliocentric ephemerides for the Solar System view.

Every plotted body state comes from a JPL Horizons VECTORS result. The Sun is
the coordinate origin. Requests are serial per the Horizons API usage policy.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time

import requests

HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
FIRST, LAST = "2025-04-01", "2027-01-01"
TARGETS = {
    "mercury": ("199", "Mercury", "Planet"),
    "venus": ("299", "Venus", "Planet"),
    "earth": ("399", "Earth", "Planet"),
    "mars": ("499", "Mars", "Planet"),
    "jupiter": ("599", "Jupiter", "Planet"),
    "saturn": ("699", "Saturn", "Planet"),
    "uranus": ("799", "Uranus", "Planet"),
    "neptune": ("899", "Neptune", "Planet"),
    "ceres": ("1;", "Ceres", "Dwarf planet"),
    "interstellar": ("DES=3I;", "3I/ATLAS", "Interstellar comet"),
}
OUT = Path(__file__).resolve().parents[1] / "public/solar/horizons.json"


def query(session, command, name, classification):
    parameters = {
        "format": "json",
        "COMMAND": f"'{command}'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'VECTORS'",
        "CENTER": "'500@10'",
        "START_TIME": f"'{FIRST}'",
        "STOP_TIME": f"'{LAST}'",
        "STEP_SIZE": "'2 d'",
        "TIME_TYPE": "'UT'",
        "OUT_UNITS": "'AU-D'",
        "REF_PLANE": "'ECLIPTIC'",
        "REF_SYSTEM": "'ICRF'",
        "VEC_CORR": "'NONE'",
        "VEC_TABLE": "'1'",
        "CSV_FORMAT": "'YES'",
    }
    for attempt in range(3):
        try:
            response = session.get(HORIZONS, params=parameters, timeout=(8, 25))
            response.raise_for_status()
            data = response.json()
            raw = data.get("result", "")
            if "$$SOE" not in raw or "$$EOE" not in raw:
                raise ValueError((data.get("error") or raw)[-650:])
            break
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(1 + 2 * attempt)
    head, bulk = raw.split("$$SOE", 1)
    result = bulk.split("$$EOE", 1)[0]
    body = next(line.split(":", 1)[1].strip() for line in head.splitlines() if "Target body name:" in line)
    if name not in body and not (name == "3I/ATLAS" and "C/2025 N1" in body):
        raise ValueError(f"Horizons resolved a different target: {body}")
    if "Sun (10)" not in head or "Ecliptic of J2000.0" not in head or "AU-D" not in head:
        raise ValueError("Unexpected origin, reference plane or units")
    samples = []
    for row in csv.reader(result.splitlines(), skipinitialspace=True):
        if not row:
            continue
        jd, x, y, z = float(row[0]), float(row[2]), float(row[3]), float(row[4])
        if not all(math.isfinite(value) for value in (jd, x, y, z)) or (samples and jd <= samples[-1][0]):
            raise ValueError("Invalid Horizons ephemeris sample")
        samples.append([jd, round(x, 10), round(y, 10), round(z, 10)])
    if len(samples) < 300:
        raise ValueError("Incomplete Horizons date coverage")
    return dict(name=name, classification=classification, target=body, source=response.url, samples=samples)


def main():
    states = {}
    with requests.Session() as session:
        session.headers["User-Agent"] = "SLOWTRACE-X/3.0 (SPHEREx educational visualization)"
        for identifier, target in TARGETS.items():
            try:
                states[identifier] = query(session, *target)
                print(identifier, len(states[identifier]["samples"]), flush=True)
            except (requests.RequestException, ValueError, StopIteration) as error:
                if identifier != "interstellar":
                    raise
                print(f"Optional comet unavailable ({error})", flush=True)
    anchors = states["earth"]["samples"]
    if any([s[0] for s in body["samples"]] != [s[0] for s in anchors] for body in states.values()):
        raise ValueError("Body ephemerides do not share a time grid")
    data = dict(
        origin="Sun center (500@10)",
        frame="Ecliptic of J2000.0, ICRF",
        timeScale="UT (modern dates in UTC)",
        positionUnit="au",
        source="NASA/JPL Horizons",
        sourceHome="https://ssd.jpl.nasa.gov/horizons/",
        retrievedAt=datetime.now(timezone.utc).isoformat(),
        stepDays=2,
        bodies=states,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(OUT)


if __name__ == "__main__":
    main()
