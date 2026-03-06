FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEUDEV_WORKSPACE=/workspace/neu-dev \
    NEUDEV_SESSION_STORE=/workspace/.neudev/hosted_sessions \
    NEUDEV_HTTP_PORT=8765 \
    NEUDEV_WS_PORT=8766 \
    NEUDEV_MODEL=auto \
    NEUDEV_AGENT_MODE=parallel \
    NEUDEV_LANGUAGE=English \
    NEUDEV_BOOTSTRAP=0 \
    NEUDEV_HOSTED_RUN_COMMAND_MODE=restricted

WORKDIR /workspace/neu-dev

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt setup.py README.md /workspace/neu-dev/
COPY neudev /workspace/neu-dev/neudev
COPY scripts /workspace/neu-dev/scripts
COPY docs /workspace/neu-dev/docs
COPY tests /workspace/neu-dev/tests

RUN python -m pip install --upgrade pip \
    && python -m pip install -e .

EXPOSE 8765 8766

ENTRYPOINT ["bash", "/workspace/neu-dev/scripts/lightning_entrypoint.sh"]
