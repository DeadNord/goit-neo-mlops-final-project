# AIOps Quality Project

Комплексний приклад ML Ops‑платформи: FastAPI inference сервіс із дрейф‑детекцією, GitOps‑деплоєм через ArgoCD, моніторингом у Prometheus/Grafana, логуванням у Loki та пайплайном GitLab CI для перевидання моделі.

## Архітектура та структура репозиторію

```
app/
│   └── main.py        # FastAPI inference + Prometheus метрики + дрейф‑детектор
model/
│   ├── artifacts/     # Збережена модель, референсні дані та метрики тренування
│   └── train.py       # Скрипт повторного тренування
helm/
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/     # Deployment, Service, ServiceAccount, анотації Prometheus/Loki
helm-monitoring/
│   ├── Chart.yaml     # Umbrella-чарт для Loki, Promtail та Grafana
│   ├── values.yaml
│   ├── files/
│   │   └── dashboards.json
│   └── templates/
│       └── dashboards-configmap.yaml
argocd/
│   ├── application.yaml        # ArgoCD Application сервісу з auto-sync та self-heal
│   └── monitoring.yaml         # ArgoCD Application моніторингового стеку
prometheus/
│   └── additionalScrapeConfigs.yaml  # Secret із додатковим scrape-конфігом для Prometheus
Dockerfile                       # Контейнер для inference сервісу
requirements.txt                 # Python залежності
.gitlab-ci.yml                   # GitLab CI/CD пайплайн retrain-model
```

**Ключові компоненти платформи**

| Компонент         | Опис                                                                                                                            |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| FastAPI сервіс    | `app/main.py` завантажує модель, експонує `/predict`, `/healthz`, `/metrics`, логування у stdout                                |
| Дрейф‑детектор    | `alibi_detect.cd.MMDDrift` із `model/artifacts/reference.npy`; збільшує Prometheus-лічильник та логує подію                     |
| GitLab CI retrain | Job `retrain-model` у `.gitlab-ci.yml` тренує модель, оновлює Docker-образ і Helm-чарт                                          |
| Helm + ArgoCD     | `helm/` описує сервіс; `argocd/` містить Application манифести з auto-sync/self-heal                                            |
| Моніторинг        | `helm-monitoring/` деплоїть Loki, Promtail, Grafana та підкладає дешборд; Prometheus отримує `/metrics` через додатковий scrape |
| Логування         | Promtail збирає stdout подів, Loki надає інтерфейс для запитів                                                                  |

## Підготовка облікових даних

1. **GitLab Container Registry** — Settings ➝ Repository ➝ Container Registry. Створіть (або використайте) Deploy Token/Personal Access Token з правами `read_registry`/`write_registry`.
2. **GitLab Project ID** — Settings ➝ General ➝ General ➝ Project ID.
3. **Pipeline Trigger Token** — Settings ➝ CI/CD ➝ Pipeline Triggers (створіть `retrain-model`).
4. **GitLab Personal Access Token** для ArgoCD — Profile ➝ Access Tokens (`read_repository`).
5. **ArgoCD доступ** — URL контролера та креденшли (admin/password або SSO).

Заповніть файл `.env` та експортуйте його в середовище:

```bash
cp .env.example .env
set -a
source .env
set +a
export IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-$REGISTRY/aiops-quality-service}"
export IMAGE_TAG="${IMAGE_TAG:-$(date +%Y%m%d%H%M)}"
```

## Покроковий кластерний runbook

1. **Зберіть та запуште Docker-образ inference сервісу.**

   ```bash
   docker login "$REGISTRY" -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD"
   docker build -t "$IMAGE_REPOSITORY:$IMAGE_TAG" .
   docker push "$IMAGE_REPOSITORY:$IMAGE_TAG"
   ```

2. **Оновіть Helm-чарт сервісу GitOps-способом та запуште зміни.**

   ```bash
   yq -i '.image.repository = strenv(IMAGE_REPOSITORY)' helm/values.yaml
   yq -i '.image.tag = strenv(IMAGE_TAG)' helm/values.yaml
   git add helm/values.yaml
   git commit -m "chore: set image $IMAGE_TAG" && git push || echo "Helm values вже містять поточний тег"
   ```

3. **Підготуйте namespace та secret для pull з registry.**

   ```bash
   kubectl create namespace aiops-quality --dry-run=client -o yaml | kubectl apply -f -
   kubectl -n aiops-quality create secret docker-registry registry-cred \
     --docker-server="$REGISTRY" \
     --docker-username="$CI_REGISTRY_USER" \
     --docker-password="$CI_REGISTRY_PASSWORD" \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

4. **Увімкніть scrape конфіг у Prometheus Operator.**

   ```bash
   kubectl apply -f prometheus/additionalScrapeConfigs.yaml
   export PROMETHEUS_NAME=$(kubectl -n monitoring get prometheus -o jsonpath='{.items[0].metadata.name}')
   kubectl -n monitoring patch prometheus "$PROMETHEUS_NAME" --type merge \
     -p '{"spec":{"additionalScrapeConfigs":{"name":"prometheus-additional-scrape-configs","key":"additional-scrape-configs.yaml"}}}'
   kubectl -n monitoring rollout status statefulset prometheus-k8s
   ```

5. **Підключіть ArgoCD CLI та репозиторій.**

   ```bash
   argocd login "$ARGOCD_SERVER" --username "$ARGOCD_USERNAME" --password "$ARGOCD_PASSWORD" --insecure
   argocd repo add "$GIT_REPO_URL" --username "$GIT_USERNAME" --password "$GIT_TOKEN"
   ```

6. **Створіть ArgoCD застосунки для сервісу та моніторингу.**

   ```bash
   kubectl apply -f argocd/monitoring.yaml
   kubectl apply -f argocd/application.yaml
   argocd app sync aiops-quality-monitoring
   argocd app wait aiops-quality-monitoring --sync --health
   argocd app sync aiops-quality-service
   argocd app wait aiops-quality-service --sync --health
   ```

7. **Налаштуйте порт-форварди для API, Grafana та Loki.**

   ```bash
   kubectl -n aiops-quality port-forward svc/aiops-quality-service 8000:8000 >/tmp/api-port-forward.log 2>&1 &
   export API_PORT_FORWARD_PID=$!
   kubectl -n monitoring port-forward svc/grafana 3000:80 >/tmp/grafana-port-forward.log 2>&1 &
   export GRAFANA_PORT_FORWARD_PID=$!
   kubectl -n monitoring port-forward svc/loki 3100:3100 >/tmp/loki-port-forward.log 2>&1 &
   export LOKI_PORT_FORWARD_PID=$!
   sleep 5
   ```

8. **Перевірте здоров'я сервісу та Prometheus-метрики.**

   ```bash
   curl -s http://127.0.0.1:8000/healthz
   curl -s http://127.0.0.1:8000/metrics | grep model_predictions_total
   curl -s -X POST "http://127.0.0.1:8000/predict" \
     -H "Content-Type: application/json" \
     -d '{"features": [13.54, 14.36, 87.46, 566.3, 0.09779, 0.08129, 0.06664, 0.04781, 0.1885, 0.05766, 0.2699, 0.7886, 2.058, 23.56, 0.008462, 0.0146, 0.02387, 0.01486, 0.01405, 0.002377, 15.11, 19.26, 99.7, 711.2, 0.144, 0.1773, 0.239, 0.1288, 0.2977, 0.07259]}' | jq '.'
   ```

9. **Звірте логування через Kubernetes та Loki.**

   ```bash
   kubectl -n aiops-quality logs deployment/aiops-quality-service | tail -n 20
   curl -s "http://127.0.0.1:3100/loki/api/v1/query?query={app%3D%22aiops-quality-service%22}&limit=5" | jq '.data.result[]?.stream'
   ```

10. **Спровокуйте дрейф-детектор та перевірте метрики/логи.**

    ```bash
    kubectl -n aiops-quality set env deployment/aiops-quality-service DRIFT_P_THRESHOLD=0.5 --overwrite
    kubectl -n aiops-quality rollout status deployment/aiops-quality-service
    curl -s -X POST "http://127.0.0.1:8000/predict" \
      -H "Content-Type: application/json" \
      -d '{"features": [100, 150, 200, 300, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 1, 1, 1, 1, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 100, 120, 140, 160, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9]}' | jq '.'
    kubectl -n aiops-quality logs deployment/aiops-quality-service | grep "Drift detection result" | tail -n 5
    curl -s http://127.0.0.1:8000/metrics | grep model_drift_events_total
    ```

11. **Запустіть GitLab CI пайплайн retrain та дочекайтеся GitOps оновлення.**

    ```bash
    curl -s -X POST "https://gitlab.com/api/v4/projects/$GITLAB_PROJECT_ID/trigger/pipeline" \
      --form token="$GITLAB_TRIGGER_TOKEN" \
      --form ref=main
    argocd app wait aiops-quality-service --operation
    argocd app get aiops-quality-service | grep -E "Health|Sync Status"
    kubectl -n aiops-quality rollout status deployment/aiops-quality-service
    ```

12. **Перевірте Grafana дешборд та джерела даних.**

    ```bash
    curl -s -u admin:admin "http://127.0.0.1:3000/api/datasources" | jq '.[].name'
    curl -s -u admin:admin "http://127.0.0.1:3000/api/dashboards/uid/aiops-quality" | jq '.dashboard.panels[].title'
    ```

13. **Завершіть порт-форварди після тестів.**

    ```bash
    kill "$API_PORT_FORWARD_PID"
    kill "$GRAFANA_PORT_FORWARD_PID"
    kill "$LOKI_PORT_FORWARD_PID"
    rm -f /tmp/api-port-forward.log /tmp/grafana-port-forward.log /tmp/loki-port-forward.log
    ```

14. **Повністю вимкніть створену інфраструктуру.**

```bash
argocd app delete aiops-quality-service --yes
argocd app delete aiops-quality-monitoring --yes
kubectl delete namespace aiops-quality --ignore-not-found
kubectl delete namespace monitoring --ignore-not-found
kubectl delete secret -n monitoring prometheus-additional-scrape-configs --ignore-not-found
```
