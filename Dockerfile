FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for legendary-gl (Epic Games) and Nile
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Nile (Amazon Games client) from GitHub
# Clone and patch pyproject.toml to fix packaging issues
RUN pip install --no-cache-dir pycryptodome zstandard requests protobuf json5 \
    && git clone --depth 1 https://github.com/imLinguin/nile.git /opt/nile \
    && cd /opt/nile \
    && sed -i 's/dynamic = \["version"\]/version = "1.1.1"/' pyproject.toml \
    && echo '[tool.setuptools.packages.find]' >> pyproject.toml \
    && echo 'include = ["nile*"]' >> pyproject.toml \
    && pip install --no-cache-dir .

# Copy application code
COPY web/ ./web/

# Create data directory and non-root user with a fixed UID/GID (1000)
# so host volume mounts can be chowned to match without inspecting the image first
RUN mkdir -p /data \
    && groupadd -g 1000 appuser \
    && useradd -u 1000 -g appuser -s /bin/sh appuser \
    && chown -R appuser:appuser /app /data

USER appuser

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/data/game_library.db

EXPOSE 5050

# Run the FastAPI application
CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "5050"]
