import io
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from googleapiclient.http import MediaIoBaseDownload
from google_service import GoogleManager
from rag_engine import RAGEngine
import database

def sync_ee_lecture_notes():
    mgr = GoogleManager()
    rag = RAGEngine()
    ee_course_id = "783189695203"
    
    announcements = mgr.classroom.courses().announcements().list(courseId=ee_course_id).execute().get("announcements", [])
    os.makedirs("downloads", exist_ok=True)
    
    total_indexed = 0
    for ann in announcements:
        for m in ann.get("materials", []):
            df = m.get("driveFile", {}).get("driveFile", {})
            file_id = df.get("id")
            title = df.get("title", "")
            if file_id and title.lower().endswith(".pdf"):
                file_path = os.path.join("downloads", title)
                if not os.path.exists(file_path):
                    print(f"📥 Downloading: {title}...")
                    request = mgr.drive.files().get_media(fileId=file_id)
                    with open(file_path, "wb") as fh:
                        downloader = MediaIoBaseDownload(fh, request)
                        done = False
                        while not done:
                            _, done = downloader.next_chunk()
                    print(f"✅ Downloaded: {title} ({os.path.getsize(file_path)} bytes)")
                
                # Index into ChromaDB if not indexed
                if not database.is_document_synced(file_id):
                    print(f"🧠 Indexing into Vector DB: {title}...")
                    chunks = rag.index_pdf_file(file_path)
                    database.record_synced_document(file_id, ee_course_id, title, file_path)
                    print(f"✨ Indexed {title}: {chunks} chunks")
                    total_indexed += chunks
                else:
                    print(f"ℹ️ Already indexed: {title}")

    print(f"\n🎉 Finished syncing EE notes. Total new chunks indexed: {total_indexed}")

if __name__ == "__main__":
    sync_ee_lecture_notes()
