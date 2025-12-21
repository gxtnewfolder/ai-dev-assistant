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
    """ถามคำถาม -> ค้น Code -> ให้ AI ตอบ"""
    try:
        # 1. ค้นหา Code ที่เกี่ยวข้อง (RAG)
        context = rag_engine.query_codebase(request.question, client)
        
        if not context:
            return {"answer": "ไม่พบ Code ที่เกี่ยวข้องใน Repo นี้ครับ"}

        # 2. สร้าง Prompt ผสม Code
        prompt = f"""
        You are a Senior Developer. Answer the question based ONLY on the provided code context.
        
        IMPORTANT RULES FOR DIAGRAMS:
        1. If the user asks for a diagram, use **Mermaid.js** syntax.
        2. Always use `flowchart TD` (do not use `graph TD`).
        3. Do NOT use semicolons `;` at the end of lines.
        4. Wrap all label text in double quotes, e.g., A["Label Text"].
        5. Do NOT add any explanations or text INSIDE the code block.

        Question: {request.question}
        
        Code Context:
        {context}
        """
        
        # 3. ให้ AI ตอบ
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        
        return {
            "answer": response.text,
            "context_used": context # ส่งกลับไปโชว์หน้าเว็บได้ว่าเอาไฟล์ไหนมาตอบ
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))