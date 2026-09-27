# ArrivalGuard API — tek süreç (zamanlayıcı dahil). Üretimde APP_ENV=prod ve .env.example'daki zorunlu değişkenler.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --create-home --uid 10001 app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install .
COPY fixtures ./fixtures
ENV AG_FIXTURES_DIR=/app/fixtures DB_PATH=/data/arrivalguard.db
RUN mkdir -p /data && chown app:app /data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
CMD ["uvicorn", "arrivalguard.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
