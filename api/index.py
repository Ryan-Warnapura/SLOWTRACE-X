"""Vercel/FastAPI entry point. All science requests use official observation URLs."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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
    return {"status": "ok", "service": "SLOWTRACE X", "source": "NASA/IPAC IRSA SPHEREx DR1 + QR3", "version": "1.0.0"}


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
    from science.analysis import analyze_stack, experiment as perform_experiment
    urls = request.urls or [x.url for x in request.observations]
    if len(urls) < 2 or len(urls) > 8 or len(set(urls)) != len(urls):
        raise ValueError("Select 2–8 distinct exposures for analysis.")
    archive.checked_position(request.ra, request.dec, request.fov)
    for url in urls:
        archive.validate_url(url)
    with ThreadPoolExecutor(max_workers=3) as pool:
        frames = list(pool.map(lambda url: archive.frame(url, request.ra, request.dec, request.fov, request.pixels), urls))
    shape = (request.pixels, request.pixels)
    values = np.array([np.array(f["data"], float).reshape(shape) for f in frames])
    variances = np.array([np.array(f["variance"], float).reshape(shape) for f in frames])
    flags = np.array([np.array(f["mask"], np.int64).reshape(shape) for f in frames])
    bad = ~np.isfinite(values) | ((flags & archive.MASK_BITS) != 0)
    meta = [f["metadata"] for f in frames]
    args = (values, variances, bad, np.array([m["mjd"] for m in meta]))
    kwargs = dict(pixel_arcsec=meta[0]["pixelArcsec"], wavelengths_um=np.array([m["wavelengthCenter"] for m in meta], float),
                  detector_ids=np.array([m["detector"] for m in meta]), velocities_arcsec_day=request.velocities,
                  threshold_snr=request.threshold, psf_sigma_pixels=request.psfSigma)
    if experiment:
        result = perform_experiment(*args, **kwargs, seed=request.seed, trials=request.trials,
                                    injected_snr=request.injectedSnr, motion_arcsec_day=request.motion)
    else:
        result = analyze_stack(*args, **kwargs)
    result["observationProvenance"] = [f["provenance"] for f in frames]
    result["observationMetadata"] = meta
    result["request"] = request.model_dump()
    return result


@app.post("/api/analyze")
def analyze(request: AnalysisRequest):
    return run(_analysis, request)


@app.post("/api/experiment")
def experiment(request: AnalysisRequest):
    return run(_analysis, request, experiment=True)


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
