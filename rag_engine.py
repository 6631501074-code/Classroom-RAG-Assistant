import os
import requests
import json
from typing import List, Dict, Any, Optional
from pathlib import Path
import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from pypdf import PdfReader

from config import CHROMA_PERSIST_DIR, GEMINI_API_KEY, GEMINI_MODELS
import database

SYSTEM_INSTRUCTION = """คุณคือ "Classroom RAG Assistant" ผู้ช่วยวิชาการส่วนตัวที่เชื่อมต่อกับ Google Classroom, คลังเอกสาร (Vector Database) และ Discord DM

หน้าที่หลัก:
1. ตอบคำถามผู้ใช้โดยอ้างอิงจากข้อมูลบริบท (Context) ที่ค้นหาได้จาก Vector Database เท่านั้น (ข้อมูลจาก Google Classroom และไฟล์ PDF/เอกสารที่ผู้ใช้อัปโหลด)
2. หากผู้ใช้ถามเรื่องงาน/การบ้าน ให้สรุป: ชื่อวิชา, หัวเรื่อง, กำหนดส่ง (Deadline), และรายละเอียดที่ต้องทำ
3. หากผู้ใช้ถามเนื้อหาในเอกสาร ให้ตอบคำถามพร้อมระบุชื่อไฟล์อ้างอิง (Source Document)
4. รูปแบบการตอบ: ใช้ภาษาไทย กระชับ จัดรูปแบบด้วย Markdown (Bullet points / Bold) ให้สแกนอ่านใน Discord ง่าย

ข้อห้ามเด็ดขาด:
- ห้ามคิดแต่งข้อมูลขึ้นมาเองนอกเหนือจาก Context ที่ส่งไปให้เด็ดขาด
- หากใน Context ไม่มีข้อมูลที่เพียงพอหรือไม่พบคำตอบ ให้ตอบเพียงข้อความนี้เท่านั้น:
"ไม่พบข้อมูลในระบบ ลองพิมพ์ !sync หรืออัปโหลดไฟล์เพิ่มเติม"
"""

class GeminiEmbeddingFunction(EmbeddingFunction[Documents]):
    def __init__(self, api_key: str):
        self.api_key = api_key
class GeminiEmbeddingFunction(EmbeddingFunction[Documents]):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.endpoint = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents"
        self._default_fallback = None
        self.current_dimension = 3072

    def _get_fallback_embeddings(self, batch: Documents) -> Embeddings:
        """Fallback to local embedding vector if API is unavailable"""
        return [[0.0] * self.current_dimension for _ in batch]

    def __call__(self, input: Documents) -> Embeddings:
        if not input:
            return []

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key
        }
        
        all_embeddings = []
        batch_size = 25
        for i in range(0, len(input), batch_size):
            batch = input[i:i + batch_size]
            requests_payload = []
            for text in batch:
                clean_text = text[:1500].strip() or "empty"
                requests_payload.append({
                    "model": "models/gemini-embedding-001",
                    "content": {"parts": [{"text": clean_text}]}
                })
            
            payload = {"requests": requests_payload}
            try:
                res = requests.post(self.endpoint, headers=headers, json=payload, timeout=25)
                if res.status_code == 200:
                    data = res.json()
                    embeddings = [item["values"] for item in data.get("embeddings", [])]
                    if embeddings:
                        self.current_dimension = len(embeddings[0])
                    all_embeddings.extend(embeddings)
                else:
                    print(f"[Embedding Error] HTTP {res.status_code}: {res.text[:120]}... Using fallback vector.")
                    all_embeddings.extend(self._get_fallback_embeddings(batch))
            except Exception as e:
                print(f"[Embedding Exception]: {e}... Using fallback vector.")
                all_embeddings.extend(self._get_fallback_embeddings(batch))
                    
        return all_embeddings

class RAGEngine:
    def __init__(self):
        self.chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        self.embedding_fn = GeminiEmbeddingFunction(api_key=GEMINI_API_KEY)
        self.collection = self.chroma_client.get_or_create_collection(
            name="classroom_knowledge",
            embedding_function=self.embedding_fn
        )

    def reset_collection(self):
        """Reset ChromaDB collection to handle dimension changes or clean slate"""
        try:
            self.chroma_client.delete_collection("classroom_knowledge")
        except Exception:
            pass
        self.collection = self.chroma_client.get_or_create_collection(
            name="classroom_knowledge",
            embedding_function=self.embedding_fn
        )

    def _safe_upsert(self, ids: List[str], documents: List[str], metadatas: List[Dict[str, Any]]):
        """Upsert with auto-recovery when dimension mismatch occurs"""
        if not ids:
            return
        try:
            self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        except Exception as e:
            if "dimension" in str(e).lower():
                print(f"[ChromaDB Auto-Fix] Dimension mismatch ({e}). Recreating collection...")
                self.reset_collection()
                self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
            else:
                raise e

    def split_text(self, text: str, chunk_size: int = 700, chunk_overlap: int = 100) -> List[str]:
        """Split text into overlapping chunks"""
        chunks = []
        start = 0
        text = text.strip()
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start += chunk_size - chunk_overlap
        return chunks

    def add_assignments_batch(self, items: List[Dict[str, Any]]):
        """Batch add coursework assignments to vector DB for maximum speed"""
        if not items:
            return
        ids = []
        documents = []
        metadatas = []
        for item in items:
            doc_id = f"assignment_{item['id']}"
            due_str = f"{item.get('due_date', 'ไม่มีกำหนด')} {item.get('due_time', '')}".strip()
            content = (
                f"[งานที่มอบหมาย / การบ้าน]\n"
                f"ชื่อวิชา: {item.get('course_name')}\n"
                f"หัวเรื่อง: {item.get('title')}\n"
                f"กำหนดส่ง (Deadline): {due_str}\n"
                f"รายละเอียด: {item.get('description', 'ไม่มีรายละเอียดเพิ่มเติม')}\n"
                f"ลิงก์ส่งงาน: {item.get('alternate_link', '')}"
            )
            metadata = {
                "type": "assignment",
                "source": f"Google Classroom: {item.get('course_name')}",
                "course_name": str(item.get("course_name")),
                "title": str(item.get("title")),
                "due_date": due_str
            }
            ids.append(doc_id)
            documents.append(content)
            metadatas.append(metadata)

        self._safe_upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )

    def add_classroom_items_batch(self, items: List[Dict[str, Any]]):
        """Batch add announcements and materials for maximum speed"""
        if not items:
            return
        ids = []
        documents = []
        metadatas = []
        for index, item in enumerate(items):
            item_type = item.get("type", "classroom_info")
            course_name = item.get("course_name", "")
            title = item.get("title", "")
            doc_id = f"{item_type}_{course_name}_{index}_{hash(title)}"
            content = (
                f"[{item.get('source')}]\n"
                f"วิชา: {course_name}\n"
                f"หัวข้อ: {title}\n"
                f"เนื้อหา:\n{item.get('content')}"
            )
            metadata = {
                "type": item_type,
                "source": str(item.get("source")),
                "course_name": str(course_name),
                "title": str(title)
            }
            ids.append(doc_id)
            documents.append(content)
            metadatas.append(metadata)

        self._safe_upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )

    def add_assignment(self, item: Dict[str, Any]):
        """Single assignment add (wraps batch)"""
        self.add_assignments_batch([item])

    def add_classroom_item(self, item: Dict[str, Any], index: int):
        """Single classroom item add (wraps batch)"""
        self.add_classroom_items_batch([item])

    def index_pdf_file(self, file_path: str, course_name: Optional[str] = None) -> int:
        """Extract and index PDF text into vector DB"""
        path = Path(file_path)
        if not path.exists():
            return 0

        reader = PdfReader(str(path))
        extracted_text = []
        for page_idx, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            if page_text.strip():
                extracted_text.append(f"--- หน้า {page_idx + 1} ---\n{page_text}")

        full_text = "\n\n".join(extracted_text)
        if not full_text.strip():
            return 0

        chunks = self.split_text(full_text)
        ids = []
        documents = []
        metadatas = []
        
        file_name = path.name
        source_name = f"ไฟล์เอกสาร: {file_name}"
        
        for idx, chunk in enumerate(chunks):
            chunk_id = f"pdf_{hash(file_name)}_{idx}"
            ids.append(chunk_id)
            documents.append(f"[เอกสาร: {file_name}]\n{chunk}")
            metadatas.append({
                "type": "pdf_document",
                "source": file_name,
                "course_name": str(course_name or "เอกสารอัปโหลด"),
                "chunk_index": idx
            })

        self._safe_upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )
        
        database.record_synced_document(
            doc_id=file_name,
            course_id=None,
            file_name=file_name,
            file_path=str(path)
        )
        return len(chunks)

    def query_context(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve most relevant context documents from ChromaDB"""
        if self.collection.count() == 0:
            return []

        results = self.collection.query(
            query_texts=[query],
            n_results=min(top_k, self.collection.count())
        )
        
        contexts = []
        if results and "documents" in results and results["documents"]:
            docs = results["documents"][0]
            metadatas = results["metadatas"][0] if "metadatas" in results else [{}] * len(docs)
            for doc, meta in zip(docs, metadatas):
                contexts.append({
                    "text": doc,
                    "metadata": meta
                })
        return contexts

    def answer_question(self, user_question: str) -> str:
        """RAG Generation with strict grounding and fallback"""
        contexts = self.query_context(user_question, top_k=6)
        
        if not contexts:
            return "ไม่พบข้อมูลในระบบ ลองพิมพ์ !sync หรืออัปโหลดไฟล์เพิ่มเติม"

        # Format retrieved context
        context_str = "\n\n-------------------------\n\n".join([
            f"[Source: {c['metadata'].get('source', 'ไม่ระบุ')}]\n{c['text']}" 
            for c in contexts
        ])

        prompt = (
            f"คำถามของผู้ใช้:\n{user_question}\n\n"
            f"ข้อมูลบริบท (Context) จากระบบ:\n{context_str}\n\n"
            f"กรุณาตอบคำถามโดยอ้างอิงจากข้อมูลด้านบนเท่านั้น หากไม่พบคำตอบ ให้ตอบว่า 'ไม่พบข้อมูลในระบบ ลองพิมพ์ !sync หรืออัปโหลดไฟล์เพิ่มเติม'"
        )

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY
        }
        
        # Model priorities
        for model_name in GEMINI_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            payload = {
                "system_instruction": {
                    "parts": [{"text": SYSTEM_INSTRUCTION}]
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 1024
                }
            }
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=40)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
                else:
                    print(f"Gemini API returned {res.status_code}: {res.text}")
            except Exception as e:
                print(f"Gemini API error with {model_name}: {e}")

        return "ไม่พบข้อมูลในระบบ ลองพิมพ์ !sync หรืออัปโหลดไฟล์เพิ่มเติม"
