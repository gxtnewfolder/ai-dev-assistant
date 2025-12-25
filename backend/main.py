from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import rag_engine
import os
from dotenv import load_dotenv
from pinecone import Pinecone
from google import genai

# 1. Setup Environment & AI Client
load_dotenv()

# ตรวจสอบ Key ก่อนเริ่ม
gemini_key = os.environ.get("GEMINI_API_KEY")
pinecone_key = os.environ.get("PINECONE_API_KEY")

if not gemini_key or not pinecone_key:
    raise ValueError("❌ Error: กรุณาใส่ GEMINI_API_KEY และ PINECONE_API_KEY ในไฟล์ .env หรือ Cloud Run Variables")

# Init Clients
client = genai.Client(api_key=gemini_key)
pc = Pinecone(api_key=pinecone_key)
index = pc.Index(rag_engine.PINECONE_INDEX_NAME)

# 2. Setup FastAPI App
app = FastAPI(title="AI Developer Assistant API")

# 3. Setup CORS (ปรับปรุงให้รองรับ Vercel และ Localhost)
app.add_middleware(
    CORSMiddleware,
    # ใส่ * เพื่อให้ Vercel เข้าได้แน่นอน (หรือจะระบุโดเมนเจาะจงก็ได้)
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Define Data Models
class StoryRequest(BaseModel):
    story_text: str

class RepoRequest(BaseModel):
    repo_url: str

class ChatRequest(BaseModel):
    question: str

# 5. API Endpoints

@app.get("/")
def read_root():
    return {"status": "ok", "message": "🚀 AI Assistant Backend is running (Optimized RAG)!"}

@app.post("/analyze-story")
def analyze_story(request: StoryRequest):
    """
    รับ Jira Story Text -> ส่งให้ AI -> คืนค่าเป็น Markdown
    """
    try:
        system_prompt = """
        You are a Senior Software Architect.
        Analyze the following Jira Story and break it down into technical sub-tasks.
        Format the output as Markdown.
        
        Provide the response in this structure:
        1.  **Frontend Tasks** (Angular/React)
        2.  **Backend Tasks** (.NET/Node.js)
        3.  **Database Changes**
        4.  **Test Cases**
        
        Here is the story:
        """
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=system_prompt + request.story_text
        )
        
        return {
            "success": True,
            "markdown_result": response.text
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ingest")
async def ingest_repository(request: RepoRequest):
    """
    รับ GitHub URL -> ดูด Code -> เก็บเข้าสมอง (Optimized Version)
    ใช้ rag_engine ตัวใหม่ที่ทำ Batching + Smart Splitting
    """
    try:
        # เรียกใช้ Engine ตัวใหม่ (ไม่ต้องส่ง client ไป เพราะ engine init เองแล้ว)
        result = rag_engine.ingest_repo(request.repo_url)
        return result
    except Exception as e:
        print(f"Ingest Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ask-codebase")
async def ask_codebase(request: ChatRequest):
    """
    RAG Search + Persona Generation
    """
    try:
        user_query = request.question.strip()

        # --- STEP 1: Search Logic (ทำใน main เพื่อคุม Logic ได้ง่าย) ---
        
        # 1. แปลงคำถามเป็น Vector
        question_embedding = client.models.embed_content(
            model="text-embedding-004",
            contents=user_query
        )

        # 2. ค้นหาใน Pinecone (ใช้ top_k=5 เพื่อความแม่นยำสูงสุด ไม่เยอะจน AI มึน)
        search_results = index.query(
            vector=question_embedding.embeddings[0].values,
            top_k=5, 
            include_metadata=True
        )

        # 3. สร้าง Context String
        context_text = ""
        found_sources = []
        for match in search_results.matches:
            if match.score > 0.45: # กรองขยะทิ้ง (ถ้าความเหมือนน้อยกว่า 45% ไม่เอา)
                context_text += f"\n--- File: {match.metadata.get('source', 'unknown')} ---\n{match.metadata.get('text', '')}\n"
                found_sources.append(match.metadata.get('source', 'unknown'))

        # ถ้าไม่เจอ Context ที่ดีพอ
        if not context_text:
            context_text = "No specific code found in the repository matching this question."

        # --- STEP 2: Persona Logic (ฟีเจอร์เด็ดของคุณ) ---
        
        role_prompt = "You are a Senior Developer. Answer the question based on the provided code context."
        
        if user_query.lower().startswith("/refactor"):
            role_prompt = "You are a Clean Code Expert. Refactor the code for better readability, performance, and maintainability."
        elif user_query.lower().startswith("/test"):
            role_prompt = "You are a QA Automation Engineer. Write comprehensive unit tests (using Pytest or Jest) for the code."
        elif user_query.lower().startswith("/security"):
            role_prompt = "You are a Security Auditor. Analyze the code for vulnerabilities (OWASP Top 10) and suggest fixes."
        elif user_query.lower().startswith("/explain"):
             role_prompt = "You are a Technical Instructor. Explain the logic step-by-step in simple terms."
        elif user_query.lower().startswith("/diagram"):
             role_prompt = "You are a System Architect. Create a Mermaid.js diagram (`flowchart TD` or `sequenceDiagram`) to visualize the flow."

        # --- STEP 3: Final Prompt Construction ---
        
        prompt = f"""
        {role_prompt}
        
        INSTRUCTIONS:
        1. Base your answer PRIMARILY on the "Code Context" provided below.
        2. If the context doesn't contain the answer, state that clearly. Do not make up code.
        3. Use Markdown formatting for code blocks.
        4. Be concise and to the point.
        
        User Question: {user_query}
        
        Code Context (Retrieved from Repo):
        {context_text}
        
        Answer:
        """
        
        # --- STEP 4: Generate Answer ---
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        
        return {
            "answer": response.text,
            "sources": list(set(found_sources)) # ส่งรายการไฟล์ที่เจอไปให้ Frontend ดูด้วย
        }

    except Exception as e:
        print(f"Chat Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))