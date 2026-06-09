# --- Stage 1: Build React frontend ---
FROM node:22-alpine AS frontend-builder
WORKDIR /frontend

# Spec 54 — bakes version no bundle do frontend.
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
ENV GIT_SHA=$GIT_SHA
ENV BUILD_DATE=$BUILD_DATE

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime ---
FROM python:3.12-slim
WORKDIR /app

# Spec 54 — backend lê via env em runtime pra responder /version.
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
ENV GIT_SHA=$GIT_SHA
ENV BUILD_DATE=$BUILD_DATE

RUN pip install --no-cache-dir uv

# Install dependencies first (layer cached; --no-install-project skips building
# the package itself so we don't need src/ yet). --extra llm pulls anthropic,
# Pillow, openpyxl — sem isso, o serviço de extração quebra em runtime com
# "anthropic SDK not installed".
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra llm

# Application source (needed to install the numis-geek package itself)
COPY src/ src/
RUN uv sync --frozen --no-dev --extra llm
COPY alembic/ alembic/
COPY alembic.ini ./

# Built frontend
COPY --from=frontend-builder /frontend/dist frontend/dist/

# Persistent data lives here (mount a volume in production).
# Spec 55 adicionou data/logs pra RotatingFileHandler do backend.
RUN mkdir -p data/attachments data/backups data/logs

EXPOSE 8000

ENV FRONTEND_DIST=frontend/dist
# Spec 55 — habilita file logging (data/logs/numis.log com rotação).
ENV LOG_DIR=data/logs

CMD ["uv", "run", "uvicorn", "numis_geek.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
