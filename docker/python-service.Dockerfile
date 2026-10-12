# syntax=docker/dockerfile:1.7
# One Dockerfile for every Python service. Build from the repo root:
#   docker build -f docker/python-service.Dockerfile --build-arg SERVICE=auth -t shop-auth .

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS build
ARG SERVICE
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /venv
ENV PATH=/venv/bin:$PATH
COPY libs/shopcommon /src/shopcommon
COPY services/${SERVICE}/requirements.txt /src/requirements.txt
RUN pip install /src/shopcommon -r /src/requirements.txt

FROM python:${PYTHON_VERSION}-slim
ARG SERVICE
ENV PATH=/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_NAME=${SERVICE}
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
COPY --from=build /venv /venv
WORKDIR /app
COPY --chown=app:app services/${SERVICE}/app ./app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/healthz'); sys.exit(0)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
