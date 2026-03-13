FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cache layer)
COPY requirements-cloud.txt .
RUN pip install --no-cache-dir -r requirements-cloud.txt

# Copy application code
COPY . .

# Render injects PORT at runtime (default 10000)
EXPOSE 10000

# Start with gunicorn (same as render.yaml startCommand)
CMD ["sh", "-c", "gunicorn compass_dashboard_cloud:app --bind 0.0.0.0:${PORT:-10000} --workers 2 --timeout 120 --preload"]
