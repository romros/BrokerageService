FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (tzdata per TZ=America/New_York)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=America/New_York

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories
RUN mkdir -p /datafiles /app/logs

# Expose ports
EXPOSE 8000

# Run application
CMD ["python3", "-m", "uvicorn", "application.main:app", "--host", "0.0.0.0", "--port", "8000"]
