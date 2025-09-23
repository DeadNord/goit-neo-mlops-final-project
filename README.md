# AIOps Quality Project

Комплексний приклад ML Ops‑платформи для FastAPI сервісу з детекцією дрейфу, моніторингом, логуванням та GitOps‑деплоєм.

## Структура репозиторію

```
app/
│   └── main.py        # FastAPI inference + Prometheus метрики + детекція дрейфу
model/
│   ├── artifacts/     # Збережена модель, референсні дані та метрики тренування
│   └── train.py       # Скрипт повторного тренування
helm/
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/                # Deployment, Service, ServiceAccount
argocd/
│   └── application.yaml          # ArgoCD Application з auto-sync та self-heal
grafana/
│   └── dashboards.json           # Приклад дешборду для метрик сервісу
prometheus/
│   └── additionalScrapeConfigs.yaml  # Scrape конфіг для метрик FastAPI
Dockerfile                        # Контейнер inference сервісу
requirements.txt                  # Python залежності
.gitlab-ci.yml                    # Пайплайн для retrain + оновлення Helm чарта
```

## Опис архітектури

1. **Inference сервіс** — FastAPI (`app/main.py`), завантажує модель з `model/artifacts/model.pkl`, логування у stdout, метрики через `prometheus_client`, детектор дрейфу на базі `alibi-detect (MMDDrift)` з референсом `reference.npy`.
2. **Drift детектор** — `alibi_detect.cd.MMDDrift`, при спрацюванні інкрементує Prometheus лічильник, логування повідомлення та (опціонально) викликає GitLab webhook для retrain.
3. **Retrain CI** — `.gitlab-ci.yml` описує job `retrain-model`, який тренує модель, збирає Docker image, пушить у реєстр та оновлює версію чарта/тег образу (створює гілку `deploy/*`).
4. **Helm + ArgoCD** — Helm чарт у `helm/` описує деплой із прометей анотаціями, середовищем для дрейфу; ArgoCD Application (`argocd/application.yaml`) вмикає `auto-sync` + `selfHeal` та створює namespace.
5. **Моніторинг** — Prometheus збирає `/metrics`, Grafana дешборд з запитами, latency, drift alerts; Loki/Promtail зчитують stdout контейнера (конфіг логування в README).

## Локальний запуск FastAPI

1. Встановіть залежності:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Запустіть сервіс:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
3. Перевірка healthcheck:
   ```bash
   curl http://localhost:8000/healthz
   ```

## Тестовий запит на /predict

```bash
curl -X POST "http://localhost:8000/predict" \
     -H "Content-Type: application/json" \
     -d '{"features": [13.54, 14.36, 87.46, 566.3, 0.09779, 0.08129, 0.06664, 0.04781, 0.1885, 0.05766, 0.2699, 0.7886, 2.058, 23.56, 0.008462, 0.0146, 0.02387, 0.01486, 0.01405, 0.002377, 15.11, 19.26, 99.7, 711.2, 0.144, 0.1773, 0.239, 0.1288, 0.2977, 0.07259]}'
```

У відповіді будуть `prediction`, `drift_detected`, `drift_score`. Стандартна модель повертає ймовірність класу (0–1).

## Як перевірити логування та дрейф

1. **stdout** — запустіть сервіс та надішліть кілька запитів; `uvicorn`/FastAPI логують у stdout. Promtail має бути сконфігурований на namespace `aiops-quality`, або використайте `kubectl logs -l app.kubernetes.io/name=aiops-quality-service -n aiops-quality`.
2. **Drift** — зменшіть параметр `DRIFT_P_THRESHOLD` у Helm values або надішліть аномальні дані (наприклад, великі значення). У логах з'явиться `Drift detection result: drift=True`, а метрика `model_drift_events_total` збільшиться. При налаштованих змінних середовища `GITLAB_RETRAIN_TRIGGER_URL/TOKEN` буде викликано webhook.

## Метрики та Grafana

1. Prometheus scrape конфіг: `prometheus/additionalScrapeConfigs.yaml`. Додайте його в `prometheus.yml` та перезапустіть Prometheus.
2. Grafana імпорт: імпортуйте `grafana/dashboards.json` (JSON). Панелі відображають кількість запитів, latency (p95), останній drift score та кількість спрацювань дрейфу.
3. Для перегляду метрик локально: `curl http://localhost:8000/metrics`.

## Перевірка GitLab CI retrain

1. Установіть змінні `CI_REGISTRY`, `CI_REGISTRY_USER`, `CI_REGISTRY_PASSWORD`, `GITLAB_USER_EMAIL`, `GITLAB_USER_NAME` у GitLab.
2. Запустіть pipeline вручну (`Run pipeline` → `retrain-model`).
3. Job виконає:
   - `python model/train.py` — генерує нову модель і `reference.npy`;
   - `docker build/push` — новий образ з тегом `CI_COMMIT_SHORT_SHA`;
   - `yq` — оновлює тег образу та версію чарта;
   - пушить зміни у гілку `deploy/<ref>`.
4. Перевірте артефакти job (нові артефакти + оновлені YAML).

## Перевірка Helm + ArgoCD

1. Додайте репозиторій у ArgoCD: `argocd repo add <git-url>` з відповідними токенами.
2. Створіть застосунок: `kubectl apply -f argocd/application.yaml`.
3. Переконайтесь, що `Sync Policy` = auto, self-heal. Після коміту нової версії чарта ArgoCD автоматично redeploy.

## Loki + Promtail

- Promtail має бути налаштований на збір stdout з namespace `aiops-quality`. Helm chart додає анотації (можна використати standard promtail `kubernetes-pods-name` pipeline).
- Для перевірки: `kubectl logs` або відкриття Loki dashboard у Grafana (додайте explore запит `app="aiops-quality-service"`).

## Оновлення моделі вручну

1. Запустіть retrain локально:
   ```bash
   python model/train.py --test-size 0.2 --random-state 42
   ```
2. Перебудуйте образ:
   ```bash
   docker build -t <registry>/aiops-quality-service:<tag> .
   docker push <registry>/aiops-quality-service:<tag>
   ```
3. Оновіть `helm/values.yaml` (`image.tag`) та `helm/Chart.yaml` (`version`), закоміть, ArgoCD підхопить нову версію.

## Перевірка повної системи

1. **kubectl port-forward**: `kubectl -n aiops-quality port-forward svc/aiops-quality-service 8000:8000`, перевірити `/predict`.
2. **Логи**: `kubectl logs -l app.kubernetes.io/name=aiops-quality-service -n aiops-quality` — присутні вхідні дані, результати та повідомлення про дрейф.
3. **Drift alert**: форсуйте аномальні дані, спостерігайте в Grafana панель `Drift Events`.
4. **Grafana**: імпортуйте dashboard, переконайтесь у відображенні трафіку/latency/alerts.
5. **CI retrain**: тригер pipeline через webhook (`GITLAB_RETRAIN_TRIGGER_URL`), перевірте лог job.
6. **ArgoCD**: оновіть тег образу у Git → ArgoCD має автоматично застосувати нову ревізію (auto-sync + self-heal).

## Додаткові поради

- Для тестування дрейфу можна змінити `DRIFT_P_THRESHOLD=0.5` у Helm values (швидше спрацювання).
- Переконайтесь, що Prometheus має доступ до service (`ClusterIP`). Якщо використовується ServiceMonitor (Prometheus Operator) — адаптуйте Helm шаблони.
- GitLab runner повинен підтримувати `docker:dind` (privileged). Якщо runner без docker, замініть блок на Kaniko або BuildKit.
