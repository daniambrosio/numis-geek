# --- Stage 1: Build React frontend ---
FROM node:22-alpine AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime ---
FROM python:3.12-slim
WORKDIR /app

RUN pip install --no-cache-dir uv

# Install dependencies first (layer cached; --no-install-project skips building
# the package itself so we don't need src/ yet)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application source (needed to install the numis-geek package itself)
COPY src/ src/
RUN uv sync --frozen --no-dev
COPY alembic/ alembic/
COPY alembic.ini ./

# Built frontend
COPY --from=frontend-builder /frontend/dist frontend/dist/

# Persistent data lives here (mount a volume in production)
RUN mkdir -p data/attachments data/backups

EXPOSE 8000

ENV FRONTEND_DIST=frontend/dist

CMD ["uv", "run", "uvicorn", "numis_geek.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
