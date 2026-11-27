ARG DCLAW_BASE_IMAGE
FROM ${DCLAW_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models/huggingface

WORKDIR /app

COPY deploy/realtime_stt/requirements.txt /tmp/requirements.txt
RUN uv pip install \
      --python /app/venv/bin/python \
      --index-url https://mirrors.aliyun.com/pypi/simple/ \
      --no-cache-dir \
      --requirement /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

COPY deploy/realtime_stt /app/deploy/realtime_stt

EXPOSE 8090

CMD ["uvicorn", "deploy.realtime_stt.app:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
