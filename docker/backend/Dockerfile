# docker.io 在部分网络下不可用，沿用 sandbox 同一镜像源。
FROM docker.m.daocloud.io/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SANDBOX_ROOT=/sandbox \
    SANDBOX_VOLUME=vcos_sandbox

WORKDIR /app

# docker-cli 才有 docker 客户端；docker.io 在 Debian 13 里只装了 dockerd。
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl docker-cli \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 清华源加速；钉死 claude-agent-sdk，避免 pip 回溯上百个版本。
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY docker/backend/openssl.cnf /etc/ssl/vcos-openssl.cnf
ENV OPENSSL_CONF=/etc/ssl/vcos-openssl.cnf
COPY app ./app
COPY docker/sandbox/runner.py /opt/runner/runner.py

RUN mkdir -p /app/data/reports /sandbox /app/.agent

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
