# Sion API image for compose.yaml (local development and integration checks).
# EXTRAS selects optional features, e.g. --build-arg EXTRAS=rag,regulation.
# Behind a TLS-intercepting proxy, pass its CA without baking it into the image:
#   docker build --secret id=pip_ca,src=/path/to/ca.pem -f deploy/api.Dockerfile .
FROM python:3.12-slim

ARG EXTRAS=""
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY . /app
RUN --mount=type=secret,id=pip_ca,required=false \
    if [ -f /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi \
    && if [ -n "$EXTRAS" ]; then pip install -e ".[$EXTRAS]"; else pip install -e .; fi \
    && useradd --system --uid 10001 --home /app sion \
    && mkdir -p /app/runtime \
    && chown -R sion /app/runtime

USER sion
EXPOSE 8000
CMD ["uvicorn", "sion_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
