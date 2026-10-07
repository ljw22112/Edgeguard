# EdgeGuard MEC application image (MEC host).
#
#   docker build -f mec_app/Dockerfile -t edgeguard-mec .          # from the repository root
#
# The same image also runs the oneM2M resource setup and the virtual devices of the
# demo profile in deploy/docker-compose.yml (tools/, devices/, sim/ are included).
# PYTHON_IMAGE can be swapped for a local base when no registry is reachable.
ARG PYTHON_IMAGE=python:3.11-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY edgeguard ./edgeguard
COPY mec_app ./mec_app
COPY config ./config
COPY tools ./tools
COPY devices ./devices
COPY sim ./sim
COPY deploy/compose-overrides.yaml ./deploy/compose-overrides.yaml

RUN useradd --system --uid 10001 --no-create-home edgeguard && mkdir -p /out && chown edgeguard /out
USER edgeguard

# Tuned site configuration; a deployment overrides only addresses via EDGEGUARD_OVERRIDES.
ENV EDGEGUARD_CONFIG=/app/config/site.yaml
EXPOSE 9090
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=6 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9090/health', timeout=2)"
CMD ["python3", "-m", "uvicorn", "mec_app.app:app", "--host", "0.0.0.0", "--port", "9090", "--log-level", "warning"]
