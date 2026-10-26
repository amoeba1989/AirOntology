FROM node:22-alpine AS web
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_TILE_URL=https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png
ARG VITE_TILE_ATTRIBUTION="&copy; OpenStreetMap contributors"
ARG VITE_ARCGIS_TOKEN=
ENV VITE_TILE_URL=$VITE_TILE_URL VITE_TILE_ATTRIBUTION=$VITE_TILE_ATTRIBUTION VITE_ARCGIS_TOKEN=$VITE_ARCGIS_TOKEN
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt && useradd --system --uid 10001 airontology
COPY backend/app /app/backend/app
COPY ontology /app/ontology
COPY simulator /app/simulator
COPY --from=web /build/dist /app/frontend/dist
ENV PYTHONPATH=/app/backend
USER airontology
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
