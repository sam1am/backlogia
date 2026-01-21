FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for legendary-gl (Epic Games)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

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
