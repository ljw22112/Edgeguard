# EdgeGuard application instance, as the orchestrator deploys it on a MEC host (edgeguard/orchestration.py).
# Built by tools/orchestration_demo.py --runtime docker (context: the edgeguard package files it needs).
#   docker build -t edgeguard/edge-app:1.0 --build-arg BASE=python:3.11-slim <context>
ARG BASE=python:3.11-slim
FROM ${BASE}
# exec form: works on images without a shell too
RUN ["python3", "-c", "import importlib.util, subprocess, sys; importlib.util.find_spec('requests') or subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', 'requests>=2.31'])"]
WORKDIR /app
COPY edgeguard /app/edgeguard
ENTRYPOINT ["python3", "-m", "edgeguard.edge_app"]
