# EdgeGuard MEC application image (deploy on the MEC host / Jetson).
# Build from the repository root:  docker build -f mec_app/Dockerfile -t edgeguard-mec .
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY edgeguard ./edgeguard
COPY mec_app ./mec_app
COPY config ./config
ENV EDGEGUARD_CONFIG=/app/config/edgeguard.yaml
EXPOSE 9090
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:9090/health')"
CMD ["uvicorn", "mec_app.app:app", "--host", "0.0.0.0", "--port", "9090"]
