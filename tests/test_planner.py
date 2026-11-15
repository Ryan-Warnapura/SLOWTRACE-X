"""Physical invariants and boundary handling for geometric planning."""
import json
import pytest

from science.planner import plan_followup


def test_celestial_pole_tracks_observer_latitude():
    result = plan_followup(0, 90, 40, -75, "2026-11-15")
    # J2000 pole precession/nutation can shift this by a small fraction of a degree.
    assert all(abs(row["altitude"]-40) < 0.5 for row in result["samples"])
    assert len(result["samples"]) == 73
    assert result["samples"][0]["time"] == "2026-11-15T00:00:00.000Z"
    assert result["samples"][-1]["time"] == "2026-11-16T00:00:00.000Z"
    assert result["windows"]
    assert result["best"]["sunAltitude"] <= -18
    json.dumps(result, allow_nan=False)


def test_invisible_south_pole_has_no_windows_from_north():
    result = plan_followup(0, -90, 40, -75, "2026-11-15")
    assert result["windows"] == []
    assert result["best"] is None
    assert all(row["airmass"] is None for row in result["samples"])


def test_every_window_sample_passes_both_constraints():
    result = plan_followup(88.8, 7.4, 19.8, -155.5, "2026-11-15", step_minutes=13)
    for row in result["samples"]:
        if row["observable"]:
            assert row["altitude"] >= 30
            assert row["sunAltitude"] <= -18
    for window in result["windows"]:
        selected = [r for r in result["samples"] if window["start"] <= r["time"] <= window["end"]]
        assert len(selected) == window["sampleCount"]
        assert all(r["observable"] for r in selected)
    assert result["samples"][-1]["time"].startswith("2026-11-16T00:00")


@pytest.mark.parametrize("key,value", [("ra", float("nan")), ("dec", 91), ("latitude", -91),
                                       ("longitude", 181), ("date", "today"), ("step_minutes", 0),
                                       ("step_minutes", 5.5), ("date", "1900-01-01")])
def test_rejects_invalid_coordinates_and_unbounded_grids(key, value):
    args = dict(ra=0, dec=0, latitude=0, longitude=0, date="2026-11-15")
    args[key] = value
    with pytest.raises(ValueError):
        plan_followup(**args)
