# image เดียวใช้ทั้ง web และ worker (คนละ command ใน docker-compose.yml)
FROM python:3.12-slim

# ffmpeg: ดึงภาพจากกล้อง RTSP (FR-1)
# libgl1, libglib2.0-0: dependency ของ opencv-python
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000"]
