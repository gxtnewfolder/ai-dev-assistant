import os
from google import genai
from dotenv import load_dotenv

# 1. Load API Key
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("Error: ไม่พบ API Key กรุณาเช็คไฟล์ .env")
    exit()

# 2. สร้าง Client (Syntax ใหม่)
client = genai.Client(api_key=api_key)

# 3. เตรียม Input (Jira Story)
jira_story = """
Title: User Registration with Email Verification
Description:
As a new user, I want to register an account using my email and password,
so that I can access the system.
Acceptance Criteria:
- User inputs email, password, confirm password.
- System validates email format.
- Password must be at least 8 chars, 1 uppercase, 1 special char.
- System sends a verification email with a link.
- User cannot login until verified.
"""

# 4. System Prompt
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

try:
    print("Thinking... กำลังวิเคราะห์ Story (ด้วย SDK ใหม่)...")
    
    # 5. ยิงคำสั่ง (Syntax ใหม่: models.generate_content)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=system_prompt + jira_story
    )

    # 6. ดูผลลัพธ์
    print("\n--- AI Response ---")
    print(response.text)

except Exception as e:
    print(f"\nError เกิดข้อผิดพลาด: {e}")