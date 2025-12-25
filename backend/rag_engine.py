import os
import shutil
import git
import time
from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
from google import genai
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# 1. โหลด Environment Variables
load_dotenv()

# 2. Config ค่าต่างๆ
REPO_PATH = "./temp_repo"
EMBEDDING_MODEL = "text-embedding-004"
PINECONE_INDEX_NAME = "codebase"
BATCH_SIZE = 100 

# 3. เริ่มต้น Pinecone
api_key = os.environ.get("PINECONE_API_KEY")
if not api_key:
    # ใน Cloud Run อาจจะยังไม่มี ENV ตอน Init ไฟล์นี้ ให้ข้ามไปก่อน (ไป Init ใน main.py แทน)
    pass 

# Init Client แบบ Global (เดี๋ยว main.py จะเป็นคนเรียกใช้)
pc = None
index = None
client = None

# พยายาม Init ถ้ามี Key อยู่แล้ว
if api_key:
    pc = Pinecone(api_key=api_key)
    if PINECONE_INDEX_NAME not in pc.list_indexes().names():
        try:
            pc.create_index(
                name=PINECONE_INDEX_NAME,
                dimension=768,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1")
            )
        except Exception as e:
            print(f"Index creation skipped/failed: {e}")
    index = pc.Index(PINECONE_INDEX_NAME)

client = None
if os.environ.get("GEMINI_API_KEY"):
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))


# --- Helper Function ---
def batch_iterate(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# ✅ ปรับแก้ฟังก์ชันรับ session_id
def ingest_repo(repo_url: str, session_id: str):
    """โหลด Repo โดยผูกติดกับ Session ID"""
    print(f"🚀 Starting ingestion for Session: {session_id}")
    
    # Re-init clients if needed (in case globals are None)
    local_pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
    local_index = local_pc.Index(PINECONE_INDEX_NAME)
    local_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    # 1. ลบความจำเก่า *เฉพาะของ Session นี้* ทิ้ง (Session อื่นไม่กระทบ)
    try:
        print(f"🧹 Clearing old memory for session: {session_id}...")
        # 🔥 Feature เด็ด: ลบเฉพาะข้อมูลที่ติดป้าย session_id นี้
        local_index.delete(filter={"session_id": session_id})
        time.sleep(2)
    except Exception as e:
        print(f"⚠️ Note: Clean up failed (maybe empty): {e}")

    # 2. Clone Repo
    if os.path.exists(REPO_PATH):
        shutil.rmtree(REPO_PATH)

    print("📥 Cloning repository (Depth=1)...")
    git.Repo.clone_from(repo_url, REPO_PATH, depth=1)

    documents = []
    print("📂 Processing files...")
    
    for root, dirs, files in os.walk(REPO_PATH):
        if '.git' in dirs: dirs.remove('.git')
        if 'node_modules' in dirs: dirs.remove('node_modules')
        
        for file in files:
            file_path = os.path.join(root, file)
            # รองรับไฟล์หลายประเภท
            if file.endswith(('.py', '.js', '.jsx', '.ts', '.tsx', '.md', '.txt', '.html', '.css', '.java', '.cs', '.go', '.php')):
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        
                    relative_path = os.path.relpath(file_path, REPO_PATH)
                    
                    splitter = RecursiveCharacterTextSplitter(
                        chunk_size=1000, 
                        chunk_overlap=200,
                        separators=["\n\n", "\n", " ", ""]
                    )

                    chunks_data = splitter.create_documents([content])
                    
                    for i, chunk in enumerate(chunks_data):
                        documents.append({
                            # ✅ ใส่ session_id ใน ID เพื่อความ Unique
                            "id": f"{session_id}_{relative_path}_{i}", 
                            "text": chunk.page_content,
                            "source": relative_path
                        })
                except Exception:
                    pass

    # 3. Embed & Upsert
    print(f"🧠 Embedding {len(documents)} chunks...")
    vectors_to_upsert = []
    
    for i, batch_docs in enumerate(batch_iterate(documents, BATCH_SIZE)):
        texts = [doc['text'] for doc in batch_docs]
        try:
            embeddings = local_client.models.embed_content(
                model=EMBEDDING_MODEL, 
                contents=texts
            )
            
            for doc, embedding in zip(batch_docs, embeddings.embeddings):
                vectors_to_upsert.append({
                    "id": doc['id'],
                    "values": embedding.values,
                    "metadata": {
                        "text": doc['text'], 
                        "source": doc['source'],
                        "session_id": session_id 
                    }
                })
        except Exception as e:
            print(f"❌ Error embedding batch: {e}")

    print(f"☁️ Uploading vectors...")
    for batch_vec in batch_iterate(vectors_to_upsert, BATCH_SIZE):
        local_index.upsert(vectors=batch_vec)

    if os.path.exists(REPO_PATH):
        shutil.rmtree(REPO_PATH)
        
    return {"status": "success", "chunks": len(documents), "session_id": session_id}