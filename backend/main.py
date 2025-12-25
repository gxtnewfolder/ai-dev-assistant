from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import rag_engine
import os
from dotenv import load_dotenv
from pinecone import Pinecone
from google import genai
import logging

load_dotenv()

# Setup Clients & Logging
client = None
pc = None
index = None
logger = logging.getLogger("backend")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AI Developer Assistant API")

@app.on_event("startup")
def startup_event():
    global client, pc, index
    gemini_key = os.environ.get("GEMINI_API_KEY")
    pinecone_key = os.environ.get("PINECONE_API_KEY")

    if gemini_key:
        client = genai.Client(api_key=gemini_key)
    
    if pinecone_key:
        pc = Pinecone(api_key=pinecone_key)
        index = pc.Index(rag_engine.PINECONE_INDEX_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ อัปเดต Model ให้รับ session_id
class RepoRequest(BaseModel):
    repo_url: str
    session_id: str 

class ChatRequest(BaseModel):
    question: str
    session_id: str

@app.get("/")
def read_root():
    return {"status": "ok", "message": "🚀 AI Assistant Backend (Multi-Session Support) is running!"}

@app.post("/ingest")
async def ingest_repository(request: RepoRequest):
    try:
        # ✅ ส่ง session_id ไปให้ rag_engine
        result = rag_engine.ingest_repo(request.repo_url, request.session_id)
        return result
    except Exception as e:
        print(f"Ingest Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ask-codebase")
async def ask_codebase(request: ChatRequest):
    try:
        if not client or not index:
             raise HTTPException(status_code=500, detail="AI Services not initialized")

        user_query = request.question.strip()

        # 1. Embed คำถาม
        question_embedding = client.models.embed_content(
            model="text-embedding-004",
            contents=user_query
        )

        # 2. ค้นหาแบบมี Filter (สำคัญมาก! 🔥)
        search_results = index.query(
            vector=question_embedding.embeddings[0].values,
            top_k=5, 
            include_metadata=True,
            filter={"session_id": request.session_id} 
        )

        context_text = ""
        found_sources = []
        for match in search_results.matches:
            if match.score > 0.40:
                context_text += f"\n--- File: {match.metadata.get('source')} ---\n{match.metadata.get('text')}\n"
                found_sources.append(match.metadata.get('source'))

        if not context_text:
            context_text = "No relevant code found in this session context."

        # Persona Logic
        role_prompt = "You are a Senior Developer. Answer based on the Code Context below."
        if user_query.lower().startswith("/refactor"): role_prompt = "You are a Clean Code Expert."
        elif user_query.lower().startswith("/test"): role_prompt = "You are a QA Engineer."
        elif user_query.lower().startswith("/explain"): role_prompt = "You are a Teacher."

        prompt = f"""
        {role_prompt}
        
        User Question: {user_query}
        
        Code Context:
        {context_text}
        
        Answer (Be concise, use Markdown):
        """
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        
        return {"answer": response.text, "sources": list(set(found_sources))}

    except Exception as e:
        print(f"Chat Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))