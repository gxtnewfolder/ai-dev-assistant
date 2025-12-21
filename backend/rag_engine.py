import os
import shutil
import git
import chromadb
import stat
from google import genai
import json

# Config
DB_PATH = "./chroma_db"
REPO_PATH = "./temp_repo"

# Init ChromaDB
chroma_client = chromadb.PersistentClient(path=DB_PATH)
collection = chroma_client.get_or_create_collection(name="codebase")

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
    if os.path.exists(REPO_PATH):
        print("🗑️ Removing old repo...")
        shutil.rmtree(REPO_PATH, onerror=remove_readonly)
    
    print(f"📥 Cloning {repo_url}...")
    git.Repo.clone_from(repo_url, REPO_PATH)

    documents = []
    metadatas = []
    ids = []
    
    print("📂 Processing files...")
    allowed_ext = {'.py', '.js', '.ts', '.tsx', '.jsx', '.cs', '.java', '.html', '.css', '.md', '.json', '.go', '.rs'}
    
    for root, dirs, files in os.walk(REPO_PATH):
        if 'node_modules' in root or '.git' in root or '__pycache__' in root or 'dist' in root or 'build' in root:
            continue
            
        for file in files:
            ext = os.path.splitext(file)[1]
            if ext in allowed_ext:
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        doc_id = file_path.replace(REPO_PATH, "")
                        
                        # Chunking: ถ้าไฟล์ใหญ่เกิน 2000 ตัวอักษร ให้ตัดแบ่ง (Simple Chunking)
                        chunk_size = 2000
                        for i in range(0, len(content), chunk_size):
                            chunk = content[i:i+chunk_size]
                            chunk_id = f"{doc_id}_part{i//chunk_size}"
                            
                            # เพิ่ม Context ชื่อไฟล์ไปในเนื้อหาด้วย เพื่อให้ Vector จับคู่ได้ดีขึ้น
                            enriched_content = f"File: {doc_id}\nCode:\n{chunk}"

                            documents.append(enriched_content)
                            metadatas.append({"path": doc_id, "language": ext})
                            ids.append(chunk_id)

                except Exception as e:
                    print(f"Skipping {file}: {e}")

    if not documents:
        return {"status": "warning", "message": "ไม่พบไฟล์ Code ที่รองรับใน Repo นี้"}

    print(f"🧠 Embedding {len(documents)} chunks... (อาจใช้เวลา)")
    
    existing_ids = collection.get()['ids']
    if existing_ids:
        collection.delete(ids=existing_ids)

    # Batch Process (เพื่อความเร็ว)
    batch_size = 50
    for i in range(0, len(documents), batch_size):
        batch_docs = documents[i:i+batch_size]
        batch_ids = ids[i:i+batch_size]
        batch_meta = metadatas[i:i+batch_size]
        
        try:
            # ใช้ loop embed ทีละตัวเพื่อกัน error limit (ถ้า production ควรใช้ batch embed)
            batch_embeddings = [get_embedding(doc, client) for doc in batch_docs]
            
            collection.add(
                ids=batch_ids,
                embeddings=batch_embeddings,
                metadatas=batch_meta,
                documents=batch_docs
            )
            print(f"   ✅ Indexed batch {i} - {i+len(batch_docs)}")
        except Exception as e:
            print(f"   ❌ Failed batch {i}: {e}")

    return {"status": "success", "files_processed": len(documents)}

# 🔥 FEATURE ใหม่: Query Expansion
def expand_query(original_query: str, client: genai.Client):
    """ใช้ AI คิด Keyword เพิ่มเติมที่เกี่ยวข้องกับ Code"""
    prompt = f"""
    You are an expert software engineer.
    The user is searching for code in a repository.
    Generate 3-5 technical keywords or related terms that might appear in the codebase for this query.
    
    User Query: "{original_query}"
    
    Output ONLY a JSON list of strings. Example: ["auth", "login_controller", "jwt_token"]
    """
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config={'response_mime_type': 'application/json'}
        )
        keywords = json.loads(response.text)
        return keywords
    except:
        return [original_query] # ถ้า error ให้ใช้คำเดิม

def query_codebase(query: str, client: genai.Client, n_results=5):
    """Smart Search: หาด้วย Query เดิม + Expanded Keywords"""
    
    # 1. Expand Query
    print(f"🔎 Expanding query: {query}")
    keywords = expand_query(query, client)
    search_terms = [query] + keywords
    print(f"   Keywords: {search_terms}")

    # 2. Search ทุกคำ (รวมผลลัพธ์)
    all_results = {} # ใช้ Dict เพื่อตัดตัวซ้ำ (Deduplicate)
    
    for term in search_terms:
        term_vector = get_embedding(term, client)
        results = collection.query(
            query_embeddings=[term_vector],
            n_results=2 # เอาคำละ 2 ไฟล์พอ เดี๋ยวเยอะเกิน
        )
        
        if results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                doc_id = results['ids'][0][i]
                if doc_id not in all_results:
                    all_results[doc_id] = {
                        "content": doc,
                        "metadata": results['metadatas'][0][i],
                        "score": results['distances'][0][i] if results['distances'] else 0
                    }

    # 3. Sort by relevance (Distance น้อย = เหมือนมาก)
    sorted_docs = sorted(all_results.values(), key=lambda x: x['score'])
    
    # 4. Format Output (เอา top 5 ที่ดีที่สุดจากทุก Keyword รวมกัน)
    final_context = []
    for item in sorted_docs[:n_results]:
        meta = item['metadata']
        final_context.append(f"--- File: {meta['path']} ---\n{item['content']}\n")
            
    return "\n".join(final_context)