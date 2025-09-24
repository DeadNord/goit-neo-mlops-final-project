import numpy as np
import logging
logger = logging.getLogger(__name__)

class SimpleDriftDetector:
    def __init__(self, ref_mean: float, tol: float = 0.5):
        self.ref_mean = ref_mean
        self.tol = tol

    def check(self, x: np.ndarray) -> bool:
        cur_mean = float(np.mean(x))
        drift = abs(cur_mean - self.ref_mean) > self.tol
        if drift:
            logger.warning("Drift detected: ref_mean=%.3f cur_mean=%.3f tol=%.3f",
                           self.ref_mean, cur_mean, self.tol)
        return drift

def get_drift_detector():
    return SimpleDriftDetector(ref_mean=0.0, tol=0.5)
