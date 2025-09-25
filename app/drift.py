"""Drift detection utilities powered by Alibi Detect."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
from alibi_detect.cd import KSDrift

logger = logging.getLogger(__name__)


DEFAULT_REF_PATH = Path(os.getenv("DRIFT_REF_PATH", "/model/reference_data.npy"))
DEFAULT_P_VAL = float(os.getenv("DRIFT_P_VALUE", "0.05"))


class AlibiKSDetector:
    """Wraps :class:`alibi_detect.cd.ks.KSDrift` for simple boolean checks."""

    def __init__(self, reference: np.ndarray, p_val: float = DEFAULT_P_VAL):
        if reference.ndim != 1:
            reference = reference.reshape(-1)
        self._reference = reference.astype("float32")
        self._detector = KSDrift(self._reference, p_val=p_val)
        self._p_val = p_val

    def check(self, x: np.ndarray) -> bool:
        """Return ``True`` if drift is detected for ``x``."""

        sample = np.asarray(x, dtype="float32").reshape(-1)
        result = self._detector.predict(sample, return_p_val=True, return_distance=True)
        drift = bool(result["data"]["is_drift"])

        if drift:
            p_val = result["data"].get("p_val", None)
            distance = result["data"].get("distance", None)
            logger.warning(
                "Drift detected by KSDrift: p_val=%s distance=%s threshold=%s",
                p_val,
                distance,
                self._p_val,
            )
        else:
            logger.debug(
                "No drift detected. p_val=%s threshold=%s",
                result["data"].get("p_val"),
                self._p_val,
            )

        return drift


def _load_reference(path: Path) -> np.ndarray:
    if path.exists():
        logger.info("Loading drift reference data from %s", path)
        return np.load(path)

    logger.warning(
        "Drift reference data not found at %s. Generating synthetic baseline.", path
    )
    rng = np.random.default_rng(42)
    return rng.normal(loc=0.0, scale=1.0, size=512).astype("float32")


def get_drift_detector(
    path: Optional[Path] = None, p_val: Optional[float] = None
) -> AlibiKSDetector:
    """Instantiate the configured drift detector."""

    ref_path = path or DEFAULT_REF_PATH
    ref = _load_reference(ref_path)
    return AlibiKSDetector(ref, p_val=p_val or DEFAULT_P_VAL)
