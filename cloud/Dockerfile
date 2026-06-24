# Pawse API container image.
# Build context is the repo root (see azure.yaml) so we can pull in the shared
# scoring/ package next to the cloud/ service code.
#
# BASE_IMAGE defaults to Docker Hub for local builds. In CI we override it with
# the ACR-mirrored copy (az acr import) so the build pulls the base image
# authenticated from our own registry and never hits Docker Hub's anonymous
# pull rate limit.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

COPY cloud/requirements.txt ./cloud/requirements.txt
RUN pip install --no-cache-dir -r cloud/requirements.txt

# Shared scoring engine, the API service, and the dashboard it serves.
COPY scoring/ ./scoring/
COPY cloud/ ./cloud/
COPY app/ ./app/
COPY data/alex_workday.json ./data/alex_workday.json

EXPOSE 8000

# Run as a non-root user (Container Apps best practice).
RUN useradd --create-home --uid 1001 appuser
USER appuser

CMD ["uvicorn", "cloud.app:app", "--host", "0.0.0.0", "--port", "8000"]
