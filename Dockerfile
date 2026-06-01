# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (FFmpeg, etc)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libopus-dev \
    libffi-dev \
    libsodium-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY railway_bot.py .

# Set environment
ENV PYTHONUNBUFFERED=1

# Run bot
CMD ["python", "railway_bot.py"]
