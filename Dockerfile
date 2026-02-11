FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential ffmpeg libsndfile1 espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -m -u 1000 appuser

COPY requirements.txt ./
RUN pip install --no-cache-dir -i https://pypi.org/simple/ -r requirements.txt

COPY app ./app
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Set ownership of app directory to appuser
RUN chown -R appuser:appuser /app

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
