import json
import math

import numpy as np
import pytest

from science import catalogs


def test_gaia_pm_ra_is_tangent_plane_component_and_wraps():
    row = dict(ra=359.999, dec=60, ref_epoch=2016, pmra=3600, pmdec=0, parallax=0)
    ra, dec, motion, parallax = catalogs._gaia_prediction(row, 2020, np.zeros(3))
    # 3.6 arcsec/year east at Dec 60° is 7.2 arcsec/year in RA coordinates.
    assert ra == pytest.approx(.007, abs=1e-8)
    # An eastward tangent vector has a small second-order change in declination.
    displacement = math.radians(14.4 / 3600)
    expected_dec = math.degrees(math.asin(math.sin(math.radians(60)) / math.hypot(1, displacement)))
    assert dec == pytest.approx(expected_dec, abs=1e-9)
    assert motion and not parallax


def test_gaia_single_row_keeps_exact_identifier_and_empty_is_valid():
    table = b"source_id,ra,dec,ref_epoch,pmra,pmdec\n4472832130942575872,269.45,4.74,2016,-801.55,10362.39\n"
    rows, truncated = catalogs._gaia_rows(table)
    assert not truncated
    assert rows[0]["source_id"] == "4472832130942575872"
    assert catalogs._gaia_rows(table.splitlines()[0])[0] == []
    with pytest.raises(catalogs.CatalogError):
        catalogs._gaia_rows(b"<html>502 Upstream Error</html>")


def test_unknown_spacecraft_axes_are_not_passed_as_icrf():
    point = dict(ra=20, dec=-7, mjd=60914.2,
                 observerState=dict(positionKm=[-3000, -6300, -400], velocityKmS=[-.7, .8, -7.4],
                                    frame=None, origin="GEOCENTER"))
    unknown = catalogs._parse_epoch(point)
    params, label = catalogs._sb_params(unknown, .12)
    assert "xobs" not in params and label.startswith("Earth surface proxy")
    assert unknown.observer_radius_km == pytest.approx(6989.277501)
    point["observerState"]["frame"] = "ICRF"
    known = catalogs._parse_epoch(point)
    params, _ = catalogs._sb_params(known, .12)
    assert len(params["xobs"].split(",")) == 6
    assert params["fov-dec-center"].startswith("M07")


def test_sbident_parser_distinguishes_empty_results_and_errors():
    signature = {"source": "NASA/JPL Small-Body Identification API", "version": "1.1"}
    fields = ["Object name", "Astrometric RA (hh:mm:ss)", "Astrometric Dec (dd mm'ss\")", "Visual magnitude (V)"]
    table = dict(signature=signature, fields_first=fields, n_first_pass=1,
                 data_first_pass=[["1 Ceres (A801 AA)", "01:20:02", "-07 04'30\"", "8.17"]])
    rows, count = catalogs._sb_rows(json.dumps(table).encode())
    assert count == 1
    assert rows[0]["ra"] == pytest.approx(20.0083333333)
    assert rows[0]["dec"] == -7.075
    assert catalogs._sb_rows(json.dumps(dict(signature=signature, n_first_pass=0)).encode()) == ([], 0)
    with pytest.raises(catalogs.CatalogError):
        catalogs._sb_rows(b'{"message":"Database unavailable"}')


def test_horizons_exact_times_and_unknown_axis_bound(monkeypatch):
    ephemeris = """Target body name: 1 Ceres (A801 AA) {source: JPL}
$$SOE
2460914.713196455, , , 20.00567,-7.07719,2.14171054935760,-15.7395018,
$$EOE"""
    monkeypatch.setattr(catalogs, "_fetch", lambda *args, **kwargs: json.dumps({"result": ephemeris}).encode())
    epoch = catalogs.Epoch(20.00567, -7.07719, 60914.213196455, observer_radius_km=7025)
    result = catalogs._refine_horizons("1 Ceres (A801 AA)", [epoch], 10.0)
    assert result["status"] == "ok"
    assert result["horizonsName"] == "1 Ceres (A801 AA)"
    assert result["samples"][0]["observer"] == "Earth geocenter"
    assert result["samples"][0]["observerOffsetUpperBoundArcsec"] == pytest.approx(4.5225, abs=.01)
    assert result["samples"][0]["observerRobust"] is True
    shifted = catalogs.Epoch(20.00567, -7.07719, 60914.2132 + 1)
    assert catalogs._refine_horizons("1 Ceres (A801 AA)", [shifted], 10.0)["status"] == "unavailable"


def test_trial_matches_cannot_become_automated_identifications():
    epochs = [catalogs.Epoch(20.0, -7.07, date) for date in [60914., 60916.]]
    gaia = dict(status="ok", matches=[dict(name="Gaia DR3 42", withinTolerance=2, properMotionApplied=True)])
    jpl = dict(status="ok", horizons=[])
    cls, reasons, _, details = catalogs._interpret(epochs, {}, gaia, jpl)
    assert cls == "insufficient-evidence"
    assert details["independentMeasuredEpochs"] == 0
    assert "provisional" in " ".join(reasons)


def test_missing_catalogs_are_not_unidentified_and_two_measured_epochs_can_be_consistent():
    epochs = [catalogs.Epoch(20., -7.07, date, kind="measured-centroid", observation_id=f"exp{date}", uncertainty_arcsec=2)
              for date in [60914., 60918.]]
    no_gaia = dict(status="ok", matches=[])
    jpl = dict(status="unavailable", horizons=[])
    assert catalogs._interpret(epochs, {}, no_gaia, jpl)[0] == "insufficient-evidence"
    gaia = dict(status="ok", matches=[dict(name="Gaia DR3 42", withinTolerance=2, properMotionApplied=True)])
    jpl["status"] = "ok"
    assert catalogs._interpret(epochs, {}, gaia, jpl)[0] == "catalog-consistent"
    assert catalogs._interpret(epochs, {}, no_gaia, jpl)[0] == "unidentified"


def test_input_epoch_validation_before_network(monkeypatch):
    def no_request(*args, **kwargs):
        pytest.fail("Invalid input reached the catalog provider")
    monkeypatch.setattr(catalogs, "_fetch", no_request)
    with pytest.raises(ValueError, match="RA"):
        catalogs.investigate(dict(ra=1000, dec=-7., referenceMjd=60914.))
    with pytest.raises(ValueError, match="one and eight"):
        catalogs.investigate(dict(evidence={"epochMeasurements": [{}] * 9}))
