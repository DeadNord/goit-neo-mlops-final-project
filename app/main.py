import logging, os
from typing import List
import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram
from .model_io import load_model
from .drift import get_drift_detector

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("inference")

APP_NAME = os.getenv("APP_NAME", "aiops-quality-service")
ENABLE_DRIFT = os.getenv("ENABLE_DRIFT", "true").lower() == "true"

REQUESTS_COUNTER = Counter("inference_requests_total", "Total inference requests", ["app"])
DRIFT_COUNTER = Counter("drift_events_total", "Total drift events", ["app"])
LATENCY_HIST = Histogram("inference_latency_seconds", "Inference latency", ["app"])

app = FastAPI(title=APP_NAME)
model = load_model()
detector = get_drift_detector() if ENABLE_DRIFT else None

class PredictRequest(BaseModel):
    values: List[float]

class PredictResponse(BaseModel):
    prediction: int
    drift: bool = False

@app.on_event("startup")
async def _startup():
    Instrumentator().instrument(app).expose(app)  # /metrics
    logger.info("Model loaded. Drift detector: %s", "on" if detector else "off")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    REQUESTS_COUNTER.labels(app=APP_NAME).inc()
    with LATENCY_HIST.labels(app=APP_NAME).time():
        x = np.array(req.values).reshape(-1, 1)
        logger.info("Incoming data: %s", req.values)
        y = model.predict(x)
        pred = int(y[0])

        drift_flag = False
        if detector:
            drift_flag = detector.check(x.flatten())
            if drift_flag:
                DRIFT_COUNTER.labels(app=APP_NAME).inc()
                print("Drift detected")

        logger.info("Prediction: %s | drift=%s", pred, drift_flag)
        return PredictResponse(prediction=pred, drift=drift_flag)
