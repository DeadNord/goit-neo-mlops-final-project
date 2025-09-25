# AIOps Quality Project — App-of-Apps (Argo CD)

FastAPI-инференс + метрики Prometheus + логи Loki/Promtail + дрейф-детектор.
Деплой и платформа (Prometheus/Grafana/Loki) — через Argo CD App-of-Apps.
CI GitLab: retrain → build → bump Helm → ArgoCD авто-redeploy.

## Архитектура

Argo CD App-of-Apps: `argocd/root-application.yaml` указывает на `argocd/apps/*`:

- kube-prometheus-stack (Prometheus + Grafana, sidecar для dashboards/datasources)
- loki-stack (Loki + Promtail)
- aiops-quality-service (Helm-чарт FastAPI сервиса)
- grafana-dashboards (ConfigMap с дашбордом и датасорсом)

Приложение (`/app`):

- `POST /predict` — предсказание, лог входных/выходных
- `/metrics` — Prometheus метрики (RPS, latency, drift)
- простой drift-детектор (порог по среднему)

GitOps: Argo CD auto-sync + self-heal

CI/CD (GitLab): retrain → build → bump helm → tag → auto-sync

## Требования

- Kubernetes кластер (kind/k3d/minikube/managed)
- `kubectl`, `helm` установлены
- Установлен Argo CD в кластере (namespace: argocd)
- Доступ к Git-репозиторию этой ветки: `main`
- Образы публикуются в ваш контейнерный реестр (обновите `helm/values.yaml.image.repository`)

## Быстрый запуск (одной командой)

Отредактируйте ссылки на репозиторий/реестр:

- `helm/values.yaml`: `image.repository: REGISTRY/aiops-quality-service`
- `argocd/apps/*.yaml`: `repoURL: https://GIT/YOUR/aiops-quality-project.git`

Закоммитьте в ветку `main`.

Примените корневое приложение Argo CD:

```bash
kind create cluster --name aiops

# kubectl create namespace argocd 2>/dev/null || true
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

kubectl apply -n argocd -f argocd/root-application.yaml
kubectl -n argocd get pods

kubectl -n argocd port-forward svc/argocd-server 8080:80
http://localhost:8080/
```

Argo CD подтянет Prometheus+Grafana, Loki+Promtail, приложение и дашборды.
Дождитесь, пока все приложения будут в `Synced/Healthy` (UI ArgoCD или `kubectl get apps -n argocd`).

## Проверки

**API доступен (port-forward):**

```bash
kubectl -n aiops port-forward svc/aiops-quality-service 8000:8000
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d; echo

curl http://localhost:8000/health
```

**Логи пода:**

```bash
kubectl -n aiops logs -l app=aiops-quality-service -f
```

**Метрики сервисa:**

```bash
curl http://localhost:8000/metrics
```

**Grafana:**

Найдите сервис Grafana в ns `monitoring`:

```bash
kubectl -n monitoring get svc | grep grafana
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
kubectl -n monitoring get secret kube-prometheus-stack-grafana \
  -o jsonpath="{.data.admin-password}" | base64 -d; echo
```

Откройте http://localhost:3000 → дашборд “AIOps Quality Service”.

## Как протестировать запрос

```bash
curl -X POST http://localhost:8000/predict   -H "Content-Type: application/json"   -d '{"values":[0.1, 0.2, 0.3]}'
```

Ожидается JSON:

```json
{ "prediction": 0, "drift": false }
```

Входные/выходные данные пишутся в stdout (собирает Promtail → Loki).

## Логирование

- Все логи приложения идут в stdout.
- Стек `loki-stack` собирает логи через promtail.
- В Grafana → Explore → Loki: фильтруйте по `namespace=aiops`, `label app=aiops-quality-service`.

Для теста дрейфа (увидеть "Drift detected" в логах) отправьте значения со средним, отличающимся от 0.0:

```bash
curl -X POST http://localhost:8000/predict   -H "Content-Type: application/json"   -d '{"values":[2.0, 3.0, 4.0]}'
```

## Метрики и Grafana

Метрики на `/metrics` публикуются библиотекой `prometheus-fastapi-instrumentator` + кастомные:

- `inference_requests_total`
- `inference_latency_seconds_bucket`
- `drift_events_total`

`kube-prometheus-stack` подхватывает `ServiceMonitor` из чарта приложения.

Дашборд `grafana/dashboards/aiops-dashboard.json` автоматически провиженится через sidecar.

## Детектор дрейфа

Реализован простой пороговый детектор по среднему (см. `app/drift.py`).

При дрейфе:

- метрика `drift_events_total` инкрементируется,
- в stdout пишется `Drift detected` (видно в Loki).

## Retrain пайплайн (GitLab CI)

Пайплайн (`.gitlab-ci.yml`) содержит:

- `retrain-model` (manual) — обучает модель и публикует артефакт
- `build-image` — собирает Docker-образ приложения с текущей моделью
- `bump-helm-and-tag` — обновляет `helm/values.yaml` и `Chart.yaml`, ставит git-tag, пушит в `main`

**Ручной запуск retrain:**

1. В GitLab → Pipelines → запустить `retrain-model` (Manual).
2. Дождаться `build-image` и `bump-helm-and-tag`.
3. Argo CD возьмёт новый тег образа и раскатит его автоматически.

---

## Обновление модели

1. Локально: `python model/train.py` (создаст/обновит `/model/model.pkl`) — или запустить CI job.
2. Увеличьте версию в `VERSION` (например, `0.1.1`).
3. Пуш в ветку `main` — CI соберёт образ и обновит Helm; Argo CD синхронизирует.
