FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_DATA_DIR=/data \
    APP_DB_PATH=/data/app.sqlite \
    SIGNAL_CONFIG_DIR=/data/signal-cli \
    SIGNAL_CLI_EXECUTABLE=/opt/signal-cli/bin/signal-cli \
    TZ=Europe/Kyiv

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        openjdk-17-jre-headless \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

ARG SIGNAL_CLI_VERSION=0.13.22

RUN mkdir -p /opt \
    && curl -fsSL "https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz" \
      -o /tmp/signal-cli.tar.gz \
    && tar -xzf /tmp/signal-cli.tar.gz -C /opt \
    && ln -s "/opt/signal-cli-${SIGNAL_CLI_VERSION}" /opt/signal-cli \
    && rm /tmp/signal-cli.tar.gz

COPY requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY app ./app
COPY migrations ./migrations

RUN mkdir -p /data /data/signal-cli

EXPOSE 8000
VOLUME ["/data"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
