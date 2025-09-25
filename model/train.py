"""
Retrain:
- грузит новые данные (мок),
- обучает модель,
- сохраняет в /model/model.pkl
"""

from pathlib import Path
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.model_io import save_model


def load_new_data():
    X = np.random.randn(1000, 1)
    y = (X[:, 0] > 0.0).astype(int)
    return X, y


def main():
    X, y = load_new_data()
    m = LogisticRegression()
    m.fit(X, y)
    save_model(m)
    ref_path = Path("/model/reference_data.npy")
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(ref_path, X[:, 0])
    print("Model retrained and saved. Reference data updated at", ref_path)


if __name__ == "__main__":
    main()
