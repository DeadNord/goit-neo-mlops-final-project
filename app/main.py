"""FastAPI inference service with drift detection and metrics."""

import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

try:
    from alibi_detect.cd import MMDDrift
except (
    ImportError
) as exc:  # pragma: no cover - guard rail for runtime envs without alibi-detect
    raise RuntimeError(
        "alibi-detect must be installed to run the drift detector."
    ) from exc

BASE_DIR = Path(__file__).resolve().parent.parent

LOGGER = logging.getLogger("aiops-quality-project")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

MODEL_PATH = Path(os.getenv("MODEL_PATH", str(BASE_DIR / "model/artifacts/model.pkl")))
REFERENCE_DATA_PATH = Path(
    os.getenv("REFERENCE_DATA_PATH", str(BASE_DIR / "model/artifacts/reference.npy"))
)
DRIFT_P_THRESHOLD = float(os.getenv("DRIFT_P_THRESHOLD", 0.05))
PIPELINE_TRIGGER_URL = os.getenv("GITLAB_RETRAIN_TRIGGER_URL")
PIPELINE_TRIGGER_TOKEN = os.getenv("GITLAB_RETRAIN_TRIGGER_TOKEN")
PIPELINE_REF = os.getenv("GITLAB_RETRAIN_REF", "main")

PREDICTION_COUNTER = Counter(
    "model_predictions_total",
    "Number of prediction requests processed",
)
PREDICTION_LATENCY = Histogram(
    "model_prediction_seconds",
    "Latency of prediction requests in seconds",
)
DRIFT_COUNTER = Counter(
    "model_drift_events_total",
    "Number of detected data drift events",
)
LATEST_DRIFT_SCORE = Gauge(
    "model_latest_drift_score",
    "Latest drift score returned by the detector",
)


class PredictionRequest(BaseModel):
    """Schema for prediction input."""

    features: List[float]


class PredictionResponse(BaseModel):
    """Schema for prediction response."""

    prediction: float
    drift_detected: bool
    drift_score: Optional[float] = None


def load_model(model_path: Path) -> Dict[str, Any]:
    """Load the serialized model and scaler artifacts."""
    if not model_path.exists():
        raise FileNotFoundError(f"Model artifact not found at {model_path}")
    LOGGER.info("Loading model from %s", model_path)
    artifact = joblib.load(model_path)
    if not {"model", "scaler"}.issubset(set(artifact.keys())):
        raise ValueError("Model artifact must contain 'model' and 'scaler' keys")
    return artifact


def load_reference_data(reference_path: Path) -> np.ndarray:
    if not reference_path.exists():
        raise FileNotFoundError(f"Reference data not found at {reference_path}")
    LOGGER.info("Loading drift reference data from %s", reference_path)
    return np.load(reference_path)


@lru_cache(maxsize=1)
def get_model() -> Dict[str, Any]:
    return load_model(MODEL_PATH)


@lru_cache(maxsize=1)
def get_drift_detector() -> MMDDrift:
    reference = load_reference_data(REFERENCE_DATA_PATH)
    return MMDDrift(reference, p_val=DRIFT_P_THRESHOLD)


def predict(features: List[float]) -> float:
    """Return the model prediction for the provided feature list."""
    artifact = get_model()
    model = artifact["model"]
    scaler = artifact["scaler"]
    data = np.array(features, dtype=float).reshape(1, -1)
    transformed = scaler.transform(data)
    LOGGER.debug("Running inference on data: %s", data)
    proba = getattr(model, "predict_proba", None)
    if proba is not None:
        prediction = float(proba(transformed)[0, 1])
    else:
        prediction = float(model.predict(transformed)[0])
    LOGGER.info("Prediction computed: %s", prediction)
    return prediction


def detect_drift(features: List[float]) -> Dict[str, Any]:
    artifact = get_model()
    scaler = artifact["scaler"]
    detector = get_drift_detector()
    sample = scaler.transform(np.array(features, dtype=float).reshape(1, -1))
    result = detector.predict(sample)
    drift_score = result["data"].get("p_val", 1.0)
    is_drift = bool(result["data"]["is_drift"])
    LOGGER.info("Drift detection result: drift=%s, p_value=%.4f", is_drift, drift_score)
    LATEST_DRIFT_SCORE.set(drift_score)
    if is_drift:
        DRIFT_COUNTER.inc()
    return {"is_drift": is_drift, "score": drift_score, "raw": result}


def trigger_retrain_if_needed(drift_result: Dict[str, Any]) -> None:
    if not drift_result["is_drift"]:
        return

    if PIPELINE_TRIGGER_URL and PIPELINE_TRIGGER_TOKEN:
        try:
            LOGGER.info(
                "Triggering GitLab retrain pipeline at %s", PIPELINE_TRIGGER_URL
            )
            payload = {
                "token": PIPELINE_TRIGGER_TOKEN,
                "ref": PIPELINE_REF,
                "variables": {
                    "DRIFT_PAYLOAD": json.dumps(drift_result["raw"], default=str),
                },
            }
            response = requests.post(PIPELINE_TRIGGER_URL, data=payload, timeout=10)
            response.raise_for_status()
            LOGGER.info("GitLab pipeline trigger response: %s", response.text)
        except requests.RequestException as exc:  # pragma: no cover - runtime logging
            LOGGER.exception("Failed to trigger GitLab retrain pipeline: %s", exc)
    else:
        LOGGER.warning(
            "Drift detected but pipeline trigger env vars are not configured"
        )


app = FastAPI(title="AIOps Quality Inference Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    # Trigger lazy loaders to fail-fast if artifacts are missing
    try:
        get_model()
        get_drift_detector()
    except FileNotFoundError as exc:
        LOGGER.error("Startup failed: %s", exc)
        raise


@app.get("/healthz")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/predict", response_model=PredictionResponse)
async def predict_endpoint(payload: PredictionRequest) -> JSONResponse:
    LOGGER.info("Received prediction request: %s", payload.features)
    start = time.perf_counter()
    try:
        prediction = predict(payload.features)
    except Exception as exc:  # pragma: no cover - runtime safety
        LOGGER.exception("Failed to generate prediction: %s", exc)
        raise HTTPException(
            status_code=500, detail="Failed to generate prediction"
        ) from exc

    drift_result = detect_drift(payload.features)
    trigger_retrain_if_needed(drift_result)

    duration = time.perf_counter() - start
    PREDICTION_COUNTER.inc()
    PREDICTION_LATENCY.observe(duration)
    LOGGER.info(
        "Request processed in %.4fs, prediction=%s, drift=%s",
        duration,
        prediction,
        drift_result["is_drift"],
    )

    response = PredictionResponse(
        prediction=prediction,
        drift_detected=drift_result["is_drift"],
        drift_score=drift_result["score"],
    )
    return JSONResponse(status_code=200, content=json.loads(response.json()))


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
