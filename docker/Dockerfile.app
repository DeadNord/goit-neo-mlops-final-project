ARG PYTHON_IMAGE=python:3.11-slim
FROM ${PYTHON_IMAGE}
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app /app/app
EXPOSE 8000
ENV APP_NAME=aiops-quality-service ENABLE_DRIFT=true LOG_LEVEL=INFO
CMD ["uvicorn", "app.main:app", "--host=0.0.0.0", "--port=8000"]
