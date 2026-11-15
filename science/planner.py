"""Geometric visibility of a fixed ICRS pointing; no orbit or weather prediction.

AI-assisted implementation. Astronomy is calculated by Astropy, not generated.
Reference: https://docs.astropy.org/en/stable/coordinates/example_gallery_plot_obs_planning.html
"""

from datetime import date as Date
import math
import warnings

import numpy as np
import astropy.units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_sun
from astropy.time import Time
from astropy.utils import iers

# Use packaged Earth-orientation data; a web request must not block a planner.
iers.conf.auto_download = False
iers.conf.auto_max_age = None


def _number(value, name, lower, upper):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a finite number") from None
    if not math.isfinite(result) or not lower <= result <= upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return result


def plan_followup(
    ra, dec, latitude, longitude, date, elevation_m=0,
    min_altitude=30, max_sun_altitude=-18, step_minutes=20,
):
    """Sample 00:00–24:00 UTC for a fixed coordinate and terrestrial location.

    RA/Dec are ICRS degrees, longitude is east-positive, elevation is meters.
    Windows delimit passing samples, not precisely solved rise/set crossings.
    Returns only JSON-compatible values. This is intentionally not an ephemeris
    for an unconfirmed moving source: users must provide its future pointing.
    """
    ra = _number(ra, "Right ascension", 0, 360)
    if ra == 360:
        ra = 0.0
    dec = _number(dec, "Declination", -90, 90)
    latitude = _number(latitude, "Latitude", -90, 90)
    longitude = _number(longitude, "Longitude", -180, 180)
    elevation_m = _number(elevation_m, "Elevation", -500, 10000)
    min_altitude = _number(min_altitude, "Minimum altitude", 0, 90)
    max_sun_altitude = _number(max_sun_altitude, "Maximum Sun altitude", -30, 0)
    step_minutes = _number(step_minutes, "Sampling interval", 5, 60)
    if int(step_minutes) != step_minutes:
        raise ValueError("Sampling interval must be whole minutes")
    step_minutes = int(step_minutes)
    try:
        day = Date.fromisoformat(str(date))
    except ValueError:
        raise ValueError("Date must be YYYY-MM-DD in UTC") from None
    if not 2000 <= day.year <= 2100:
        raise ValueError("Planner supports dates from 2000 through 2100")

    minutes = np.arange(0, 1440, step_minutes, dtype=float)
    minutes = np.append(minutes, 1440.0)
    times = Time(f"{day.isoformat()}T00:00:00", scale="utc") + minutes * u.min
    location = EarthLocation.from_geodetic(longitude*u.deg, latitude*u.deg, elevation_m*u.m)
    target = SkyCoord(ra=ra*u.deg, dec=dec*u.deg, frame="icrs")
    frame = AltAz(obstime=times, location=location, pressure=0*u.hPa)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        target_horizontal = target.transform_to(frame)
        solar_horizontal = get_sun(times).transform_to(frame)
    altitude = target_horizontal.alt.deg
    sun_altitude = solar_horizontal.alt.deg
    valid = (altitude >= min_altitude) & (sun_altitude <= max_sun_altitude)
    rows = []
    for i, instant in enumerate(times):
        alt = float(altitude[i])
        rows.append({
            "time": instant.utc.isot + "Z",
            "altitude": round(alt, 4),
            "azimuth": round(float(target_horizontal.az.deg[i]), 4),
            "sunAltitude": round(float(sun_altitude[i]), 4),
            "airmass": round(1/math.sin(math.radians(alt)), 4) if alt >= 10 else None,
            "observable": bool(valid[i]),
        })
    windows = []
    first = None
    for i in range(len(rows)+1):
        if i < len(rows) and valid[i]:
            if first is None:
                first = i
        elif first is not None:
            last = i-1
            windows.append({
                "start": rows[first]["time"], "end": rows[last]["time"],
                "durationMinutes": float(minutes[last]-minutes[first]),
                "sampleCount": last-first+1,
            })
            first = None
    valid_indices = np.flatnonzero(valid)
    best = int(valid_indices[np.argmax(altitude[valid_indices])]) if len(valid_indices) else None
    limitations = [
        "Fixed ICRS pointing; no proper motion, parallax, candidate orbit or trajectory extrapolation.",
        "Airless geometric altitudes; no refraction, weather, terrain, telescope or brightness constraints.",
        f"UTC samples every {step_minutes} minutes; window boundaries are passing samples, not exact crossings.",
        "Approximate secant airmass is shown only above 10 degrees; not an atmospheric transmission model.",
        "Packaged IERS Earth-orientation data; precision may degrade outside its covered dates.",
    ]
    if not windows:
        limitations.append("No sampled time meets the selected altitude and darkness limits.")
    for warning in caught:
        message = str(warning.message)
        if message not in limitations:
            limitations.append(message)
    return {
        "status": "calculated", "kind": "fixed-coordinate-visibility",
        "coordinates": {"ra": ra, "dec": dec, "frame": "ICRS"},
        "observer": {"latitude": latitude, "longitude": longitude, "elevationM": elevation_m},
        "date": day.isoformat(), "timeScale": "UTC",
        "constraints": {"minAltitude": min_altitude, "maxSunAltitude": max_sun_altitude,
                        "stepMinutes": step_minutes, "refraction": False},
        "samples": rows, "windows": windows,
        "best": rows[best] if best is not None else None,
        "limitations": limitations,
        "method": "Astropy ICRS-to-AltAz and builtin get_sun; packaged IERS, pressure=0 hPa.",
    }
