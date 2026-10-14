import json
import time
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional

from config import GEMINI_API_KEY, GEMINI_MODELS

CURRENT_DATE_STR = "2026-10-12"

EXTRACTION_PROMPT = """คุณคือ AI ผู้เชี่ยวชาญด้านการวิเคราะห์ตารางเรียนและงานวิชาการ
วันที่ปัจจุบันคือ: {current_date}

กรุณาวิเคราะห์ข้อความ ประกาศ หรือเอกสารของวิชา: "{course_name}" (ที่มา: {source})
เพื่อค้นหา "งานที่มอบหมาย, การบ้าน, โปรเจกต์กลุ่ม/เดี่ยว, นัดหมายประชุม/บรีฟงาน (Briefing / Google Meet), นัดสอบกลางภาค/ปลายภาค (Midterm/Final Exam), ควิซ (Quiz), นัดนำเสนอโปรเจกต์ (Presentation), หรือกำหนดการส่งงานที่มีเดดไลน์"
โดยเฉพาะงานหรือกำหนดการที่อาจารย์พิมพ์แจ้งในประกาศ Stream, สไลด์เรียน, หรือตารางสอน (Course Syllabus) ที่ไม่ได้เปิดเป็นกล่องส่งการบ้านทางการ

เงื่อนไขสำคัญ:
1. หากในข้อความมีหลายกิจกรรม/กำหนดการ (เช่น มีทั้งนัดบรีฟโปรเจกต์ และ นัดนำเสนอ Present) ให้แยกสกัดออกมาเป็นแต่ละรายการใน JSON Array ให้ครบถ้วน ห้ามข้าม!
2. หากมีการระบุวัน เช่น "Tuesday, October 13", "17 November 2026", "29 September 2026", หรือบอกเวลาสัมพันธ์ เช่น "พุธหน้า", "พรุ่งนี้", ให้แปลงเป็นวันที่มาตรฐาน YYYY-MM-DD โดยอ้างอิงปี 2026 จากวันที่ปัจจุบัน ({current_date})
3. ถ้าเป็นนัดหมาย/สอบ ให้ระบุเวลาเริ่มต้นใน due_time (เช่น "16:00", "09:00") ถ้าไม่ระบุเวลา ให้ใส่ "23:59"
4. task_type ให้ระบุเป็นประเภทที่ชัดเจน เช่น "ส่งงาน/การบ้าน", "นัดหมาย/บรีฟงาน", "นัดนำเสนอ/Present", "นัดสอบ", "ควิซ"
5. สรุปเป็นภาษาไทย 1-2 ประโยค (summary_thai) และภาษาอังกฤษ 1-2 ประโยค (summary_english)
6. หากข้อความนี้เป็นเพียงการทักทายทั่วไป, แชร์ลิงก์โดยไม่มีนัดหมาย/งาน, หรือแจ้งยกเลิกคลาส ให้ส่งกลับเป็นลิสต์ว่าง []

ตอบกลับเฉพาะ JSON Array เท่านั้น ในรูปแบบ:
[
  {{
    "title": "ชื่องานหรือกำหนดการ",
    "task_type": "ส่งงาน/การบ้าน / นัดหมาย/บรีฟงาน / นัดนำเสนอ/Present / นัดสอบ / ควิซ",
    "due_date": "YYYY-MM-DD",
    "due_time": "HH:MM",
    "raw_deadline": "ข้อความกำหนดวันเวลาเดิมที่อาจารย์เขียน",
    "description": "รายละเอียดสิ่งที่ต้องทำ (รวมลิงก์ Meet/เอกสาร/ห้องเรียนถ้ามี)",
    "summary_thai": "สรุปภาษาไทย 1-2 ประโยค",
    "summary_english": "English summary 1-2 sentences"
  }}
]
"""

def extract_tasks_from_text(text: str, course_name: str, source: str) -> List[Dict[str, Any]]:
    """Analyze announcements or document text using Gemini to detect informal assignments and deadlines"""
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

    prompt = EXTRACTION_PROMPT.format(
        current_date=CURRENT_DATE_STR,
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
