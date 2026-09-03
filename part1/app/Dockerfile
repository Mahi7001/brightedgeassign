FROM python:3.11-slim

WORKDIR /app

# Prevent Python from buffering stdout/stderr and writing .pyc files
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root system user for security
RUN useradd -u 10001 appuser
USER 10001

COPY --chown=appuser:appuser main.py .

EXPOSE 8080

# Starts uvicorn on port 8080, dynamically reading WORKERS from env
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8080 --workers ${WORKERS:-1}"]