# Use the stable and slim Python 3.11 base image
FROM python:3.11-slim

# Set environment variables for Python and debian for non-interactive installs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive
# Set a dedicated path for Playwright browsers to be cached between builds
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required by Playwright
# NOTE: The python:3.11-slim image is currently based on Debian Trixie (testing).
# In this version, 'libgles2' and 'libegl1' do not have the '-mesa' suffix.
# This may change if the base image is updated to a different Debian release.
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    procps \
    curl \
    # Playwright browser dependencies
    libxss1 \
    libnss3 \
    libnspr4 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libatspi2.0-0 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxcb-dri3-0 \
    libxcb1 \
    libxtst6 \
    libxshmfence1 \
    libglu1-mesa \
    libgles2 \
    libegl1 \
    libdbus-1-3 \
    # Clean up apt cache to reduce image size
    && rm -rf /var/lib/apt/lists/*

# Copy only the requirements file to leverage Docker's layer caching
COPY requirements.txt .

# Install Python dependencies
# CRITICAL FIX: Added --trusted-host to fix "CERTIFICATE_VERIFY_FAILED" errors on corporate networks/VPNs.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install \
        --no-cache-dir \
        --trusted-host pypi.org \
        --trusted-host files.pythonhosted.org \
        -r requirements.txt

# Install only the Chromium browser without reinstalling dependencies
# The '--with-deps' flag is not needed as we already installed them with apt-get
# CRITICAL FIX: Added NODE_TLS_REJECT_UNAUTHORIZED=0 to fix SSL errors when downloading browsers on corporate networks/VPNs.
RUN NODE_TLS_REJECT_UNAUTHORIZED=0 playwright install chromium

# Copy the rest of the application code into the container
COPY . .

# Create a directory for reports
RUN mkdir -p reports

# Expose the port the app runs on
EXPOSE 5500

# Add a healthcheck to ensure the container is running correctly
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5500/ || exit 1

# Set the command to run the application using Gunicorn
CMD ["gunicorn", "--threads=2", "-t", "500", "--bind", "0.0.0.0:5500", "app:create_app()"]