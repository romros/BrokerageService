FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all scripts
COPY *.py ./

# Make scripts executable
RUN chmod +x *.py

# Keep container alive for testing
CMD ["tail", "-f", "/dev/null"]
