FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models/huggingface

WORKDIR /app

COPY deploy/realtime_stt/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY deploy/realtime_stt /app/deploy/realtime_stt

EXPOSE 8090

CMD ["uvicorn", "deploy.realtime_stt.app:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
