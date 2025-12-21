FROM python:3.12-slim

# ตั้งค่า Working Directory
WORKDIR /app

# Copy ไฟล์ requirements มาลง library ก่อน (เพื่อใช้ Cache ของ Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy โค้ดทั้งหมด
COPY . .

# เปิด Port (Cloud Run ใช้ 8080 เป็นหลัก แต่เปิด 8000 เผื่อไว้)
EXPOSE 8080

# คำสั่งรัน Server (รองรับ $PORT จาก Cloud Run)
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}