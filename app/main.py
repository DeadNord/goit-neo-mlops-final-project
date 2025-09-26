import logging, os
from typing import Dict, List

import numpy as np
from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram, REGISTRY
from .model_io import load_model
from .drift import get_drift_detector
from .gitlab_client import GitLabTriggerError, trigger_gitlab_pipeline

import time
import threading

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("inference")

APP_NAME = os.getenv("APP_NAME", "aiops-quality-service")
ENABLE_DRIFT = os.getenv("ENABLE_DRIFT", "true").lower() == "true"
GITLAB_TRIGGER_ENABLED = os.getenv("GITLAB_TRIGGER_ENABLED", "false").lower() == "true"
GITLAB_BASE_URL = os.getenv("GITLAB_BASE_URL", "https://gitlab.com")
GITLAB_PROJECT_ID = os.getenv("GITLAB_PROJECT_ID")
GITLAB_TRIGGER_TOKEN = os.getenv("GITLAB_TRIGGER_TOKEN")
GITLAB_TRIGGER_REF = os.getenv("GITLAB_TRIGGER_REF", "main")
GITLAB_TRIGGER_TIMEOUT = int(os.getenv("GITLAB_TRIGGER_TIMEOUT", "10"))

# Минимальный интервал между автозапусками retrain в секундах
MIN_RETRAIN_INTERVAL = int(os.getenv("MIN_RETRAIN_INTERVAL_SECONDS", "300"))

_last_trigger_ts = 0.0
_trigger_lock = threading.Lock()
_trigger_in_flight = False


def _parse_variables(raw: str) -> Dict[str, str]:
    variables: Dict[str, str] = {}
    if not raw:
        return variables
    for pair in raw.split(","):
        key, sep, value = pair.partition("=")
        if not sep:
            logger.warning("Ignoring malformed GitLab trigger variable: '%s'", pair)
            continue
        variables[key.strip()] = value.strip()
    return variables


GITLAB_TRIGGER_VARIABLES = _parse_variables(os.getenv("GITLAB_TRIGGER_VARIABLES", ""))

if GITLAB_TRIGGER_ENABLED and not (GITLAB_PROJECT_ID and GITLAB_TRIGGER_TOKEN):
    logger.warning(
        "GitLab trigger is enabled but project ID or trigger token is missing."
    )

REQUESTS_COUNTER = Counter(
    "inference_requests_total",
    "Total inference requests",
    ["app"],
    registry=REGISTRY,
)
DRIFT_COUNTER = Counter(
    "drift_events_total", "Total drift events", ["app"], registry=REGISTRY
)
LATENCY_HIST = Histogram(
    "inference_latency_seconds",
    "Inference latency",
    ["app"],
    registry=REGISTRY,
)

# Pre-initialize metric series so they are visible in Prometheus/Grafana dashboards
# even before any inference requests are processed.
REQUESTS_COUNTER.labels(app=APP_NAME)
DRIFT_COUNTER.labels(app=APP_NAME)
LATENCY_HIST.labels(app=APP_NAME)

app = FastAPI(title=APP_NAME)
Instrumentator(registry=REGISTRY).instrument(app).expose(app)  # /metrics

model = load_model()
detector = get_drift_detector() if ENABLE_DRIFT else None


class PredictRequest(BaseModel):
    values: List[float]


class PredictResponse(BaseModel):
    prediction: int
    drift: bool = False


@app.on_event("startup")
async def _startup():
    logger.info("Model loaded. Drift detector: %s", "on" if detector else "off")
    if GITLAB_TRIGGER_ENABLED:
        logger.info(
            "GitLab retrain trigger enabled for project=%s ref=%s",
            GITLAB_PROJECT_ID,
            GITLAB_TRIGGER_REF,
        )
    else:
        logger.info("GitLab retrain trigger disabled")


@app.get("/health")
def health():
    return {"status": "ok"}


def _trigger_retrain_background():
    try:
        trigger_gitlab_pipeline(
            base_url=GITLAB_BASE_URL,
            project=GITLAB_PROJECT_ID,
            token=GITLAB_TRIGGER_TOKEN,
            ref=GITLAB_TRIGGER_REF,
            variables=GITLAB_TRIGGER_VARIABLES,
            timeout=GITLAB_TRIGGER_TIMEOUT,
        )
    except (GitLabTriggerError, Exception) as exc:  # pragma: no cover - background task
        logger.exception("Failed to trigger GitLab retrain pipeline: %s", exc)


def _schedule_retrain(background_tasks: BackgroundTasks):
    global _last_trigger_ts, _trigger_in_flight

    if not GITLAB_TRIGGER_ENABLED:
        return
    if not (GITLAB_PROJECT_ID and GITLAB_TRIGGER_TOKEN):
        logger.error("Drift detected but GitLab trigger is not fully configured.")
        return

    now = time.monotonic()
    with _trigger_lock:
        # Ограничение по частоте
        if now - _last_trigger_ts < MIN_RETRAIN_INTERVAL:
            logger.info(
                "Drift detected but cooldown not passed (%.0fs left). Skipping trigger.",
                MIN_RETRAIN_INTERVAL - (now - _last_trigger_ts),
            )
            return
        # Не запускать несколько одновременно
        if _trigger_in_flight:
            logger.info("Drift detected but trigger already in flight. Skipping.")
            return

        _trigger_in_flight = True
        _last_trigger_ts = now

    def _wrapped():
        global _trigger_in_flight
        try:
            _trigger_retrain_background()
        finally:
            with _trigger_lock:
                _trigger_in_flight = False

    background_tasks.add_task(_wrapped)
    logger.info("Drift detected → scheduled GitLab retrain pipeline trigger.")


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest, background_tasks: BackgroundTasks):
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
                _schedule_retrain(background_tasks)

        logger.info("Prediction: %s | drift=%s", pred, drift_flag)
        return PredictResponse(prediction=pred, drift=drift_flag)
