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
- дрейф-детектор на базе Alibi Detect (KSDrift) + автотреггер retrain в GitLab

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
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d; echo

http://localhost:8080/
```

Argo CD подтянет Prometheus+Grafana, Loki+Promtail, приложение и дашборды.
Дождитесь, пока все приложения будут в `Synced/Healthy` (UI ArgoCD или `kubectl get apps -n argocd`).

## Проверки

**API доступен (port-forward):**

```bash
kubectl -n aiops port-forward svc/aiops-quality-service 8000:8000

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
http://localhost:3000
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

Для теста дрейфа (увидеть "Drift detected" в логах и срабатывание retrain-триггера) отправьте значения, отличающиеся от обучающих данных:

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

На дашборде Grafana доступны панели:

- **Inference Requests / Drift** — графики `inference_requests_total` и `drift_events_total`, можно увидеть рост счётчиков во времени;
- **Latency (P50/P90/P99)** — гистограммы `inference_latency_seconds_bucket`;
- **Pod Health** — статус подов сервиса (через kube-state-metrics);
- **Log samples** — встроенный explore-сегмент (Loki) для быстрых переходов к логам.

## Детектор дрейфа

Используется `alibi-detect` (алгоритм `KSDrift`). Референсные данные считываются из `/model/reference_data.npy`.
Если файл не найден, сервис генерирует синтетический baseline и пишет предупреждение в логах.

При дрейфе:

- метрика `drift_events_total` инкрементируется,
- в stdout пишется `Drift detected` (видно в Loki),
- опционально триггерится GitLab CI пайплайн `retrain-model` (см. ниже).

Обновление эталонных данных происходит вместе с retrain (`model/train.py` сохраняет `/model/reference_data.npy`).

### Настройка автотреггера retrain

Сервис умеет дергать GitLab trigger API при обнаружении дрейфа. Конфигурация задаётся переменными окружения (см. `helm/values.yaml`):

| Переменная | Назначение |
| --- | --- |
| `GITLAB_TRIGGER_ENABLED` | `true` — включить вызов API |
| `GITLAB_BASE_URL` | URL GitLab (по умолчанию `https://gitlab.com`) |
| `GITLAB_PROJECT_ID` | ID проекта или `group/project` |
| `GITLAB_TRIGGER_TOKEN` | Trigger Token из настроек CI/CD |
| `GITLAB_TRIGGER_REF` | Ветка для пайплайна (по умолчанию `main`) |
| `GITLAB_TRIGGER_VARIABLES` | Доп. переменные CI в формате `KEY1=VAL1,KEY2=VAL2` |

После включения (`GITLAB_TRIGGER_ENABLED=true` + заполненные `GITLAB_PROJECT_ID`/`GITLAB_TRIGGER_TOKEN`) сервис при дрейфе запускает фоновой запрос к GitLab. В логах появится сообщение `Drift detected → scheduled GitLab retrain pipeline trigger.`

Проверка:

1. Установите переменные окружения/секреты в чарте (можно через Argo CD values override).
2. Отправьте "аномальный" запрос (см. выше).
3. В логах сервиса (`kubectl logs`) убедитесь, что был вызов GitLab (`GitLab retrain trigger enabled...`, `scheduled GitLab retrain pipeline trigger`).
4. В GitLab появится новый пайплайн `retrain-model` с пометкой "trigger".

## Сценарий проверки дрейфа и метрик

1. Пробросьте порт API (см. раздел «Проверки»).
2. Прогрейте сервис без дрейфа (среднее входов близко к 0):

```bash
for i in $(seq 1 200); do
  curl -s -X POST http://127.0.0.1:8000/predict \
    -H 'Content-Type: application/json' \
    -d '{"values":[0.1,0.2,0.3]}' >/dev/null
  sleep 0.05
done
```

3. Сымитируйте дрейф (среднее значительно отличается):

```bash
for i in $(seq 1 30); do
  curl -s -X POST http://127.0.0.1:8000/predict \
    -H 'Content-Type: application/json' \
    -d '{"values":[2.0,3.0,4.0]}' >/dev/null
  sleep 0.05
done
```

4. Проверьте метрики (счётчики должны увеличиться):

```bash
curl -s http://127.0.0.1:8000/metrics | grep -E 'drift_events_total|inference_requests_total'
```

5. В Grafana на дашборде «AIOps Quality Service» увидите рост `inference_requests_total`, события `drift_events_total` и изменение latency.
6. В Loki (Grafana → Explore) фильтруйте `app=aiops-quality-service` — появится лог `Drift detected`.

## Retrain пайплайн (GitLab CI)

Пайплайн (`.gitlab-ci.yml`) содержит:

- `retrain-model` (manual) — обучает модель и публикует артефакт
- `build-image` — собирает Docker-образ приложения с текущей моделью
- `bump-helm-and-tag` — обновляет `helm/values.yaml` и `Chart.yaml`, ставит git-tag, пушит в `main`

**Ручной запуск retrain:**

1. В GitLab → Pipelines → запустить `retrain-model` (Manual).
2. Дождаться `build-image` и `bump-helm-and-tag`.
3. Argo CD возьмёт новый тег образа и раскатит его автоматически.

**Автотриггер от дрейфа:**

1. Настройте переменные окружения (см. таблицу выше).
2. Отправьте запрос с дрейфующей выборкой.
3. Убедитесь, что в GitLab появился пайплайн, инициированный Trigger API.

## Обновление модели

1. Локально: `python model/train.py` (создаст/обновит `/model/model.pkl`) — или запустить CI job.
2. Увеличьте версию в `VERSION` (например, `0.1.1`).
3. Пуш в ветку `main` — CI соберёт образ и обновит Helm; Argo CD синхронизирует.
