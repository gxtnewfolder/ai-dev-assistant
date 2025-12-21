import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from dotenv import load_dotenv
import rag_engine

# 1. Setup Environment & AI Client
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("ไม่พบ GEMINI_API_KEY ในไฟล์ .env")

client = genai.Client(api_key=api_key)

# 2. Setup FastAPI App
app = FastAPI(title="AI Developer Assistant API")

# 3. Setup CORS (เพื่อให้ Frontend ที่รันคนละ Port เรียกมาหา Backend ได้)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # ใน Production ควรเปลี่ยนเป็น domain ของ frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Define Data Model (กำหนดหน้าตาข้อมูลที่จะรับเข้ามา)
class StoryRequest(BaseModel):
    story_text: str
    
class RepoRequest(BaseModel):
    repo_url: str

class ChatRequest(BaseModel):
    question: str

# 5. API Endpoints
@app.get("/")
def read_root():
    return {"status": "ok", "message": "AI Assistant Backend is running!"}

@app.post("/analyze-story")
def analyze_story(request: StoryRequest):
    """
    รับ Jira Story Text -> ส่งให้ AI -> คืนค่าเป็น Markdown
    """
    try:
        # Prompt เดิมที่เราเทสผ่านแล้ว
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
        
        # เรียก AI
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=system_prompt + request.story_text
        )
        
        # ส่งผลลัพธ์กลับไป
        return {
            "success": True,
            "markdown_result": response.text
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ingest")
def ingest_repository(request: RepoRequest):
    """รับ GitHub URL -> ดูด Code -> เก็บเข้าสมอง"""
    try:
        result = rag_engine.ingest_repo(request.repo_url, client)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/ask-codebase")
def ask_codebase(request: ChatRequest):
    """ถามคำถาม -> ค้น Code -> ให้ AI ตอบ (รองรับ Smart Commands)"""
    try:
        # 1. ค้นหา Code ที่เกี่ยวข้อง (RAG)
        context = rag_engine.query_codebase(request.question, client)
        
        if not context:
            return {"answer": "ไม่พบ Code ที่เกี่ยวข้องใน Repo นี้ครับ (ลอง Load Repo ใหม่ดูนะ)"}

        # 2. แยกแยะ Smart Commands
        user_query = request.question.strip()
        
        # Default Persona
        role_prompt = "You are a Senior Developer. Answer the question based ONLY on the provided code context."
        
        # Smart Personas
        if user_query.lower().startswith("/refactor"):
            role_prompt = """
            You are a Clean Code Expert & Architect.
            Your goal is to REFACTOR the provided code to be cleaner, faster, and more maintainable.
            - Suggest specific improvements (SOLID principles, DRY).
            - Show the 'Before' vs 'After' code comparison.
            """
        elif user_query.lower().startswith("/test"):
            role_prompt = """
            You are a QA Automation Engineer.
            Your goal is to WRITE UNIT TESTS for the provided code.
            - Use the most popular testing framework for the language (e.g., Jest for JS, Pytest for Python).
            - Cover edge cases and happy paths.
            """
        elif user_query.lower().startswith("/security"):
            role_prompt = """
            You are a Cyber Security Expert.
            Analyze the provided code for security vulnerabilities (OWASP Top 10).
            - Highlight SQL Injection, XSS, weak auth, etc.
            - Suggest how to patch them securely.
            """
        elif user_query.lower().startswith("/explain"):
             role_prompt = """
            You are a Computer Science Teacher.
            Explain the provided code logic step-by-step in simple terms.
            - Use analogies.
            - Explain WHY this code exists.
            """

        # 3. สร้าง Prompt ผสม Rules เดิม (Mermaid)
        prompt = f"""
        {role_prompt}
        
        IMPORTANT RULES FOR DIAGRAMS:
        1. If the user asks for a diagram OR if it helps explain complex logic, use **Mermaid.js**.
        2. Always use `flowchart TD` (do not use `graph TD`).
        3. Do NOT use semicolons `;` at the end of lines.
        4. Wrap all label text in double quotes, e.g., A["Label Text"].
        
        User Query: {user_query}
        
        Code Context:
        {context}
        """
        
        # 4. ให้ AI ตอบ
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        
        return {
            "answer": response.text,
            "context_used": context
        }

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))