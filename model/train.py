"""Training pipeline for the FastAPI inference service."""

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, Tuple

import joblib
import numpy as np
from sklearn.datasets import load_breast_cancer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

LOGGER = logging.getLogger("aiops-quality-project.train")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "model.pkl"
REFERENCE_DATA_PATH = ARTIFACT_DIR / "reference.npy"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"


def load_dataset(
    test_size: float, random_state: int
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    dataset = load_breast_cancer()
    X_train, X_test, y_train, y_test = train_test_split(
        dataset.data,
        dataset.target,
        test_size=test_size,
        stratify=dataset.target,
        random_state=random_state,
    )
    LOGGER.info("Dataset loaded: train=%s test=%s", X_train.shape, X_test.shape)
    return X_train, X_test, y_train, y_test


def build_and_train_model(
    X_train: np.ndarray, y_train: np.ndarray
) -> Tuple[LogisticRegression, StandardScaler]:
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_train)
    model = LogisticRegression(max_iter=500)
    model.fit(X_scaled, y_train)
    LOGGER.info("Model training completed")
    return model, scaler


def evaluate_model(
    model: LogisticRegression,
    scaler: StandardScaler,
    X_test: np.ndarray,
    y_test: np.ndarray,
) -> Dict[str, Dict[str, float]]:
    predictions = model.predict(scaler.transform(X_test))
    report = classification_report(y_test, predictions, output_dict=True)
    LOGGER.info("Classification report: %s", json.dumps(report, indent=2))
    return report


def persist_artifacts(
    model: LogisticRegression,
    scaler: StandardScaler,
    reference_data: np.ndarray,
    metrics: Dict[str, Dict[str, float]],
) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "scaler": scaler}, MODEL_PATH)
    np.save(REFERENCE_DATA_PATH, reference_data)
    with METRICS_PATH.open("w", encoding="utf-8") as fp:
        json.dump(metrics, fp, indent=2)
    LOGGER.info("Artifacts stored under %s", ARTIFACT_DIR)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the classification model")
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Fraction of samples for evaluation",
    )
    parser.add_argument(
        "--random-state", type=int, default=42, help="Random seed for reproducibility"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    X_train, X_test, y_train, y_test = load_dataset(args.test_size, args.random_state)
    model, scaler = build_and_train_model(X_train, y_train)
    metrics = evaluate_model(model, scaler, X_test, y_test)
    persist_artifacts(model, scaler, scaler.transform(X_train), metrics)


if __name__ == "__main__":
    main()
