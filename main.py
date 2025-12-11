import os
import sys
import threading
import json
import re
import requests
import concurrent.futures
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
# 1. [แก้ไข] เพิ่ม ImageMessage ตรงนี้
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage

# 1. โหลด Config
load_dotenv()
line_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
line_secret = os.getenv('LINE_CHANNEL_SECRET')
gemini_key = os.getenv('GEMINI_API_KEY')
notion_key = os.getenv('NOTION_API_KEY')
notion_db_id = os.getenv('NOTION_DATABASE_ID')
NGROK_URL = "https://keiko-motivational-insuperably.ngrok-free.dev" # 👉 อย่าลืมแก้!

if not all([line_token, line_secret, gemini_key, notion_key, notion_db_id]):
    sys.exit(1)

# 2. Setup Models (ใช้ Lite เพื่อความเร็วสูงสุด)
genai.configure(api_key=gemini_key)
# หมายเหตุ: gemini-flash-latest รองรับรูปภาพอยู่แล้ว ไม่ต้องเปลี่ยน
chat_model = genai.GenerativeModel("gemini-flash-latest") 

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

headers = {"Authorization": f"Bearer {notion_key}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}

# --- Helper Functions (Notion) ---

def fetch_keyword_search(user_msg, user_id):
    """ค้นหา Keyword (Timeout สั้น)"""
    url = f"https://api.notion.com/v1/databases/{notion_db_id}/query"
    payload = {
        "filter": {
            "and": [
                {"property": "Idea", "rich_text": {"contains": user_msg}},
                {"property": "UserID", "rich_text": {"equals": user_id}}
            ]
        },
        "page_size": 1
    }
    try:
        # ⚡ Timeout แค่ 1.5 วินาที (มาช้าตัดทิ้ง)
        response = requests.post(url, json=payload, headers=headers, timeout=1.5) 
        results = response.json().get("results", [])
        if results:
            item = results[0]['properties']
            return f"ความทรงจำ: คุณเคยพูดว่า '{item['Idea']['title'][0]['text']['content']}' และฉันตอบว่า '{item['Feedback']['rich_text'][0]['text']['content']}'"
    except: pass
    return None

def fetch_recent_chat(user_id):
    """ดึงแชทล่าสุด (Timeout สั้น)"""
    url = f"https://api.notion.com/v1/databases/{notion_db_id}/query"
    payload = {
        "filter": {"property": "UserID", "rich_text": {"equals": user_id}},
        "sorts": [{"property": "Date", "direction": "descending"}],
        "page_size": 1
    }
    try:
        # ⚡ Timeout แค่ 1.5 วินาที
        response = requests.post(url, json=payload, headers=headers, timeout=1.5)
        results = response.json().get("results", [])
        if results:
            item = results[0]['properties']
            return f"บริบทล่าสุด: คุยเรื่อง '{item['Idea']['title'][0]['text']['content']}' ตอบว่า '{item['Feedback']['rich_text'][0]['text']['content']}'"
    except: pass
    return None

def get_smart_memory_fast(user_msg, user_id):
    """
    🏎️ ระบบความจำแบบ Speed-First:
    ให้เวลา Notion แค่ 1.5 วินาที ถ้าไม่ทันคือข้ามเลย เน้นตอบเร็วก่อน
    """
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_keyword = executor.submit(fetch_keyword_search, user_msg, user_id)
        future_recent = executor.submit(fetch_recent_chat, user_id)

        try:
            # รอแค่ 1.5 วินาทีเท่านั้น! (ลดจาก 4)
            keyword_result = future_keyword.result(timeout=1.5)
            recent_result = future_recent.result(timeout=1.5)
            
            if keyword_result: return keyword_result
            if recent_result: return recent_result
        except concurrent.futures.TimeoutError:
            print("⚠️ Memory Timeout: Notion ช้าเกินไป ข้าม!")
        except Exception as e:
            print(f"Memory Error: {e}")

    return "ไม่มีข้อมูล (เน้นตอบเร็ว)"

def save_to_notion(user_idea, ai_reply, user_id, category):
    """บันทึก Background"""
    print(f"💾 Background Save: {category}")
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": notion_db_id},
        "properties": {
            "Idea": {"title": [{"text": {"content": user_idea}}]},
            "Feedback": {"rich_text": [{"text": {"content": ai_reply[:2000]}}]},
            "UserID": {"rich_text": [{"text": {"content": user_id}}]},
            "Category": {"select": {"name": category}}, 
            "Date": {"date": {"start": datetime.now().isoformat()}}
        }
    }
    try: requests.post(url, json=payload, headers=headers)
    except: pass

def clean_json_string(json_str):
    cleaned = re.sub(r'```json\s*', '', json_str)
    cleaned = re.sub(r'```', '', cleaned)
    return cleaned.strip()

# --- System Prompt (อันเดิมที่ลูกพี่แก้ให้แล้ว) ---
SYSTEM_PROMPT = """
Role: You are "IdeaPartner", a sincere and supportive business partner (Friendly & Witty).
Mindset: Based on Dale Carnegie + Positive Psychology:
1. Show genuine interest in the user.
2. Be a good listener & Show empathy.
3. Don't judge, just support.
4. Growth Mindset.

rules_language:
**CRITICAL:** Detect the user's input language and respond in the **SAME** language.

Mode 1: If User speaks THAI 🇹🇭
- Tone: "Modern Thai Friend 2024" (เพื่อนสนิทคนไทย)
- Style: Casual, fun, sincere, use Thai particles (e.g., ว่ะ, เนอะ, สิ, เว้ย).
- No translationese: Use natural Thai slang.

Mode 2: If User speaks ENGLISH 🇺🇸
- Tone: "Friendly American Creator/Founder"
- Style: Casual, energetic, concise. Use words like "Dude", "Man", "Gotcha", "Totally".
- No textbook English: Make it sound natural and spoken.

General Rules (For both languages):
1. **Length:** Short & Punchy! (Max 3-4 lines).
2. **Business/Productivity:** Praise first (Dale Carnegie) -> Then ask a thought-provoking question.
3. **Self-Dev (Sad/Burnout):** Empathy first! Comfort them. No teaching.
4. **Off-topic:** Politely decline in a friendly way.
5. **Memory:**
   - If [Memory] says "Past/History": Greet them like an old friend ("Hey! I remember you wanted to sell...")
   - If [Memory] says "Recent/Context": Continue the conversation smoothly.

Output Format (JSON Only):
{
  "category": "Choose from: Business / Productivity / Self-Dev / Off-topic / Finance",
  "reply": "Your response string (in the detected language)"
}
"""

app = FastAPI()
# แทรกตรงนี้ก่อน app.mount
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")
line_bot_api = LineBotApi(line_token)
handler = WebhookHandler(line_secret)

@app.get("/")
async def root(): return {"status": "Active", "mode": "Speed King (1.5s Timeout) + Vision Ready"}

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get('X-Line-Signature', '')
    body = await request.body()
    try: handler.handle(body.decode('utf-8'), signature)
    except InvalidSignatureError: raise HTTPException(status_code=400)
    return 'OK'

# ---------------------------------------------------------
# ส่วนเดิม: จัดการข้อความ (Text)
# ---------------------------------------------------------
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text
    user_id = event.source.user_id
    reply_token = event.reply_token
    
    try:
        # 1. Parallel Memory Fetch (Timeout 1.5s)
        memory_context = get_smart_memory_fast(user_msg, user_id)
        
        # 2. Gemini Thinking
        full_prompt = f"{SYSTEM_PROMPT}\n\n[Memory]\n{memory_context}\n\n[Input]\n{user_msg}\n\nResponse (JSON):"
        
        response = chat_model.generate_content(
            full_prompt, 
            safety_settings=safety_settings
        )
        
        raw_reply = response.text.strip()
        print(f"🤖 AI (Text): {raw_reply[:30]}...") 

        # 3. Clean JSON
        try:
            cleaned_json = clean_json_string(raw_reply)
            data = json.loads(cleaned_json)
            category = data.get("category", "General") 
            ai_reply = data.get("reply", "โทษที เบลอนิดหน่อย เอาใหม่นะ")
        except:
            category = "General"
            ai_reply = raw_reply

        # 4. ตอบทันที!
        line_bot_api.reply_message(reply_token, TextSendMessage(text=ai_reply))
        
        # 5. Save Background
        if category != "Off-topic":
            bg_thread = threading.Thread(
                target=save_to_notion, 
                args=(user_msg, ai_reply, user_id, category)
            )
            bg_thread.start()

    except Exception as e:
        print(f"Error: {e}")

# ---------------------------------------------------------
# [ใหม่] ส่วนจัดการรูปภาพ (Image) สำหรับส่งประกวด!
# ---------------------------------------------------------
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    reply_token = event.reply_token
    try:
        print("📸 Received Image...")
        
        # 1. ดึงไฟล์รูปจาก LINE Server
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = message_content.content
        
        # 2. สร้าง Prompt สำหรับ Vision โดยเฉพาะ
        vision_prompt = """
        Role: You are "IdeaPartner" (AI Life Coach).
        Task: Analyze this image and respond based on context:
        
        Scenario A: If it's a messy room/desk:
        - Tease them gently (friendly joke).
        - Suggest 1 tiny step to organize (e.g., "Move that coffee cup first").
        
        Scenario B: If it's a notebook/handwriting/bills:
        - Analyze the numbers or content briefly.
        - Compliment their discipline in tracking/writing.
        
        Scenario C: Other images:
        - Just chat about it like a friend.
        
        Tone: Friendly, Witty, Encouraging (Thai Language).
        Output: Plain text (No JSON needed here, just the reply string).
        """
        
        # 3. เตรียมข้อมูลส่ง Gemini (Text + Image Bytes)
        image_part = {
            "mime_type": "image/jpeg",
            "data": image_bytes
        }
        
        # 4. ยิงไปหา Gemini
        response = chat_model.generate_content(
            [vision_prompt, image_part],
            safety_settings=safety_settings
        )
        
        ai_reply = response.text.strip()
        print(f"🤖 AI (Vision): {ai_reply}")
        
        # 5. ตอบกลับ LINE
        line_bot_api.reply_message(reply_token, TextSendMessage(text=ai_reply))
        
    except Exception as e:
        print(f"Vision Error: {e}")
        line_bot_api.reply_message(reply_token, TextSendMessage(text="โทษทีเพื่อน เน็ตไม่ดี มองไม่เห็นรูปเลย 😵‍💫"))
