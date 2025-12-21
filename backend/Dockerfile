FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

# ตั้งค่า Working Directory
WORKDIR /app

# Copy ไฟล์ requirements มาลง library ก่อน
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy โค้ดทั้งหมด
COPY . .

# เปิด Port 8080
EXPOSE 8080

# คำสั่งรัน Server (ถูกต้องแล้วครับ)
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}