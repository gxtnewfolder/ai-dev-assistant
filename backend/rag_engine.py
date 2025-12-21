import os
import shutil
import git
import stat
import json
import time
from google import genai
from pinecone import Pinecone, ServerlessSpec
from dotenv import load_dotenv

load_dotenv()

# Config
REPO_PATH = "./temp_repo"
MODEL_NAME = "gemini-2.5-flash"  # ใช้ Model ล่าสุด
EMBEDDING_MODEL = "text-embedding-004"
PINECONE_INDEX_NAME = "codebase"

# Init Pinecone
# ต้องตั้ง Environment Variable: PINECONE_API_KEY
pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))

# Connect to Index
index = pc.Index(PINECONE_INDEX_NAME)

def remove_readonly(func, path, _):
    """เปลี่ยนไฟล์ Read-only ให้เขียนได้ ก่อนสั่งลบ"""
    os.chmod(path, stat.S_IWRITE)
    func(path)

def get_embedding(text, client):
    """แปลงข้อความ เป็น Vector (768 Dimensions)"""
    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text
    )
    return result.embeddings[0].values

def ingest_repo(repo_url: str, client: genai.Client):
    """Clone Repo -> Embed -> Upsert to Pinecone"""
    
    # 1. Clear Local Temp Repo (Stateless)
    if os.path.exists(REPO_PATH):
        print("🗑️ Removing old local repo...")
        shutil.rmtree(REPO_PATH, onerror=remove_readonly)
    
    print(f"📥 Cloning {repo_url}...")
    git.Repo.clone_from(repo_url, REPO_PATH)

    # 2. Reset Pinecone Index (ล้างความจำเก่าก่อนโหลด Repo ใหม่)
    # หมายเหตุ: ใน Production จริงอาจใช้วิธีแยก Namespace แทนการลบทั้ง Index
    print("🧹 Cleaning old vectors in Pinecone...")
    try:
        index.delete(delete_all=True) 
    except Exception as e:
        print(f"Warning clearing index: {e}")

    documents = []
    
    print("📂 Processing files...")
    allowed_ext = {'.py', '.js', '.ts', '.tsx', '.jsx', '.cs', '.java', '.html', '.css', '.md', '.json', '.go', '.rs', '.yaml', '.yml'}
    
    vectors_to_upsert = []
    
    for root, dirs, files in os.walk(REPO_PATH):
        if 'node_modules' in root or '.git' in root or '__pycache__' in root:
            continue
            
        for file in files:
            ext = os.path.splitext(file)[1]
            if ext in allowed_ext:
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        doc_path = file_path.replace(REPO_PATH, "")
                        
                        # Chunking Strategy
                        chunk_size = 2000
                        for i in range(0, len(content), chunk_size):
                            chunk = content[i:i+chunk_size]
                            chunk_id = f"{doc_path}_part{i//chunk_size}"
                            
                            # Context rich text
                            enriched_content = f"File: {doc_path}\nCode:\n{chunk}"
                            
                            # Create Embedding
                            vector = get_embedding(enriched_content, client)
                            
                            # Prepare for Pinecone (ID, Vector, Metadata)
                            vectors_to_upsert.append({
                                "id": chunk_id,
                                "values": vector,
                                "metadata": {
                                    "path": doc_path,
                                    "content": enriched_content, # เก็บเนื้อหาไว้ใน Metadata เลย (Cloud Run จะได้ไม่ต้องอ่านไฟล์)
                                    "language": ext
                                }
                            })

                except Exception as e:
                    print(f"Skipping {file}: {e}")

    if not vectors_to_upsert:
        return {"status": "warning", "message": "No valid code files found."}

    print(f"🧠 Upserting {len(vectors_to_upsert)} chunks to Pinecone...")
    
    # Batch Upsert (Pinecone แนะนำทีละ 100-200)
    batch_size = 100
    for i in range(0, len(vectors_to_upsert), batch_size):
        batch = vectors_to_upsert[i:i+batch_size]
        try:
            index.upsert(vectors=batch)
            print(f"   ✅ Upserted batch {i} - {i+len(batch)}")
        except Exception as e:
            print(f"   ❌ Failed batch {i}: {e}")

    return {"status": "success", "chunks_processed": len(vectors_to_upsert)}

def expand_query(original_query: str, client: genai.Client):
    """Query Expansion (เหมือนเดิม)"""
    prompt = f"""
    Generate 3 technical keywords for finding code related to: "{original_query}"
    Output JSON list of strings only.
    """
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config={'response_mime_type': 'application/json'}
        )
        return json.loads(response.text)
    except:
        return [original_query]

def query_codebase(query: str, client: genai.Client, n_results=5):
    """Search using Pinecone"""
    
    # 1. Expand Query
    print(f"🔎 Expanding query: {query}")
    keywords = expand_query(query, client)
    search_terms = [query] + keywords
    print(f"   Keywords: {search_terms}")

    all_matches = {}
    
    # 2. Vector Search for each term
    for term in search_terms:
        term_vector = get_embedding(term, client)
        
        results = index.query(
            vector=term_vector,
            top_k=2,
            include_metadata=True # ดึงเนื้อหา Code กลับมาด้วย
        )
        
        for match in results['matches']:
            doc_id = match['id']
            if doc_id not in all_matches:
                all_matches[doc_id] = {
                    "content": match['metadata']['content'],
                    "path": match['metadata']['path'],
                    "score": match['score']
                }

    # 3. Sort & Format
    sorted_docs = sorted(all_matches.values(), key=lambda x: x['score'], reverse=True)
    
    final_context = []
    for item in sorted_docs[:n_results]:
        final_context.append(f"--- File: {item['path']} ---\n{item['content']}\n")
            
    return "\n".join(final_context)