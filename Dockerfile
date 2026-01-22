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
COPY scripts/ ./scripts/
COPY web/ ./web/

# Create data directory for the database
RUN mkdir -p /data

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/data/game_library.db

EXPOSE 5050

# Run the Flask application
CMD ["python", "web/app.py"]
