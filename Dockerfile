FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for Pillow (thumbnail generation)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libjpeg62-turbo libwebp7 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY player ./player
COPY admin ./admin

RUN mkdir -p /app/data /app/media/images /app/media/videos /app/media/sponsors /app/media/thumbnails

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
