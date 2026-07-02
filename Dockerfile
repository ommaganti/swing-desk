# Reproducible container for the swing-desk dashboard.
#   docker build -t swingdesk .
#   docker run --rm -p 8501:8501 \
#       --env-file .env \
#       -v "$(pwd)/data:/app/data" \
#       swingdesk
# The volume persists the journal, snapshots, and OI cache across runs.
# The morning auto-refresh (launchd) is macOS-only; in a container, schedule
# `swingdesk-refresh` with cron / your platform's scheduler instead.
FROM python:3.11-slim

WORKDIR /app

# Install pinned deps first for layer caching + reproducibility.
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

# App code (see .dockerignore — secrets and local runtime state are excluded).
COPY . .

ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
