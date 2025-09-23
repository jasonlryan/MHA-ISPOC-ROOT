# Sample Dockerfile for MHA iSPOC pipeline runner
# Build with: docker build -t <acr>.azurecr.io/mha-ispoc:latest -f infra/Dockerfile .
# Push with:  docker push <acr>.azurecr.io/mha-ispoc:latest

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace/app

# System deps (kept minimal). Uncomment if needed for wheels/builds.
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     && rm -rf /var/lib/apt/lists/*

# Install Python requirements first for better layer caching
COPY scripts/requirements.txt /workspace/app/scripts/requirements.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install -r scripts/requirements.txt

# Copy repository
COPY . /workspace/app

# Default command (can be overridden by the job)
CMD ["python", "run_pipeline.py", "--log-level", "INFO"]
