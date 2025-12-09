import os
import google.generativeai as genai
from dotenv import load_dotenv

# โหลดกุญแจ
load_dotenv()
api_key = os.getenv('GEMINI_API_KEY')
genai.configure(api_key=api_key)

print("กำลังค้นหาโมเดลที่ใช้ได้... (กรุณารอสักครู่)")
print("-" * 30)

try:
    # สั่งให้ลิสต์รายชื่อโมเดลทั้งหมดออกมา
    for m in genai.list_models():
        # กรองเอาเฉพาะตัวที่ทำ Chat ได้ (generateContent)
        if 'generateContent' in m.supported_generation_methods:
            print(f"✅ พบโมเดล: {m.name}")
except Exception as e:
    print(f"❌ Error: {e}")

print("-" * 30)