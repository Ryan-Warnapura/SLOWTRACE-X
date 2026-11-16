import hashlib
import io
from types import SimpleNamespace

import numpy as np
import pytest
import requests
from astropy.io import fits
from astropy.wcs import WCS

from science import survey_image
from science.archive import MISSING


SOURCE = (
    "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/level2/2025W20_2D/"
    "l2b-v27-2026-198/2/level2_2025W20_2D_0176_4D2_spx_l2b-v27-2026-198.fits"
)
OBSERVATION_ID = "2025W20_2D_0176_4"


def fixture_bytes(*, compressed=False, all_masked=False):
    """Artificial FITS exercise of native sizes, flags, variance and sky wrap."""
    shape = (48, 64)
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.radesys = "ICRS"
    wcs.wcs.crpix = [32.5, 24.5]
    wcs.wcs.crval = [359.95, 12]
    wcs.wcs.cdelt = [-0.02, 0.02]
    header = wcs.to_header()
    header["OBSID"] = OBSERVATION_ID
    header["DETECTOR"] = 2
    header["MJD-BEG"], header["MJD-AVG"], header["MJD-END"] = 60800, 60800.001, 60800.002
    header["BUNIT"] = "MJy / sr"
    intensity = np.full(shape, 10, dtype=np.float32)
    variance = np.full(shape, 4, dtype=np.float32)
    flags = np.zeros(shape, dtype=np.int32)
    flags[:, : (64 if all_masked else 32)] = MISSING
    variance[0, 32] = 0
    intensity[0, 33] = np.nan
    hdu = fits.CompImageHDU if compressed else fits.ImageHDU
    stream = io.BytesIO()
    fits.HDUList([
        fits.PrimaryHDU(),
        hdu(intensity, header, name="IMAGE"),
        hdu(variance, name="VARIANCE"),
        hdu(flags, name="FLAGS"),
        hdu(np.full(shape, 2, dtype=np.float32), name="ZODI"),
    ]).writeto(stream)
    return stream.getvalue()


class PayloadResponse:
    def __init__(self, raw, status=200):
        self.raw = raw
        self.status_code = status
        self.headers = {"Content-Length": str(len(raw)), "ETag": '"test-product"'}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        for start in range(0, len(self.raw), chunk_size):
            yield self.raw[start : start + chunk_size]


def patch_response(monkeypatch, raw, status=200):
    monkeypatch.setattr(survey_image, "_session", lambda: SimpleNamespace(
        get=lambda *args, **kwargs: PayloadResponse(raw, status),
    ))


@pytest.mark.parametrize("compressed", (False, True))
def test_native_science_processing(tmp_path, monkeypatch, compressed):
    raw = fixture_bytes(compressed=compressed)
    patch_response(monkeypatch, raw)
    monkeypatch.setattr(survey_image.tempfile, "tempdir", str(tmp_path))

    result = survey_image.process_image(SOURCE, f"{OBSERVATION_ID}D2", 2)

    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["downloadedBytes"] == len(raw)
    assert result["totalPixels"] == 64 * 48
    assert result["validPixels"] == 32 * 48 - 2
    assert result["zodiSubtracted"]
    assert result["brightnessQuantiles"]["median"] == pytest.approx(8)
    assert result["medianPixelVariance"] == pytest.approx(4)
    assert result["flagPixelCounts"] == {"MISSING_DATA": 32 * 48}
    assert result["wcs"]["NAXIS1"] == 64
    assert result["center"]["ra"] == pytest.approx(359.95)
    assert min(point["ra"] for point in result["boundary"]) < 1
    assert max(point["ra"] for point in result["boundary"]) > 359
    ranges = result["coverageRanges"]
    assert all(start < end for start, end in ranges)
    assert all(previous[1] < following[0] for previous, following in zip(ranges, ranges[1:]))
    sampled_area = sum(end - start for start, end in ranges) * 129600 / (np.pi * 12 * 1024**2)
    assert 0.52 < sampled_area < 0.71  # half the 1.28 × .96 deg native TAN rectangle
    assert list(tmp_path.iterdir()) == []


def test_fully_masked_product_is_rejected(monkeypatch):
    patch_response(monkeypatch, fixture_bytes(all_masked=True))
    with pytest.raises(survey_image.ImageRejected, match="No usable native science pixels"):
        survey_image.process_image(SOURCE, f"{OBSERVATION_ID}D2", 2)


def test_identity_is_checked_before_download(monkeypatch):
    def refuse_download():
        pytest.fail("wrong archive identity must not reach the network")

    monkeypatch.setattr(survey_image, "_session", refuse_download)
    with pytest.raises(survey_image.ImageRejected, match="Expected observation identity"):
        survey_image.process_image(SOURCE, f"{OBSERVATION_ID}D3", 3)


def test_partial_transfer_retryable(monkeypatch):
    patch_response(monkeypatch, b"partial object", 206)
    with pytest.raises(requests.RequestException, match="full FITS response"):
        survey_image.process_image(SOURCE, f"{OBSERVATION_ID}D2", 2)
