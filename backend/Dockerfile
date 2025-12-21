# ใช้ Python 3.9 (หรือเวอร์ชั่นที่คุณใช้)
FROM python:3.9-slim

# ตั้งค่า Working Directory
WORKDIR /app

# Copy ไฟล์ requirements มาลง library ก่อน (เพื่อใช้ Cache ของ Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy โค้ดทั้งหมด
COPY . .

# เปิด Port 8000
EXPOSE 8000

# คำสั่งรัน Server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]