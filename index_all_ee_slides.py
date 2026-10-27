import os
import sys
import io
import json
import base64
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pypdfium2 as pdfium
import requests
from config import GEMINI_API_KEY, GEMINI_MODELS
from rag_engine import RAGEngine
import database

EE_COURSE_NAME = "[1/2568] 1501319 Fundamental of Electrical Engineering"
EE_COURSE_ID = "783189695203"

PDF_FILES = [
    "01 basic concept.pdf",
    "02 v-i division.pdf",
    "03 kcl.pdf",
    "04 LC.pdf",
    "05 RLC.pdf",
    "06 energy_power.pdf",
    "07 AC and Power.pdf",
    "08 Transformer.pdf",
    "09 Polyphase AC.pdf",
    "10 Inductor Motor.pdf"
]

def transcribe_pages_with_vision(pdf_path: str, start_page: int, end_page: int) -> str:
    """Render a batch of pages and extract detailed formulas and explanations with Gemini Vision"""
    pdf = pdfium.PdfDocument(pdf_path)
    total_pages = len(pdf)
    end_page = min(end_page, total_pages)
    
    parts = []
    for idx in range(start_page, end_page):
        page = pdf[idx]
        pil_img = page.render(scale=1.3).to_pil()
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=80)
        b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_data}})

    prompt_text = (
        f"นี่คือสไลด์การสอนวิชา {EE_COURSE_NAME} ไฟล์ {os.path.basename(pdf_path)} หน้า {start_page + 1} ถึง {end_page}\n"
        "กรุณาสรุปและถอดเนื้อหาทั้งหมดอย่างละเอียดที่สุด เพื่อใช้เป็นฐานข้อมูลความรู้ทางวิชาการ (Knowledge Base for RAG):\n"
        "1. ทฤษฎี, กฎเกณฑ์, หลักการ (เช่น Ohm's law, KCL, KVL, Voltage/Current Division, RLC, AC Power, Transformer, Induction Motor)\n"
        "2. สูตรคณิตศาสตร์และสมการวงจรทั้งหมด (เขียนแบบ LaTeX หรือข้อความชัดเจน)\n"
        "3. อธิบายรายละเอียดวงจร ค่าตัวแปร แหล่งจ่าย ตัวต้านทาน ตัวเก็บประจุ ขดลวดเหนี่ยวนำ และสภาวะวงจร (Transient, Steady-state, etc.)\n"
        "4. ตัวอย่างการคำนวณและข้อสังเกตสำคัญของอาจารย์ผู้สอน"
    )
    parts.append({"text": prompt_text})

    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
    for model_name in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048}
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=50)
            if res.status_code == 200:
                data = res.json()
                candidates = data.get("candidates", [])
                if candidates:
                    text_parts = candidates[0].get("content", {}).get("parts", [])
                    if text_parts:
                        return text_parts[0].get("text", "").strip()
            else:
                print(f"[Vision Warning] {model_name} HTTP {res.status_code}: {res.text[:100]}")
        except Exception as e:
            print(f"[Vision Error] {model_name}: {e}")
        time.sleep(1)

    return ""

def process_and_index_ee_slides():
    rag = RAGEngine()
    os.makedirs("downloads", exist_ok=True)
    
    total_chunks = 0
    for pdf_name in PDF_FILES:
        pdf_path = os.path.join("downloads", pdf_name)
        if not os.path.exists(pdf_path):
            print(f"⚠️ File not found: {pdf_path}")
            continue

        cache_path = os.path.join("downloads", f"{pdf_name}.notes.txt")
        full_text = ""
        
        if os.path.exists(cache_path):
            print(f"📂 Loading cached notes for {pdf_name}...")
            with open(cache_path, "r", encoding="utf-8") as f:
                full_text = f.read()
        else:
            print(f"🧠 Transcribing {pdf_name} with Gemini Vision...")
            pdf = pdfium.PdfDocument(pdf_path)
            num_pages = len(pdf)
            batch_size = 4
            sections = []
            
            for p_start in range(0, num_pages, batch_size):
                p_end = min(p_start + batch_size, num_pages)
                print(f"   - Processing pages {p_start + 1} to {p_end} of {num_pages}...")
                batch_text = transcribe_pages_with_vision(pdf_path, p_start, p_end)
                if batch_text:
                    sections.append(f"### [สไลด์ {pdf_name} หน้า {p_start + 1}-{p_end}]\n{batch_text}")
                time.sleep(1)
            
            full_text = "\n\n-------------------------\n\n".join(sections)
            if full_text:
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(full_text)
                print(f"💾 Saved cached notes to {cache_path}")

        if not full_text.strip():
            print(f"⚠️ No text could be extracted for {pdf_name}")
            continue

        # Split into chunks and index into ChromaDB
        chunks = rag.split_text(full_text, chunk_size=800, chunk_overlap=120)
        ids = []
        documents = []
        metadatas = []
        
        for idx, chunk in enumerate(chunks):
            chunk_id = f"ee_slide_{hash(pdf_name)}_{idx}"
            ids.append(chunk_id)
            documents.append(f"[วิชา: {EE_COURSE_NAME} | สไลด์: {pdf_name}]\n{chunk}")
            metadatas.append({
                "type": "ee_lecture_notes",
                "source": f"สไลด์: {pdf_name}",
                "course_name": EE_COURSE_NAME,
                "title": pdf_name,
                "chunk_index": idx
            })
            
        rag._safe_upsert(ids=ids, documents=documents, metadatas=metadatas)
        database.record_synced_document(
            doc_id=f"ee_{pdf_name}",
            course_id=EE_COURSE_ID,
            file_name=pdf_name,
            file_path=pdf_path
        )
        print(f"✅ Indexed {pdf_name}: {len(chunks)} chunks into ChromaDB")
        total_chunks += len(chunks)

    print(f"\n🎉 Finished indexing all EE lecture notes! Total chunks: {total_chunks}")

if __name__ == "__main__":
    process_and_index_ee_slides()
