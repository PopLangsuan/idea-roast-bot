import os
import requests
from datetime import datetime
from dotenv import load_dotenv

# 1. โหลดค่า
load_dotenv()
notion_key = os.getenv('NOTION_API_KEY')
notion_db_id = os.getenv('NOTION_DATABASE_ID')

print(f"🔑 Token: {notion_key[:5]}...xxxx")
print(f"📂 DB ID: {notion_db_id}")

# 2. เตรียมข้อมูลทดสอบ
headers = {
    "Authorization": f"Bearer {notion_key}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

url = "https://api.notion.com/v1/pages"

payload = {
    "parent": {"database_id": notion_db_id},
    "properties": {
        # ลองเช็คชื่อคอลัมน์ดีๆ นะครับ
        "Idea": {
            "title": [{"text": {"content": "Test Idea (Debug Mode)"}}]
        },
        "Feedback": {
            "rich_text": [{"text": {"content": "Test Feedback"}}]
        },
        "UserID": {
            "rich_text": [{"text": {"content": "AdminDebug"}}]
        },
        "Date": {
            "date": {"start": datetime.now().isoformat()}
        }
    }
}

# 3. ยิงข้อมูลจริง และ *อ่านคำตอบ*
print("-" * 30)
print("กำลังส่งข้อมูลไป Notion...")
response = requests.post(url, json=payload, headers=headers)

print(f"สถานะ (Status Code): {response.status_code}")
print(f"ผลลัพธ์จาก Notion: {response.text}")
print("-" * 30)