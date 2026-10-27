import json
import time
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional

from config import GEMINI_API_KEY, GEMINI_MODELS

CURRENT_DATE_STR = "2026-10-12"

EXTRACTION_PROMPT = """คุณคือ AI ผู้เชี่ยวชาญด้านการวิเคราะห์ตารางเรียน การบ้าน และกำหนดการทางวิชาการที่มีความแม่นยำสูงสุด
วันที่และเวลาที่อาจารย์โพสต์ประกาศนี้ (Post Published Date): {post_date}
วันที่ปัจจุบันของระบบ (Today / Run Date): {current_date}

วิชา: "{course_name}"
ที่มา: {source}

หน้าที่ของคุณคือค้นหาเฉพาะ "งานที่มอบหมาย (Assignment), การบ้าน (Homework), โปรเจกต์ (Project), นัดหมายสำคัญ/บรีฟงานโปรเจกต์ (Project Briefing), นัดสอบกลางภาค/ปลายภาค (Midterm/Final Exam), ควิซ (Quiz), หรือนัดนำเสนอผลงาน (Presentation)"

กฎเหล็กด้านความแม่นยำสูงสุด (STRICT ACCURACY RULES - สำคัญมาก ห้ามผิดพลาด!):
1. **การคำนวณวันสัมพัทธ์ (Relative Date Resolution)**:
   - คำระบุวันสัมพัทธ์ เช่น "วันนี้ (Today)", "คืนนี้ (Tonight)", "พรุ่งนี้ (Tomorrow)", "เมื่อวาน (Yesterday)", "วันพุธนี้", "สัปดาห์หน้า", "คาบนี้"
     **ต้องคำนวณและอ้างอิงจาก {post_date} (วันที่โพสต์ประกาศ) เท่านั้น!**
     ห้ามอ้างอิงจากวันที่ปัจจุบัน {current_date} เป็นอันขาด!
   - ตัวอย่างชัดเจน:
     - หากประกาศโพสต์วันที่ "2026-10-05" แล้วเนื้อหาเขียนว่า "Today, we'll dive into AI Agents... See you on time at 12:00 PM"
       -> วันที่ของกิจกรรมคือ "2026-10-05" (วันที่ของโพสต์) ไม่ใช่วันที่ {current_date}!
2. **ห้ามเดาหรือมโนวันส่งงานเด็ดขาด (Never Hallucinate / Guess Dates)**:
   - หากในข้อความไม่ได้ระบุวันเวลาเดดไลน์ หรือวันกำหนดส่ง ไว้อย่างชัดเจน ห้ามเดาเอาเอง และห้ามใส่วันที่ปัจจุบัน {current_date} เด็ดขาด
   - หากไม่มีวันที่เดดไลน์แน่นอน ให้ใส่ "due_date": null, "due_time": null
3. **ประกาศที่ไม่ใช่งาน (Non-Task Filter)**:
   - สิ่งที่ต้องดึงเป็นกำหนดการ (VALID TASKS):
     - การบ้าน, งานที่มอบหมาย, ควิซ, นัดสอบกลางภาค/ปลายภาค
     - นัดนำเสนอโครงงาน/โปรเจกต์ (Project Presentation / Proposal)
     - นัดหมายบรีฟงาน (Project Briefing / Guidelines)
     - คลาสเรียนสดพิเศษ หรือ คลาสแบบ Synchronous (เช่น "Synchronous class for HR8", Google Meet Sessions) ที่มีวันและเวลาแน่นอน
     - บรรยายพิเศษโดยวิทยากรรับเชิญ (Special Guest Lecture) ที่มีวันเวลาห้องเรียนชัดเจน
     - กำหนดการสำคัญของมหาวิทยาลัย/รายวิชา (เช่น กำหนดการถอนรายวิชา W, วันสุดท้ายกรอกข้อมูลฝึกงาน)
   - สิ่งที่ไม่ใช่งาน ให้ตอบกลับเป็นลิสต์ว่าง [] ทันที:
     a) การทักทายทั่วไป หรือแนะนำตัวโดยไม่มีวันเวลานัดหมายกิจกรรม
     b) การแจ้งผลคะแนนสอบ, สถิติคะแนนสอบ (Midterm Exam Scores / Statistics)
     c) การแจ้งยกเลิกคลาสเรียน, งดคลาส, วันหยุด (Class cancelled / No class today)
     d) การแชร์สไลด์ สรุปเนื้อหา หรือลิงก์อ่านประกอบทั่วไป ที่ไม่มีคลาสเรียนสด นัดหมาย หรือการบ้านเดดไลน์
4. **การระบุเวลา (due_time)**:
   - หากมีการระบุเวลา เช่น "12:00 PM" ให้แปลงเป็นรูปแบบ 24 ชม. เช่น "12:00", "3:00 PM" ให้เป็น "15:00"
   - หากไม่ระบุเวลาแน่นอน ให้ใส่ "23:59"

ตอบกลับเฉพาะ JSON Array เท่านั้น ในรูปแบบ:
[
  {{
    "title": "ชื่องานหรือกำหนดการ",
    "task_type": "ส่งงาน/การบ้าน / นัดหมาย/บรีฟงาน / นัดนำเสนอ/Present / นัดสอบ / ควิซ",
    "due_date": "YYYY-MM-DD หรือ null",
    "due_time": "HH:MM หรือ null",
    "end_time": "HH:MM หรือ null (หากระบุช่วงเวลา เช่น 09.00 - 16.00 ให้ใส่ '16:00')",
    "location": "สถานที่จัดกิจกรรม เช่น ห้องเรียน อาคาร C4 หรือ ลิงก์ออนไลน์ หรือ null",
    "raw_deadline": "ข้อความกำหนดวันเวลาเดิมที่อาจารย์เขียน",
    "description": "รายละเอียดสิ่งที่ต้องทำ",
    "summary_thai": "สรุปภาษาไทย 1-2 ประโยค",
    "summary_english": "English summary 1-2 sentences"
  }}
]
"""

def extract_tasks_from_text(text: str, course_name: str, source: str, post_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Analyze announcements or document text using Gemini to detect informal assignments and deadlines with strict accuracy"""
    clean_text = (text or "").strip()
    if len(clean_text) < 15:
        return []

    # Filter out obvious non-task announcements to save API calls
    keywords = [
        "งาน", "การบ้าน", "สอบ", "quiz", "ควิซ", "ส่ง", "due", "deadline", 
        "กำหนด", "โปรเจกต์", "project", "present", "นำเสนอ", "นัด", "คะแนน",
        "แบบฝึกหัด", "homework", "assignment", "exam", "midterm", "final",
        "ตาราง", "สัปดาห์", "week", "วันที่", "meet", "meeting", "briefing"
    ]
    text_lower = clean_text.lower()
    if not any(k in text_lower for k in keywords):
        return []

    now = datetime.now()
    cur_date_str = now.strftime("%Y-%m-%d")
    post_date_str = post_date or cur_date_str

    prompt = EXTRACTION_PROMPT.format(
        post_date=post_date_str,
        current_date=cur_date_str,
        current_year=str(now.year),
        course_name=course_name,
        source=source
    ) + f"\n\nข้อความที่ต้องวิเคราะห์:\n{clean_text[:2500]}"

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }

    for model_name in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=25)
            if res.status_code == 200:
                data = res.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        results = json.loads(parts[0]["text"])
                        if isinstance(results, list):
                            valid_tasks = []
                            for t in results:
                                if isinstance(t, dict) and t.get("title"):
                                    t["course_name"] = course_name
                                    t["source"] = source
                                    valid_tasks.append(t)
                            return valid_tasks
            else:
                time.sleep(1.0)
                continue
        except Exception as e:
            print(f"[Task Extractor Warning on {model_name}] {e}")
            time.sleep(1.0)
            continue

    return []
