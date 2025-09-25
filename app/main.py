import logging, os
from typing import Dict, List

import numpy as np
from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram
from .model_io import load_model
from .drift import get_drift_detector
from .gitlab_client import GitLabTriggerError, trigger_gitlab_pipeline

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
    "inference_requests_total", "Total inference requests", ["app"]
)
DRIFT_COUNTER = Counter("drift_events_total", "Total drift events", ["app"])
LATENCY_HIST = Histogram("inference_latency_seconds", "Inference latency", ["app"])

app = FastAPI(title=APP_NAME)
Instrumentator().instrument(app).expose(app)  # /metrics

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
    if not GITLAB_TRIGGER_ENABLED:
        return
    if not (GITLAB_PROJECT_ID and GITLAB_TRIGGER_TOKEN):
        logger.error("Drift detected but GitLab trigger is not fully configured.")
        return
    background_tasks.add_task(_trigger_retrain_background)
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
