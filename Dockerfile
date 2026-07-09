FROM python:3.12-slim

# Install system dependencies (including yt-dlp for trailer lookups)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    dvdauthor \
    dvd+rw-tools \
    wodim \
    genisoimage \
    fonts-dejavu-core \
    yt-dlp \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY jellydisc/ ./jellydisc/

# Create staging, output, and assets mount directories
RUN mkdir -p assets staging output

# Set env variables
ENV PYTHONUNBUFFERED=1

# By default, run in headless mode
ENTRYPOINT ["python", "-m", "jellydisc.main", "--headless"]
