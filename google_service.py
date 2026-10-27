import os
import io
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

import requests
import json
from config import (
    CREDENTIALS_FILE,
    TOKEN_FILE,
    GOOGLE_SCOPES,
    DOWNLOADS_DIR,
    GEMINI_API_KEY,
    EXCLUDED_COURSES,
    GEMINI_MODELS
)
import database
from task_extractor import extract_tasks_from_text

def get_credentials(force_reauth: bool = False) -> Optional[Credentials]:
    """Get valid user credentials from storage or run local OAuth flow."""
    creds = None
    if os.path.exists(TOKEN_FILE) and not force_reauth:
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                token_data = json.load(f)
            disk_scopes = token_data.get("scopes", [])
            missing_scopes = set(GOOGLE_SCOPES) - set(disk_scopes)
            if missing_scopes:
                print(f"ℹ️ ตรวจพบว่ามีการเพิ่มสิทธิ์ใหม่: {missing_scopes}")
                print("🌐 กำลังเปิดหน้าต่างเบราว์เซอร์เพื่อขออนุญาตสิทธิ์ Google เพิ่มเติม...")
                creds = None
            else:
                creds = Credentials.from_authorized_user_file(TOKEN_FILE, GOOGLE_SCOPES)
        except Exception as e:
            print(f"[Google Auth] Error loading token file: {e}")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"[Google Auth] Error refreshing token: {e}")
                creds = None
                
        if not creds:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(f"Missing '{CREDENTIALS_FILE}'. Please put your OAuth client json file here.")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, GOOGLE_SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w", encoding="utf-8") as token_out:
            token_out.write(creds.to_json())

    return creds

def generate_bilingual_summary(course_name: str, title: str, description: str) -> Dict[str, str]:
    """Generate concise Thai and English summaries using Gemini"""
    clean_desc = (description or "").strip()
    if not clean_desc:
        return {
            "thai": "ไม่มีรายละเอียดเพิ่มเติมจากผู้สอน",
            "english": "No additional instructions provided by instructor."
        }

    prompt = (
        f"ช่วยสรุปรายละเอียดงานต่อไปนี้เป็น 2 ภาษา (ภาษาไทย และ ภาษาอังกฤษ) ให้สั้นกระชับ 1-3 บรรทัด สำหรับใส่ใน Google Calendar:\n"
        f"วิชา: {course_name}\n"
        f"ชื่องาน: {title}\n"
        f"รายละเอียด: {clean_desc[:1200]}\n\n"
        f"กรุณาตอบเป็น JSON ในรูปแบบนี้เท่านั้น:\n"
        f'{{"thai": "สรุปภาษาไทย 1-3 บรรทัด", "english": "English summary 1-3 lines"}}'
    )
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}
    }
    for model_name in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=20)
            if res.status_code == 200:
                data = res.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        parsed = json.loads(parts[0]["text"])
                        return {
                            "thai": parsed.get("thai", clean_desc[:250]),
                            "english": parsed.get("english", clean_desc[:250])
                        }
            else:
                continue
        except Exception as e:
            print(f"[Gemini Bilingual Summary Error on {model_name}]: {e}")
            continue

    return {
        "thai": clean_desc[:250],
        "english": clean_desc[:250]
    }

def is_course_excluded(course_name: str, course_id: str = "", section: str = "") -> bool:
    """Check if course is in user's excluded blacklist or belongs to past semesters"""
    name_clean = (course_name or "").lower()
    id_clean = str(course_id or "")
    sec_clean = (section or "").lower()
    for ex in EXCLUDED_COURSES:
        ex_clean = ex.lower()
        if ex_clean in name_clean or ex_clean in sec_clean or ex_clean == id_clean:
            return True
    return False

class GoogleManager:
    def __init__(self):
        self.creds = get_credentials()
        self.classroom = build("classroom", "v1", credentials=self.creds)
        self.calendar = build("calendar", "v3", credentials=self.creds)
        self.drive = build("drive", "v3", credentials=self.creds)
        try:
            self.tasks = build("tasks", "v1", credentials=self.creds)
        except Exception as e:
            self.tasks = None
            print(f"[Google Tasks Warning] Could not initialize Tasks service: {e}")

    def fetch_courses(self) -> List[Dict[str, Any]]:
        """Fetch active courses user is enrolled in (filtered by exclusion list)"""
        try:
            results = self.classroom.courses().list(
                studentId="me", 
                courseStates=["ACTIVE"]
            ).execute()
            raw_courses = results.get("courses", [])
            courses = [
                c for c in raw_courses 
                if not is_course_excluded(c.get("name", ""), c.get("id", ""), c.get("section", ""))
            ]
            database.save_courses(courses)
            return courses
        except Exception as e:
            print(f"[Classroom] Error fetching courses: {e}")
            return []

    def fetch_all_coursework(self, days_back: int = 60) -> List[Dict[str, Any]]:
        """Fetch assignments across all active courses and store in SQLite (filtered to active & recent ~2 months)"""
        cutoff_date = (datetime.now().date() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        cutoff_creation = (datetime.now().date() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        courses = self.fetch_courses()
        all_assignments = []
        for course in courses:
            course_id = course.get("id")
            course_name = course.get("name")
            try:
                results = self.classroom.courses().courseWork().list(
                    courseId=course_id
                ).execute()
                works = results.get("courseWork", [])
                for work in works:
                    due_date_str = None
                    due_time_str = None
                    due_date_obj = work.get("dueDate")
                    due_time_obj = work.get("dueTime")
                    
                    if due_date_obj:
                        year = due_date_obj.get("year")
                        month = due_date_obj.get("month")
                        day = due_date_obj.get("day")
                        due_date_str = f"{year:04d}-{month:02d}-{day:02d}"
                    
                    if due_time_obj:
                        hours = due_time_obj.get("hours", 23)
                        minutes = due_time_obj.get("minutes", 59)
                        due_time_str = f"{hours:02d}:{minutes:02d}"

                    # Filter out old coursework (> 60 days / 2 months)
                    if due_date_str:
                        if due_date_str < cutoff_date:
                            continue  # Skip coursework with deadline older than 60 days
                    else:
                        creation_date = (work.get("creationTime") or "")[:10]
                        if creation_date and creation_date < cutoff_creation:
                            continue  # Skip coursework with no deadline created > 60 days ago

                    assignment_data = {
                        "id": work.get("id"),
                        "course_id": course_id,
                        "course_name": course_name,
                        "title": work.get("title"),
                        "description": work.get("description", ""),
                        "due_date": due_date_str,
                        "due_time": due_time_str,
                        "alternate_link": work.get("alternateLink", ""),
                        "materials": work.get("materials", [])
                    }
                    database.save_assignment(assignment_data)
                    all_assignments.append(assignment_data)
            except Exception as e:
                print(f"[Classroom] Error fetching coursework for {course_name}: {e}")
        return all_assignments

    def fetch_course_materials_and_announcements(self, days_back_tasks: int = 60, days_back_materials: int = 60) -> List[Dict[str, Any]]:
        """Fetch announcements, materials, and extract informal tasks and schedules using AI (filtered to recent ~2 months)"""
        cutoff_date = (datetime.now().date() - timedelta(days=days_back_tasks)).strftime("%Y-%m-%d")
        cutoff_materials_date = (datetime.now().date() - timedelta(days=days_back_materials)).strftime("%Y-%m-%d")
        courses = self.fetch_courses()
        items = []
        for course in courses:
            course_id = course.get("id")
            course_name = course.get("name")
            is_internship = "internship" in course_name.lower() or "ฝึกงาน" in course_name
            
            # 1. Announcements (Stream)
            try:
                res = self.classroom.courses().announcements().list(courseId=course_id).execute()
                announcements = res.get("announcements", [])
                for ann in announcements:
                    creation_time = ann.get("creationTime", "")
                    ann_date = creation_time[:10] if creation_time else ""
                    post_dt_str = ann_date
                    if creation_time:
                        try:
                            dt = datetime.fromisoformat(creation_time.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=7)))
                            post_dt_str = dt.strftime("%Y-%m-%d %H:%M")
                            ann_date = dt.strftime("%Y-%m-%d")
                        except Exception:
                            pass

                    # Scan announcements from recent months
                    ann_limit = (datetime.now().date() - timedelta(days=180)).strftime("%Y-%m-%d") if is_internship else (datetime.now().date() - timedelta(days=120)).strftime("%Y-%m-%d")
                    if ann_date and ann_date < ann_limit:
                        continue

                    text = ann.get("text", "").strip()
                    if text:
                        items.append({
                            "type": "announcement",
                            "course_name": course_name,
                            "title": f"ประกาศจาก {course_name}",
                            "content": text,
                            "date": creation_time,
                            "source": f"Classroom Announcement ({course_name})",
                            "materials": ann.get("materials", [])
                        })
                        
                        # AI Extract hidden tasks / deadlines from announcement with publication date
                        extracted_tasks = extract_tasks_from_text(
                            text, 
                            course_name, 
                            f"ประกาศใน Stream: {course_name}",
                            post_date=post_dt_str
                        )
                        ann_id = str(ann.get("id") or abs(hash(text[:50])))
                        for idx, t in enumerate(extracted_tasks):
                            task_due = t.get("due_date")
                            if not task_due or task_due < cutoff_date:
                                continue  # Skip missing or past deadlines

                            ext_id = f"ext_ann_{ann_id}_{idx}"
                            assign_record = {
                                "id": ext_id,
                                "course_id": course_id,
                                "course_name": course_name,
                                "title": t["title"],
                                "description": t.get("description", text[:300]),
                                "due_date": task_due,
                                "due_time": t.get("due_time", "23:59"),
                                "alternate_link": ann.get("alternateLink", ""),
                                "task_type": t.get("task_type", "กำหนดการ"),
                                "raw_deadline": t.get("raw_deadline", ""),
                                "summary_thai": t.get("summary_thai", ""),
                                "summary_english": t.get("summary_english", "")
                            }
                            database.save_assignment(assign_record)
            except Exception as e:
                print(f"[Classroom] Error fetching announcements for {course_name}: {e}")

            # 2. Materials
            try:
                res = self.classroom.courses().courseWorkMaterials().list(courseId=course_id).execute()
                materials = res.get("courseWorkMaterial", [])
                for mat in materials:
                    creation_time = mat.get("creationTime", "")
                    mat_date = creation_time[:10] if creation_time else ""
                    post_dt_str = mat_date
                    if creation_time:
                        try:
                            dt = datetime.fromisoformat(creation_time.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=7)))
                            post_dt_str = dt.strftime("%Y-%m-%d %H:%M")
                            mat_date = dt.strftime("%Y-%m-%d")
                        except Exception:
                            pass

                    mat_limit = (datetime.now().date() - timedelta(days=180)).strftime("%Y-%m-%d") if is_internship else (datetime.now().date() - timedelta(days=120)).strftime("%Y-%m-%d")
                    if mat_date and mat_date < mat_limit:
                        continue

                    title = mat.get("title", "")
                    desc = mat.get("description", "")
                    content = f"{title}\n{desc}".strip()
                    items.append({
                        "type": "material",
                        "course_name": course_name,
                        "title": title,
                        "content": content,
                        "date": creation_time,
                        "source": f"Classroom Material: {title}",
                        "materials": mat.get("materials", [])
                    })
                    
                    # AI Extract hidden tasks / deadlines from material description
                    if len(content) > 15:
                        extracted_tasks = extract_tasks_from_text(
                            content, 
                            course_name, 
                            f"เอกสารเนื้อหา: {title}",
                            post_date=post_dt_str
                        )
                        mat_id = str(mat.get("id") or abs(hash(title)))
                        for idx, t in enumerate(extracted_tasks):
                            task_due = t.get("due_date")
                            if not task_due or task_due < cutoff_date:
                                continue

                            ext_id = f"ext_mat_{mat_id}_{idx}"
                            assign_record = {
                                "id": ext_id,
                                "course_id": course_id,
                                "course_name": course_name,
                                "title": t["title"],
                                "description": t.get("description", desc[:300]),
                                "due_date": task_due,
                                "due_time": t.get("due_time", "23:59"),
                                "alternate_link": mat.get("alternateLink", ""),
                                "task_type": t.get("task_type", "กำหนดการ"),
                                "raw_deadline": t.get("raw_deadline", ""),
                                "summary_thai": t.get("summary_thai", ""),
                                "summary_english": t.get("summary_english", "")
                            }
                            database.save_assignment(assign_record)
            except Exception as e:
                print(f"[Classroom] Error fetching materials for {course_name}: {e}")

        return items

    def delete_all_calendar_events(self) -> int:
        """Delete all previously created bot events and tasks from Google Calendar & Tasks"""
        deleted_count = 0
        db_event_ids = set(database.get_synced_calendar_event_ids())
        db_task_ids = set(database.get_synced_google_task_ids())
        
        # 1. Delete events recorded in SQLite
        for eid in db_event_ids:
            try:
                self.calendar.events().delete(calendarId="primary", eventId=eid).execute()
                deleted_count += 1
            except Exception:
                pass

        # 2. Delete tasks recorded in SQLite
        if self.tasks:
            for tid in db_task_ids:
                try:
                    self.tasks.tasks().delete(tasklist="@default", task=tid).execute()
                    deleted_count += 1
                except Exception:
                    pass

        # 3. Search primary calendar for bot prefixes and clean up
        prefixes = ["📌", "[ส่งงาน/Due]", "[กำหนดส่งงาน]", "[ส่งงาน]", "[การบ้าน]", "[นัดหมาย/บรีฟงาน]", "[นัดสอบ]", "[ควิซ]", "[นัดนำเสนอ/Present]"]
        for p in prefixes:
            try:
                res = self.calendar.events().list(
                    calendarId="primary",
                    q=p,
                    maxResults=250
                ).execute()
                for item in res.get("items", []):
                    item_id = item.get("id")
                    if item_id and item_id not in db_event_ids:
                        try:
                            self.calendar.events().delete(calendarId="primary", eventId=item_id).execute()
                            deleted_count += 1
                            db_event_ids.add(item_id)
                        except Exception:
                            pass
            except Exception as e:
                print(f"[Calendar Cleanup Warning]: {e}")

        # Reset database states
        database.reset_calendar_sync()
        return deleted_count

    def sync_to_google_calendar(self, days_back: int = 60) -> List[Dict[str, Any]]:
        """Sync unsynced assignments with due dates to Google Calendar & Google Tasks with bilingual summaries"""
        today_str = datetime.now().strftime("%Y-%m-%d")
        unsynced = database.get_unsynced_calendar_assignments(days_back=days_back)
        synced_results = []
        seen_event_keys = set()
        
        for item in unsynced:
            due_date = item.get("due_date")
            cutoff_date = (datetime.now().date() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            if not due_date or due_date < cutoff_date:
                continue

            event_key = (str(item.get("course_id")), item.get("title", "").strip().lower(), due_date)
            if event_key in seen_event_keys:
                database.mark_assignment_calendar_synced(item.get("id"), event_id="duplicate_skipped")
                continue
            seen_event_keys.add(event_key)
                
            due_time = item.get("due_time") or "23:59"
            
            # Determine start and end datetimes (provide at least 1-hour block for visibility)
            try:
                time_parts = [int(p) for p in due_time.split(":")]
                h, m = time_parts[0], time_parts[1]
                end_dt_obj = datetime.strptime(f"{due_date} {h:02d}:{m:02d}", "%Y-%m-%d %H:%M")
                start_dt_obj = end_dt_obj - timedelta(hours=1) if h > 0 else end_dt_obj
                dt_start_str = start_dt_obj.strftime("%Y-%m-%dT%H:%M:00+07:00")
                dt_end_str = end_dt_obj.strftime("%Y-%m-%dT%H:%M:00+07:00")
            except Exception:
                dt_start_str = f"{due_date}T{due_time}:00+07:00"
                dt_end_str = f"{due_date}T{due_time}:00+07:00"
            
            # Check if bilingual summaries are already cached from AI extractor
            thai_sum = item.get("summary_thai")
            eng_sum = item.get("summary_english")
            if not thai_sum or not eng_sum:
                summaries = generate_bilingual_summary(
                    item.get('course_name', ''),
                    item.get('title', ''),
                    item.get('description', '')
                )
                thai_sum = summaries["thai"]
                eng_sum = summaries["english"]

            raw_deadline_info = f" ({item.get('raw_deadline')})" if item.get('raw_deadline') else ""
            desc_body = (
                f"🇹🇭 【รายละเอียดภาษาไทย】\n"
                f"• วิชา: {item.get('course_name')}\n"
                f"• หัวข้อ: {item.get('title')}\n"
                f"• ประเภท: {item.get('task_type', 'การบ้าน')}\n"
                f"• สรุปงาน: {thai_sum}\n"
                f"• กำหนดส่ง: {due_date} เวลา {due_time} น.{raw_deadline_info}\n"
                f"• ลิงก์ส่งงาน: {item.get('alternate_link', 'ไม่มีลิงก์')}\n\n"
                f"──────────────────────────────────\n"
                f"🇬🇧 【English Summary】\n"
                f"• Course: {item.get('course_name')}\n"
                f"• Topic: {item.get('title')}\n"
                f"• Type: {item.get('task_type', 'Assignment')}\n"
                f"• Summary: {eng_sum}\n"
                f"• Deadline: {due_date} at {due_time}\n"
                f"• Link: {item.get('alternate_link', 'None')}"
            )

            task_type = item.get("task_type", "การบ้าน")
            is_submission = any(w in str(task_type).lower() for w in ["การบ้าน", "ส่งงาน", "กำหนดส่งงาน", "assignment", "งาน", "ประเมิน", "quiz", "ควิซ"])

            task_id = None
            event_id = None

            # 1. Optionally sync to Google Tasks if it's a submission
            if is_submission and self.tasks:
                try:
                    task_due_rfc = f"{due_date}T00:00:00.000Z"
                    task_body = {
                        "title": f"📌 [{task_type}] {item.get('course_name')}: {item.get('title')}",
                        "notes": desc_body,
                        "due": task_due_rfc
                    }
                    res_task = self.tasks.tasks().insert(tasklist="@default", body=task_body).execute()
                    task_id = res_task.get("id")
                except Exception as te:
                    print(f"[Google Tasks Notice] Cannot sync as task: {te}")

            # 2. ALWAYS create Google Calendar Event for clear visual schedule in Calendar
            try:
                task_tag = item.get("task_type", "ส่งงาน/Due")
                event_body = {
                    "summary": f"📌 [{task_tag}] {item.get('course_name')}: {item.get('title')}",
                    "description": desc_body,
                    "start": {
                        "dateTime": dt_start_str,
                        "timeZone": "Asia/Bangkok",
                    },
                    "end": {
                        "dateTime": dt_end_str,
                        "timeZone": "Asia/Bangkok",
                    },
                    "reminders": {
                        "useDefault": False,
                        "overrides": [
                            {"method": "popup", "minutes": 24 * 60},  # 1 day before
                            {"method": "popup", "minutes": 120},      # 2 hours before
                        ],
                    },
                }
                event = self.calendar.events().insert(
                    calendarId="primary", 
                    body=event_body
                ).execute()
                event_id = event.get("id")
            except Exception as e:
                print(f"[Calendar] Error creating event for {item.get('title')}: {e}")

            if task_id or event_id:
                database.mark_assignment_calendar_synced(item.get("id"), event_id=event_id, task_id=task_id)
                synced_results.append({
                    "title": item.get("title"),
                    "course_name": item.get("course_name"),
                    "due_date": f"{due_date} {due_time}",
                    "is_task": bool(task_id),
                    "event_link": event.get("htmlLink") if event_id else None
                })

        return synced_results

    def create_custom_calendar_event(
        self,
        title: str,
        due_date: str,
        due_time: str = "23:59",
        end_time: Optional[str] = None,
        task_type: str = "กำหนดการ",
        course_name: str = "กำหนดการจากแชท",
        description: str = "",
        location: Optional[str] = None,
        summary_thai: str = "",
        summary_english: str = "",
        alternate_link: str = ""
    ) -> Dict[str, Any]:
        """Create a custom Google Calendar event and/or Google Task on demand (e.g. from Discord chat message)"""
        if not due_date:
            due_date = datetime.now().strftime("%Y-%m-%d")
        if not due_time:
            due_time = "23:59"

        # Calculate start and end ISO datetimes (+07:00)
        try:
            t_parts = [int(p) for p in due_time.split(":")]
            h, m = t_parts[0], t_parts[1]
            if end_time:
                end_parts = [int(p) for p in end_time.split(":")]
                eh, em = end_parts[0], end_parts[1]
                start_dt_obj = datetime.strptime(f"{due_date} {h:02d}:{m:02d}", "%Y-%m-%d %H:%M")
                end_dt_obj = datetime.strptime(f"{due_date} {eh:02d}:{em:02d}", "%Y-%m-%d %H:%M")
            else:
                is_sub = any(w in str(task_type).lower() for w in ["การบ้าน", "ส่งงาน", "assignment", "งาน", "ควิซ", "quiz"])
                if is_sub:
                    end_dt_obj = datetime.strptime(f"{due_date} {h:02d}:{m:02d}", "%Y-%m-%d %H:%M")
                    start_dt_obj = end_dt_obj - timedelta(hours=1) if h > 0 else end_dt_obj
                else:
                    start_dt_obj = datetime.strptime(f"{due_date} {h:02d}:{m:02d}", "%Y-%m-%d %H:%M")
                    end_dt_obj = start_dt_obj + timedelta(hours=1)
            dt_start_str = start_dt_obj.strftime("%Y-%m-%dT%H:%M:00+07:00")
            dt_end_str = end_dt_obj.strftime("%Y-%m-%dT%H:%M:00+07:00")
        except Exception:
            dt_start_str = f"{due_date}T{due_time}:00+07:00"
            dt_end_str = f"{due_date}T{due_time}:00+07:00"

        # Build bilingual description
        loc_str = f"• สถานที่: {location}\n" if location else ""
        loc_str_en = f"• Location: {location}\n" if location else ""
        time_display = f"{due_time} น." + (f" - {end_time} น." if end_time else "")
        time_display_en = f"{due_time}" + (f" - {end_time}" if end_time else "")

        desc_body = (
            f"🇹🇭 【รายละเอียดภาษาไทย】\n"
            f"• กิจกรรม/งาน: {title}\n"
            f"• ประเภท: {task_type}\n"
            f"• วิชา/ที่มา: {course_name}\n"
            f"• กำหนดการ: {due_date} เวลา {time_display}\n"
            f"{loc_str}"
            f"• สรุปงาน: {summary_thai or title}\n"
            + (f"• รายละเอียด: {description}\n" if description else "")
            + (f"• ลิงก์: {alternate_link}\n" if alternate_link else "")
            + f"\n──────────────────────────────────\n"
            f"🇬🇧 【English Summary】\n"
            f"• Event/Task: {title}\n"
            f"• Type: {task_type}\n"
            f"• Course/Source: {course_name}\n"
            f"• Schedule: {due_date} at {time_display_en}\n"
            f"{loc_str_en}"
            f"• Summary: {summary_english or title}\n"
            + (f"• Details: {description}\n" if description else "")
            + (f"• Link: {alternate_link}\n" if alternate_link else "")
        )

        task_id = None
        event_id = None
        html_link = None
        is_submission = any(w in str(task_type).lower() for w in ["การบ้าน", "ส่งงาน", "assignment", "งาน", "ประเมิน", "quiz", "ควิซ"])

        # 1. Optionally insert into Google Tasks if submission
        if is_submission and self.tasks:
            try:
                task_body = {
                    "title": f"📌 [{task_type}] {course_name}: {title}",
                    "notes": desc_body,
                    "due": f"{due_date}T00:00:00.000Z"
                }
                res_task = self.tasks.tasks().insert(tasklist="@default", body=task_body).execute()
                task_id = res_task.get("id")
            except Exception as te:
                print(f"[Google Tasks Notice on custom event]: {te}")

        # 2. Insert into Google Calendar Event
        try:
            event_body = {
                "summary": f"📌 [{task_type}] {course_name}: {title}",
                "description": desc_body,
                "start": {"dateTime": dt_start_str, "timeZone": "Asia/Bangkok"},
                "end": {"dateTime": dt_end_str, "timeZone": "Asia/Bangkok"},
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "popup", "minutes": 24 * 60},
                        {"method": "popup", "minutes": 120},
                    ]
                }
            }
            if location:
                event_body["location"] = location

            event = self.calendar.events().insert(calendarId="primary", body=event_body).execute()
            event_id = event.get("id")
            html_link = event.get("htmlLink")
        except Exception as ce:
            print(f"[Google Calendar Error on custom event]: {ce}")

        # Record in SQLite database
        custom_id = f"custom_{abs(hash(title + str(due_date) + str(due_time)))}"
        database.save_assignment({
            "id": custom_id,
            "course_id": "discord_chat",
            "course_name": course_name,
            "title": title,
            "description": description or summary_thai,
            "due_date": due_date,
            "due_time": due_time,
            "task_type": task_type,
            "alternate_link": html_link or alternate_link or "",
            "raw_deadline": f"{due_date} {time_display}",
            "summary_thai": summary_thai,
            "summary_english": summary_english
        })
        if event_id or task_id:
            database.mark_assignment_calendar_synced(custom_id, event_id=event_id, task_id=task_id)

        return {
            "title": title,
            "course_name": course_name,
            "due_date": due_date,
            "due_time": due_time,
            "end_time": end_time,
            "task_type": task_type,
            "location": location,
            "summary_thai": summary_thai,
            "summary_english": summary_english,
            "event_id": event_id,
            "task_id": task_id,
            "event_link": html_link,
            "is_task": bool(task_id)
        }

    def download_drive_file(self, file_id: str, file_name: str) -> Optional[str]:
        """Download file from Google Drive to local downloads folder"""
        try:
            target_path = os.path.join(DOWNLOADS_DIR, file_name)
            request = self.drive.files().get_media(fileId=file_id)
            with open(target_path, "wb") as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
            return target_path
        except Exception as e:
            print(f"[Drive] Error downloading file {file_name} ({file_id}): {e}")
            return None
