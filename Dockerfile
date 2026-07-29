FROM python:3.11-slim

# Install system dependencies for rasterio (GDAL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy solution source code
COPY solution/ ./solution/

# Set the entrypoint as required by the assignment
ENTRYPOINT ["python", "-m", "solution.infer"]
