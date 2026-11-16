from science import archive, coverage


def test_real_wcs_index_covers_off_preset_barnard_field():
    ra, dec = 269.5862, 4.76883
    stopgap = archive.search(ra, dec, 5, 1, 4, indexed_only=True)
    assert stopgap["status"] == "recorded-metadata"
    assert stopgap["searchCoverage"]["complete"] is False
    assert stopgap["searchCoverage"]["liveCollections"] == []
    assert len(stopgap["observations"]) >= 2
    assert stopgap["observations"][-1]["mjd"] - stopgap["observations"][0]["mjd"] > 30
    assert all(o["metadataSource"] == "nasa-fits-header-index" for o in stopgap["observations"])
    assert all(len(o["fitsHeaderSha256"]) == 64 for o in stopgap["observations"])


def test_an_uncovered_index_position_is_an_incomplete_search():
    result = archive.search(4, -87, 5, 1, 4, indexed_only=True)
    assert result["observations"] == []
    assert not result["searchCoverage"]["complete"]


def test_index_does_not_use_fov_to_fabricate_coverage():
    matching, stamp = coverage.matching_records(133.795129, -7.245147, 1, {"dr1", "qr3"})
    assert stamp and matching
    assert all(coverage._on_image(row, 133.795129, -7.245147) for row in matching)
