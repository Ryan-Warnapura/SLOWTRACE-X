"""Vercel/FastAPI entry point. All science requests use official observation URLs."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, FiniteFloat

from science import archive
from science.planner import plan_followup

app = FastAPI(title="SLOWTRACE X science API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


def run(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except archive.ArchiveError as error:
        raise HTTPException(503, str(error)) from error
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(502, f"The scientific service could not complete this request ({type(error).__name__}). Please retry.") from error


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "SLOWTRACE X", "source": "NASA/IPAC IRSA SPHEREx DR1 + QR3", "version": "2.0.0"}


@app.get("/api/search")
def search(ra: float, dec: float, fov: float = 5, detector: int = 1, limit: int = 12):
    return run(archive.search, ra, dec, fov, detector, limit)


@app.get("/api/frame")
def frame(url: str, ra: float, dec: float, fov: float = 5, pixels: int = 96):
    return run(archive.frame, url, ra, dec, fov, pixels)


class FrameReference(BaseModel):
    url: str


class AnalysisRequest(BaseModel):
    ra: float
    dec: float
    fov: float = 5
    pixels: int = Field(96, ge=32, le=128)
    urls: list[str] = Field(default_factory=list, max_length=8)
    observations: list[FrameReference] = Field(default_factory=list, max_length=8)
    threshold: float = Field(5.0, ge=3, le=12)
    velocities: list[tuple[float, float]] | None = Field(None, max_length=49)
    psfSigma: float = Field(1.0, ge=0.6, le=2)
    seed: int = Field(42, ge=0, le=2147483647)
    trials: int = Field(8, ge=2, le=16)
    injectedSnr: float = Field(3.0, ge=0.5, le=15)
    motion: tuple[float, float] = (0.02, 0.0)


def _analysis(request, experiment=False):
    from science.analysis import analyze_stack, compatible_subset, experiment as perform_experiment
    urls = request.urls or [x.url for x in request.observations]
    if len(urls) < 2 or len(urls) > 8 or len(set(urls)) != len(urls):
        raise ValueError("Select 2–8 distinct exposures for analysis.")
    archive.checked_position(request.ra, request.dec, request.fov)
    for url in urls:
        archive.validate_url(url)
    frames, failures = [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = [pool.submit(archive.frame, url, request.ra, request.dec, request.fov, request.pixels) for url in urls]
        for url, future in zip(urls, pending):
            try:
                frames.append(future.result())
            except archive.ArchiveError as error:
                failures.append({"url": url, "reason": str(error)})
    if len(frames) < 2:
        raise archive.ArchiveError("Fewer than two of the requested NASA exposures could be loaded. Retry the analysis after more frames are available.")
    shape = (request.pixels, request.pixels)
    values = np.array([np.array(f["data"], float).reshape(shape) for f in frames])
    variances = np.array([np.array(f["variance"], float).reshape(shape) for f in frames])
    flags = np.array([np.array(f["mask"], np.int64).reshape(shape) for f in frames])
    meta = [f["metadata"] for f in frames]
    mask_bits = np.array([m.get("maskBits", archive.MASK_BITS) for m in meta], np.int64)[:, None, None]
    bad = ~np.isfinite(values) | ((flags & mask_bits) != 0)
    bands = np.array([m.get("wavelengthCenter") for m in meta], float)
    detectors = np.array([m["detector"] for m in meta])
    groups = {}
    for i, item in enumerate(meta):
        key = (item["unit"], item["zodiSubtracted"], item.get("calibrationVersion"))
        groups.setdefault(key, []).append(i)
    comparable = []
    for group in groups.values():
        chosen = [group[i] for i in compatible_subset(bands[group], detectors[group])]
        if chosen:
            span = max(meta[i]["mjd"] for i in chosen) - min(meta[i]["mjd"] for i in chosen)
            comparable.append((len(chosen), span, group))
    if not comparable or max(comparable)[0] < 2:
        raise ValueError("The loaded images do not contain two exposures with comparable wavelength, detector, calibration and background processing.")
    _, _, group = max(comparable)
    bands[[i for i in range(len(meta)) if i not in group]] = np.nan
    args = (values, variances, bad, np.array([m["mjd"] for m in meta]))
    kwargs = dict(pixel_arcsec=meta[0]["pixelArcsec"], wavelengths_um=bands,
                  detector_ids=detectors, velocities_arcsec_day=request.velocities,
                  threshold_snr=request.threshold, psf_sigma_pixels=request.psfSigma)
    if experiment:
        result = perform_experiment(*args, **kwargs, seed=request.seed, trials=request.trials,
                                    injected_snr=request.injectedSnr, motion_arcsec_day=request.motion)
    else:
        result = analyze_stack(*args, **kwargs)
    result["observationProvenance"] = [f["provenance"] for f in frames]
    result["observationMetadata"] = meta
    result["retrievalFailures"] = failures
    result["request"] = request.model_dump()
    result["notes"].append("Analysis selects observations with matching units, zodiacal-light processing and calibration version before the approximate wavelength comparison.")
    if failures:
        result["notes"].append(f"The archive could not reload {len(failures)} requested image(s). This calculation uses the images that loaded and records the failures in the export.")
    return result


@app.post("/api/analyze")
def analyze(request: AnalysisRequest):
    return run(_analysis, request)


@app.post("/api/experiment")
def experiment(request: AnalysisRequest):
    return run(_analysis, request, experiment=True)


class CatalogEpoch(BaseModel):
    ra: FiniteFloat = Field(ge=0, lt=360)
    dec: FiniteFloat = Field(ge=-90, le=90)
    mjd: FiniteFloat = Field(ge=50000, le=70000)
    positionKind: Literal["predicted-track", "reference-position", "measured-centroid"] = "predicted-track"
    valid: bool | None = None
    usable: bool | None = None
    observationId: str | None = Field(None, max_length=100)


class CatalogEvidence(BaseModel):
    epochMeasurements: list[CatalogEpoch] = Field(default_factory=list, max_length=8)
    nominalSnr: FiniteFloat | None = None
    snrGainOverStatic: FiniteFloat | None = None


class CatalogRequest(BaseModel):
    ra: FiniteFloat = Field(ge=0, lt=360)
    dec: FiniteFloat = Field(ge=-90, le=90)
    referenceMjd: FiniteFloat = Field(ge=50000, le=70000)
    evidence: CatalogEvidence = Field(default_factory=CatalogEvidence)


@app.post("/api/investigate")
def investigate(request: CatalogRequest):
    from science.catalogs import investigate as check_catalogs

    candidate = request.model_dump(exclude_none=True)
    for point in candidate["evidence"]["epochMeasurements"]:
        # Browser-submitted positions are provisional. Archive-signed measurements
        # and validated observer axes are required for an independent identification.
        if point["positionKind"] == "measured-centroid":
            point["positionKind"] = "predicted-track"
    return run(check_catalogs, candidate)


class PlanRequest(BaseModel):
    ra: float
    dec: float
    latitude: float
    longitude: float
    date: str
    elevation_m: float = 0
    min_altitude: float = 30
    max_sun_altitude: float = -18
    step_minutes: int = 20


@app.post("/api/plan")
@app.post("/api/planner")
def plan(request: PlanRequest):
    return run(plan_followup, **request.model_dump())
