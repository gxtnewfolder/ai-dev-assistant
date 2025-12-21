FROM python:3.12-slim

# ตั้งค่าให้ Log แสดงผลทันที
ENV PYTHONUNBUFFERED=1

# ตั้งค่า Working Directory
WORKDIR /app

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy ไฟล์ requirements มาลง library
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy โค้ดทั้งหมด
COPY . .

# เปิด Port 8080
EXPOSE 8080

# คำสั่งรัน Server
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}