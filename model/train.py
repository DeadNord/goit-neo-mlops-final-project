"""
Retrain:
- грузит новые данные (мок),
- обучает модель,
- сохраняет в /model/model.pkl
"""
import numpy as np
from sklearn.linear_model import LogisticRegression
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
    print("Model retrained and saved.")

if __name__ == "__main__":
    main()
