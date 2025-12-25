import os
import shutil
import git
import time
from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
from google import genai
from langchain.text_splitter import RecursiveCharacterTextSplitter, Language
from langchain_core.documents import Document

# 1. โหลด Environment Variables
load_dotenv()

# 2. Config ค่าต่างๆ
REPO_PATH = "./temp_repo"
EMBEDDING_MODEL = "text-embedding-004"
PINECONE_INDEX_NAME = "codebase"
BATCH_SIZE = 100  # ส่งข้อมูลเข้า Pinecone ทีละ 100 ก้อน (เร็วกว่าส่งทีละอัน)

# 3. เริ่มต้น Pinecone
api_key = os.environ.get("PINECONE_API_KEY")
if not api_key:
    raise ValueError("❌ PINECONE_API_KEY not found in .env")

pc = Pinecone(api_key=api_key)
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# สร้าง Index ถ้ายังไม่มี
if PINECONE_INDEX_NAME not in pc.list_indexes().names():
    pc.create_index(
        name=PINECONE_INDEX_NAME,
        dimension=768,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1")
    )

index = pc.Index(PINECONE_INDEX_NAME)

# --- Helper Function: Batch Generator ---
def chunks(iterable, batch_size=100):
    """ฟังก์ชันช่วยแบ่งข้อมูลเป็นก้อนๆ เพื่อส่งแบบ Batch"""
    it = iter(iterable)
    chunk = list(it)
    while chunk:
        # ถ้า chunk ยังไม่เต็ม batch_size ให้เติม
        while len(chunk) < batch_size:
             try:
                 chunk.append(next(it))
             except StopIteration:
                 break
        yield chunk[:batch_size]
        chunk = chunk[batch_size:]
        # ถ้า chunk หมดแล้ว แต่อ่านต่อได้ (กรณีหลุด loop while ใน)
        if not chunk and len(chunk) < batch_size:
             try:
                # ลองดึงตัวถัดไป ถ้ามีก็เริ่ม loop ใหม่
                 item = next(it) 
                 chunk.append(item) 
             except StopIteration:
                 break
                 
# เขียนแบบง่ายกว่าสำหรับ list slicing
def batch_iterate(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def ingest_repo(repo_url: str):
    """โหลด Repo และแปลงเป็น Vector ลง Pinecone"""
    print(f"🚀 Starting ingestion for: {repo_url}")
    
    # 1. Clear พื้นที่เก่า
    if os.path.exists(REPO_PATH):
        shutil.rmtree(REPO_PATH)

    # 2. Clone แบบ depth=1 (เร็วขึ้นมาก ไม่เอาประวัติเก่า)
    print("📥 Cloning repository (Depth=1)...")
    git.Repo.clone_from(repo_url, REPO_PATH, depth=1)

    documents = []
    
    # 3. อ่านไฟล์และเลือก Splitter ให้ฉลาด
    print("📂 Processing files...")
    for root, dirs, files in os.walk(REPO_PATH):
        # ข้ามโฟลเดอร์ที่ไม่จำเป็น
        if '.git' in dirs: dirs.remove('.git')
        if 'node_modules' in dirs: dirs.remove('node_modules')
        
        for file in files:
            file_path = os.path.join(root, file)
            # รองรับไฟล์ Code หลักๆ
            if file.endswith(('.py', '.js', '.jsx', '.ts', '.tsx', '.md', '.txt', '.html', '.css', '.cs')):
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        
                    relative_path = os.path.relpath(file_path, REPO_PATH)
                    
                    # เลือก Splitter ตามภาษา
                    if file.endswith('.py'):
                        splitter = RecursiveCharacterTextSplitter.from_language(
                            language=Language.PYTHON, chunk_size=1000, chunk_overlap=200
                        )
                    elif file.endswith(('.js', '.jsx', '.ts', '.tsx')):
                        splitter = RecursiveCharacterTextSplitter.from_language(
                            language=Language.JS, chunk_size=1000, chunk_overlap=200
                        )
                    elif file.endswith('.md'):
                        splitter = RecursiveCharacterTextSplitter.from_language(
                            language=Language.MARKDOWN, chunk_size=1000, chunk_overlap=200
                        )
                    elif file.endswith('.cs'):
                        splitter = RecursiveCharacterTextSplitter.from_language(
                            language=Language.CSHARP, chunk_size=1000, chunk_overlap=200
                        )
                    else:
                        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)

                    # ตัดคำ
                    chunks_data = splitter.create_documents([content])
                    
                    for i, chunk in enumerate(chunks_data):
                        documents.append({
                            "id": f"{relative_path}_{i}",
                            "text": chunk.page_content,
                            "source": relative_path
                        })
                        
                except Exception as e:
                    print(f"⚠️ Skipping {file}: {e}")

    # 4. แปลงเป็น Vector (Embedding) และส่งเข้า Pinecone แบบ Batch
    print(f"🧠 Embedding {len(documents)} chunks...")
    
    # เตรียมข้อมูลสำหรับ Upsert
    vectors_to_upsert = []
    
    # ใช้ Batch เพื่อลดการเรียก API ของ Gemini และ Pinecone
    for i, batch_docs in enumerate(batch_iterate(documents, BATCH_SIZE)):
        print(f"   Processing batch {i+1}...")
        
        # ดึงเฉพาะ Text ไปทำ Embedding
        texts = [doc['text'] for doc in batch_docs]
        
        try:
            # เรียก Gemini ครั้งเดียวได้หลาย Embedding (ประหยัดเวลา)
            embeddings = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=texts,
            )
            
            # จับคู่ Vector กับ Metadata
            for doc, embedding in zip(batch_docs, embeddings.embeddings):
                vectors_to_upsert.append({
                    "id": doc['id'],
                    "values": embedding.values,
                    "metadata": {"text": doc['text'], "source": doc['source']}
                })
        except Exception as e:
            print(f"❌ Error embedding batch: {e}")

    # 5. Upsert เข้า Pinecone ทีละก้อนใหญ่
    print(f"☁️ Uploading {len(vectors_to_upsert)} vectors to Pinecone...")
    for batch_vec in batch_iterate(vectors_to_upsert, BATCH_SIZE):
        index.upsert(vectors=batch_vec)

    # Clean up
    if os.path.exists(REPO_PATH):
        shutil.rmtree(REPO_PATH)
        
    print("✅ Ingestion Complete!")
    return {"status": "success", "chunks": len(documents)}