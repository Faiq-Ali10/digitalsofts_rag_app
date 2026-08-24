FROM python:3.11-slim

WORKDIR /app

# System dependencies for document parsing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 1. Upgrade build tools first
RUN pip install --upgrade pip setuptools wheel

# 2. Copy ALL application code and pyproject.toml
COPY . .

# 3. Install the package normally (without the -e flag)
RUN pip install --no-cache-dir ".[dev]"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
