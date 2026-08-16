FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

RUN addgroup --system cem \
    && adduser --system --ingroup cem cem \
    && chown -R cem:cem /app

COPY --chown=cem:cem app ./app
COPY --chown=cem:cem scripts ./scripts

# Migrations must be in the image: nothing else creates the schema, so a
# container without these can start, report healthy (SELECT 1 succeeds on an
# empty database) and fail every real query with "relation does not exist".
# Something still has to INVOKE them -- an init container, a pre-deploy job, or
# `alembic upgrade head &&` in front of the command. compose.local.yaml does the
# last of those for local development.
COPY --chown=cem:cem alembic.ini ./alembic.ini
COPY --chown=cem:cem migrations ./migrations

USER cem

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
