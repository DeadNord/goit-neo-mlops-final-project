from pathlib import Path
import joblib
import numpy as np

MODEL_PATH = Path("/model/model.pkl")

def load_model():
    if MODEL_PATH.exists():
        return joblib.load(MODEL_PATH)
    # простой мок: логистическая регрессия с нулевыми весами
    from sklearn.linear_model import LogisticRegression
    m = LogisticRegression()
    m.classes_ = np.array([0, 1])
    m.coef_ = np.zeros((1, 1))
    m.intercept_ = np.zeros((1,))
    m.n_features_in_ = 1
    return m

def save_model(model):
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
