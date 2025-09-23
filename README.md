# AIOps Quality Project

Комплексний приклад ML Ops‑платформи: FastAPI inference сервіс із дрейф‑детекцією, GitOps‑деплоєм через ArgoCD, моніторингом у Prometheus/Grafana, логуванням у Loki та пайплайном GitLab CI для перевидання моделі.

## Архітектура та вміст репозиторію

```
app/
│   └── main.py        # FastAPI inference + Prometheus метрики + дрейф‑детектор
model/
│   ├── artifacts/     # Збережена модель, референсні дані та метрики тренування
│   └── train.py       # Скрипт повторного тренування
helm/
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/     # Deployment, Service, ServiceAccount, ConfigMap
argocd/
│   └── application.yaml   # ArgoCD Application з auto-sync та self-heal
grafana/
│   └── dashboards.json    # Дешборд із запитами, latency та дрейф‑алертами
prometheus/
│   └── additionalScrapeConfigs.yaml  # Scrape конфіг для FastAPI сервісу
Dockerfile                     # Контейнер для inference сервісу
requirements.txt               # Python залежності
.gitlab-ci.yml                 # GitLab CI/CD пайплайн retrain-model
```

**Основні компоненти платформи**

1. **Inference сервіс** (`app/main.py`) — FastAPI, завантажує модель з `model/artifacts/model.pkl`, експонує `/predict`, `/healthz`, `/metrics`, логування у stdout.
2. **Дрейф‑детектор** — `alibi_detect.cd.MMDDrift` з референсом `model/artifacts/reference.npy`; при спрацюванні збільшує Prometheus‑лічильник і логінг повідомлення, за наявності webhook викликає GitLab retrain.
3. **GitLab CI retrain** (`.gitlab-ci.yml`) — job `retrain-model` тренує модель, збирає Docker образ, оновлює Helm чарт і пушить зміни.
4. **Helm чарт** (`helm/`) — Deployment/Service із Prometheus та Loki анотаціями, змінні середовища для дрейфу й webhook.
5. **ArgoCD** (`argocd/application.yaml`) — Application у namespace `aiops-quality`, auto-sync + self-heal для Helm релізу.
6. **Моніторинг** — Prometheus збирає `/metrics` через додатковий scrape, Grafana використовує `grafana/dashboards.json`.
7. **Логування** — Loki + Promtail читають stdout завдяки анотаціям у Helm чартах.

## Покрокова інструкція запуску, перевірки та оновлення

### 1. Підготовка локального середовища

```bash
git clone <ваш-git-url>/aiops-quality-project.git
cd aiops-quality-project
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> Якщо потрібна GPU/CPU специфіка — оновіть `requirements.txt` перед встановленням.

### 2. Локальний запуск FastAPI сервісу

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Очікуйте повідомлення `Application startup complete`. Сервіс доступний на `http://localhost:8000`.

### 3. Перевірка healthcheck та прометей метрик

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/metrics | head
```

Перше повертає `{"status": "ok"}`, друге — набір Prometheus метрик (включно з `model_drift_events_total`).

### 4. Тестовий запит на `/predict`

```bash
curl -X POST "http://localhost:8000/predict" \
     -H "Content-Type: application/json" \
     -d '{"features": [13.54, 14.36, 87.46, 566.3, 0.09779, 0.08129, 0.06664, 0.04781, 0.1885, 0.05766, 0.2699, 0.7886, 2.058, 23.56, 0.008462, 0.0146, 0.02387, 0.01486, 0.01405, 0.002377, 15.11, 19.26, 99.7, 711.2, 0.144, 0.1773, 0.239, 0.1288, 0.2977, 0.07259]}'
```

Очікувана відповідь: `prediction` (ймовірність 0–1), `drift_detected` (True/False), `drift_score` (p-value). Усі запити логуються у stdout.

### 5. Перевірка логування

- Локально: у вікні з `uvicorn` побачите рядки з даними запиту та результатом.
- У Kubernetes:

```bash
kubectl logs -l app.kubernetes.io/name=aiops-quality-service -n aiops-quality -f
```

Після підключення Promtail/Loki логи з'являться в Grafana Explore (запит `{app="aiops-quality-service"}`).

### 6. Перевірка дрейф‑детектора

1. Зробіть поріг чутливішим (опціонально):

   ```bash
   kubectl -n aiops-quality edit configmap aiops-quality-service-config
   # змініть DRIFT_P_THRESHOLD на 0.5 або нижче, збережіть та дочекайтесь оновлення подів
   ```

2. Надішліть аномальний запит:

   ```bash
   curl -X POST "http://localhost:8000/predict" \
        -H "Content-Type: application/json" \
        -d '{"features": [100, 150, 200, 300, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 1, 1, 1, 1, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 100, 120, 140, 160, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9]}'
   ```

3. Переконайтесь у логах у повідомленні `Drift detection result: drift=True` і в метриках:

   ```bash
   curl http://localhost:8000/metrics | grep model_drift_events_total
   ```

4. За наявності змінних `GITLAB_RETRAIN_TRIGGER_URL` та `GITLAB_RETRAIN_TRIGGER_TOKEN` сервіс викличе GitLab webhook для retrain.

### 7. Побудова та публікація Docker образу

```bash
export REGISTRY=<ваш-реєстр>
export IMAGE_TAG=$(date +%Y%m%d%H%M)
docker login "$REGISTRY"
docker build -t "$REGISTRY/aiops-quality-service:$IMAGE_TAG" .
docker push "$REGISTRY/aiops-quality-service:$IMAGE_TAG"
```

### 8. Підготовка Kubernetes namespace та секретів

```bash
kubectl create namespace aiops-quality
kubectl -n aiops-quality create secret docker-registry registry-cred \
  --docker-server="$REGISTRY" \
  --docker-username="$CI_REGISTRY_USER" \
  --docker-password="$CI_REGISTRY_PASSWORD"
```

За потреби додайте `registry-cred` у `imagePullSecrets` у `helm/values.yaml`.

### 9. Ручний деплой Helm чарта (первинне розгортання)

```bash
helm upgrade --install aiops-quality-service ./helm \
  --namespace aiops-quality \
  --set image.repository="$REGISTRY/aiops-quality-service" \
  --set image.tag="$IMAGE_TAG"

kubectl get pods -n aiops-quality
```

Чекайте статусу `Running/Ready`.

### 10. Налаштування ArgoCD

```bash
argocd repo add <git-url> --username <user> --password <token>
kubectl apply -f argocd/application.yaml
argocd app sync aiops-quality-service
```

ArgoCD бере під контроль реліз Helm, `autoSync: true` та `selfHeal: true` забезпечують автооновлення.

### 11. Перевірка сервісу в кластері

```bash
kubectl -n aiops-quality port-forward svc/aiops-quality-service 8000:8000
curl http://127.0.0.1:8000/healthz
curl -X POST "http://127.0.0.1:8000/predict" \
     -H "Content-Type: application/json" \
     -d '{"features": [13.54, 14.36, 87.46, ...]}'
```

### 12. Підключення Prometheus та Grafana

1. Додайте scrape конфіг:

   ```bash
   kubectl apply -n monitoring -f prometheus/additionalScrapeConfigs.yaml
   kubectl rollout restart statefulset prometheus-k8s -n monitoring
   ```

2. Імпортуйте дешборд у Grafana (UI → Dashboards → Import → JSON з `grafana/dashboards.json`).
3. Перевірте панелі: `Requests per minute`, `Latency p95`, `Drift events`.

### 13. Налаштування Loki + Promtail

```bash
helm upgrade --install loki grafana/loki-stack --namespace monitoring --set grafana.enabled=false
helm upgrade --install promtail grafana/promtail \
  --namespace monitoring \
  --set "config.clients[0].url=http://loki.monitoring:3100/loki/api/v1/push"
```

Анотації `loki.grafana.com/*` у Helm чартах вже додаються; логи будуть доступні в Grafana Explore.

### 14. Перевірка GitLab CI пайплайна `retrain-model`

1. Додайте змінні у налаштуваннях GitLab проєкту:

   ```text
   CI_REGISTRY
   CI_REGISTRY_USER
   CI_REGISTRY_PASSWORD
   GITLAB_USER_EMAIL
   GITLAB_USER_NAME
   GITLAB_REPOSITORY_URL
   ```

2. (Опціонально) додайте `GITLAB_RETRAIN_TRIGGER_URL` та `GITLAB_RETRAIN_TRIGGER_TOKEN` для автоматичного виклику.
3. Запустіть пайплайн вручну: UI → `Run pipeline` → job `retrain-model` → `Play`.
4. У логах переконайтесь у виконанні кроків `python model/train.py`, `docker build/push`, `yq` оновлення версій, `git push deploy/<ref>`.
5. Після пушу змін ArgoCD автоматично redeploy сервіс.

### 15. Оновлення моделі вручну (без CI)

```bash
python model/train.py --test-size 0.2 --random-state 42
docker build -t "$REGISTRY/aiops-quality-service:$IMAGE_TAG" .
docker push "$REGISTRY/aiops-quality-service:$IMAGE_TAG"
```

Оновіть `helm/values.yaml` (`image.tag`) та `helm/Chart.yaml` (`version`), виконайте `git commit && git push` — ArgoCD підхопить нову версію.

### 16. Повна перевірка системи

1. **Трафік** — надішліть декілька запитів `curl` або використайте `hey`/`ab`.
2. **Логи** — `kubectl logs ...` та Grafana Explore повинні містити вхідні дані та відповіді.
3. **Drift** — форсуйте аномалії, перевірте `drift_detected=True`, метрику `model_drift_events_total` і панель Grafana.
4. **Prometheus/Grafana** — відкрийте дешборд, переконайтесь у відображенні запитів, latency, кількості дрейфів.
5. **GitLab CI retrain** — після webhook/job очікуйте новий тег образу, оновлені `values.yaml`/`Chart.yaml`.
6. **ArgoCD** — статус застосунку має бути `Synced` та `Healthy`; при зміні чарта ArgoCD робить redeploy.

### 17. Корисні поради

- Для швидкого тесту дрейфу можна встановити `DRIFT_P_THRESHOLD=0.5` через Helm `--set env.DRIFT_P_THRESHOLD=0.5`.
- Якщо Prometheus Operator використовується, замініть scrape-конфіг на `ServiceMonitor` (можна додати шаблон у `helm/templates/`).
- GitLab Runner має працювати в режимі `docker:dind`; якщо це неможливо, замініть збірку на Kaniko/BuildKit.
