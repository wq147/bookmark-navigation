FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
RUN useradd --system --uid 10001 --create-home app
WORKDIR /app
COPY backend/ ./
RUN pip install --no-cache-dir .
COPY --from=frontend /src/dist /app/static
USER app
CMD ["sh", "-c", "FORWARDED_ALLOW_IPS=${NAV_TRUSTED_PROXY_IPS:-172.30.0.1} exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers"]
