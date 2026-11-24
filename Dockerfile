# One image: built React UI + FastAPI. Config via env. No host paths, no secrets.
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UI_DIST=/app/frontend/dist \
    HOST=0.0.0.0 \
    PORT=8000

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .
COPY --from=ui /ui/dist /app/frontend/dist

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn fantasy_football.api.app:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
