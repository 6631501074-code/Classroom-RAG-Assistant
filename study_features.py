import io
import json
import urllib.parse
import random
import requests
from typing import List, Dict, Any, Optional

from config import GEMINI_API_KEY

def call_gemini(prompt: str, temperature: float = 0.3) -> str:
    """Helper to query Gemini for study features with multi-model fallback"""
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    models = ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.8-flash"]
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 2048
        }
    }
    for model_name in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=30)
            if res.status_code == 200:
                data = res.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
            elif res.status_code == 429:
                continue
        except Exception as e:
            print(f"[Gemini Study Error on {model_name}]: {e}")
    return ""

def generate_study_guide(topic: str, context_text: str) -> str:
    """NotebookLM-style Comprehensive Study Guide generator"""
    prompt = f"""คุณคือผู้ช่วยสร้างคู่มือการเรียนระดับสูง (สไตล์ NotebookLM Study Guide)
หัวข้อที่ต้องการสรุป: {topic}

ข้อมูลอ้างอิงจากเอกสารบทเรียน:
{context_text[:5000]}

กรุณาสร้าง "คู่มือสรุปการเรียนและเตรียมสอบ (Study Guide)" ฉบับสมบูรณ์ ประกอบด้วย:
1. 📌 **ภาพรวมและใจความสำคัญ (Overview & Core Ideas)** - สรุปแก่นสาระสำคัญใน 2-3 บรรทัด
2. 🔑 **นิยามและคำศัพท์สำคัญ (Key Concepts & Definitions)** - แยกเป็น Bullet points ตัวหนาชัดเจน
3. 🎯 **ประเด็นเก็งข้อสอบ (Exam Highlights & Key Takeaways)** - จุดที่มักถูกนำมาออกข้อสอบหรือห้ามพลาด
4. 💡 **คำถามทบทวนตัวเอง (Review Questions)** - คำถามสั้นๆ 3 ข้อ เพื่อเช็กความเข้าใจ

จัดรูปแบบด้วย Markdown (หัวข้อ, bold, bullet points) ให้อ่านง่าย สบายตา เหมาะสำหรับนักศึกษา"""

    response = call_gemini(prompt, temperature=0.3)
    if not response:
        return "❌ ไม่สามารถสร้าง Study Guide ได้ในขณะนี้ โปรดลองใหม่อีกครั้ง"
    return response

def generate_quiz(topic: str, context_text: str) -> str:
    """Generate practice quiz with spoiler answers like NotebookLM"""
    prompt = f"""คุณคือผู้ช่วยติวสอบ
หัวข้อ: {topic}

ข้อมูลอ้างอิง:
{context_text[:4000]}

กรุณาสร้าง "แบบฝึกหัดทบทวนความรู้ (Practice Quiz)" จำนวน 3 ข้อ จากข้อมูลด้านบน:
- มีทั้งคำถามแบบปรนัย (ก, ข, ค, ง) หรือคำถามคิดวิเคราะห์
- ด้านล่างของแต่ละข้อ ให้ใส่เฉลยพร้อมคำอธิบายสั้นๆ โดยต้องครอบด้วย Discord Spoiler Markdown ||เฉลยและคำอธิบาย|| เพื่อให้ผู้เรียนคลิกดูเอง

ตัวอย่างฟอร์แมต:
**ข้อที่ 1:** [คำถาม...]
A) ...
B) ...
C) ...
D) ...
> ||เฉลย: B) เพราะ...||
"""
    response = call_gemini(prompt, temperature=0.4)
    if not response:
        return "❌ ไม่สามารถสร้างแบบทดสอบได้ในขณะนี้"
    return response

def generate_visual_mindmap_prompt(topic: str, context_snippet: str) -> str:
    """Use Gemini to craft a visual description for educational image generation"""
    prompt = f"""Given the study topic: "{topic}" and context: "{context_snippet[:800]}", 
create a highly descriptive English image prompt for an educational infographic or diagram.
Focus on: clean educational diagram, mind map, flowchart, whiteboard sketch, high resolution, minimalist academic aesthetic, professional infographic, vector art style.
Output ONLY the raw image prompt in English without extra explanations."""
    
    img_prompt = call_gemini(prompt, temperature=0.5)
    if not img_prompt:
        img_prompt = f"Educational infographic diagram explaining {topic}, clean modern visual aid, academic mind map, high quality"
    return img_prompt

def generate_study_image(topic: str, context_snippet: str = "") -> Optional[bytes]:
    """Generate an educational image/diagram using visual generation service"""
    refined_prompt = generate_visual_mindmap_prompt(topic, context_snippet)
    encoded = urllib.parse.quote(refined_prompt[:350])
    seed = random.randint(1000, 999999)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=768&nologo=true&seed={seed}&model=flux"
    
    try:
        res = requests.get(url, timeout=35)
        if res.status_code == 200 and len(res.content) > 1000:
            return res.content
    except Exception as e:
        print(f"[Image Gen Error]: {e}")
        
    return None
