import os
import shutil
import git
import chromadb
import stat # <--- 1. ต้อง import อันนี้เพิ่ม
from google import genai

# Config
DB_PATH = "./chroma_db"
REPO_PATH = "./temp_repo"

# Init ChromaDB
chroma_client = chromadb.PersistentClient(path=DB_PATH)
collection = chroma_client.get_or_create_collection(name="codebase")

# <--- 2. เพิ่มฟังก์ชันช่วยลบไฟล์ Read-only บน Windows --->
def remove_readonly(func, path, _):
    """เปลี่ยนไฟล์ Read-only ให้เขียนได้ ก่อนสั่งลบ"""
    os.chmod(path, stat.S_IWRITE)
    func(path)

def get_embedding(text, client):
    """แปลงข้อความ เป็น list ตัวเลข (Vector) ด้วย Gemini"""
    result = client.models.embed_content(
        model="text-embedding-004",
        contents=text
    )
    return result.embeddings[0].values

def ingest_repo(repo_url: str, client: genai.Client):
    """
    1. Clone Repo
    2. อ่านไฟล์
    3. สร้าง Vector
    4. เก็บลง ChromaDB
    """
    # 1. Clear Old Data & Clone
    if os.path.exists(REPO_PATH):
        print("🗑️ Removing old repo...")
        # <--- 3. แก้ตรงนี้: ใส่ onerror=remove_readonly --->
        shutil.rmtree(REPO_PATH, onerror=remove_readonly)
    
    print(f"📥 Cloning {repo_url}...")
    git.Repo.clone_from(repo_url, REPO_PATH)

    # 2. Read Files (Walk through directory)
    documents = []
    metadatas = []
    ids = []
    
    print("📂 Processing files...")
    # Extensions ที่จะอ่าน
    allowed_ext = {'.py', '.js', '.ts', '.tsx', '.jsx', '.cs', '.java', '.html', '.css', '.md', '.json', '.cs'}
    
    for root, dirs, files in os.walk(REPO_PATH):
        # ข้าม folder ขยะ
        if 'node_modules' in root or '.git' in root or '__pycache__' in root:
            continue
            
        for file in files:
            ext = os.path.splitext(file)[1]
            if ext in allowed_ext:
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                        # สร้าง ID ไม่ซ้ำ
                        doc_id = file_path.replace(REPO_PATH, "")
                        
                        documents.append(content)
                        metadatas.append({"path": doc_id, "language": ext})
                        ids.append(doc_id)
                except Exception as e:
                    print(f"Skipping {file}: {e}")

    # 3. Create Embeddings & Save to DB
    if not documents:
        return {"status": "warning", "message": "ไม่พบไฟล์ Code ที่รองรับใน Repo นี้"}

    print(f"🧠 Embedding {len(documents)} files... (อาจใช้เวลา)")
    
    # ล้าง DB เก่าก่อน
    existing_ids = collection.get()['ids']
    if existing_ids:
        collection.delete(ids=existing_ids)

    # Loop add
    for i, doc in enumerate(documents):
        # ตัด content ยาวเกิน 
        truncated_doc = doc[:9000] 
        
        try:
            vector = get_embedding(truncated_doc, client)
            
            collection.add(
                ids=[ids[i]],
                embeddings=[vector],
                metadatas=[metadatas[i]],
                documents=[truncated_doc] 
            )
            print(f"   ✅ Indexed: {ids[i]}")
        except Exception as e:
            print(f"   ❌ Failed to embed {ids[i]}: {e}")

    return {"status": "success", "files_processed": len(documents)}

def query_codebase(query: str, client: genai.Client, n_results=3):
    """ค้นหาไฟล์ที่เกี่ยวข้องกับคำถาม"""
    # 1. แปลงคำถามเป็น Vector
    query_vector = get_embedding(query, client)
    
    # 2. Search ใน Chroma
    results = collection.query(
        query_embeddings=[query_vector],
        n_results=n_results
    )
    
    # 3. Format ผลลัพธ์กลับไป
    found_docs = []
    if results['documents']:
        for i, doc in enumerate(results['documents'][0]):
            meta = results['metadatas'][0][i]
            found_docs.append(f"--- File: {meta['path']} ---\n{doc}\n")
            
    return "\n".join(found_docs)