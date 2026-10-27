import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from config import DATABASE_FILE, EXCLUDED_COURSES

def get_connection():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database tables"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Courses table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                course_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                section TEXT
            )
        """)
        
        # Assignments table (supports both official coursework and extracted announcements/syllabus tasks)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                course_name TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                due_date TEXT,
                due_time TEXT,
                alternate_link TEXT,
                calendar_event_id TEXT,
                synced_to_calendar INTEGER DEFAULT 0,
                task_type TEXT DEFAULT 'การบ้าน',
                raw_deadline TEXT,
                summary_thai TEXT,
                summary_english TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Upgrade existing database if missing columns
        cursor.execute("PRAGMA table_info(assignments)")
        cols = [c[1] for c in cursor.fetchall()]
        for col_name, col_def in [
            ("task_type", "TEXT DEFAULT 'การบ้าน'"),
            ("raw_deadline", "TEXT"),
            ("summary_thai", "TEXT"),
            ("summary_english", "TEXT"),
            ("google_task_id", "TEXT")
        ]:
            if col_name not in cols:
                try:
                    cursor.execute(f"ALTER TABLE assignments ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass
        
        # Synced documents table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS synced_documents (
                id TEXT PRIMARY KEY,
                course_id TEXT,
                file_name TEXT NOT NULL,
                file_path TEXT,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def save_courses(courses: List[Dict[str, Any]]):
    with get_connection() as conn:
        cursor = conn.cursor()
        for c in courses:
            c_name = c.get("name", "")
            c_id = str(c.get("id", ""))
            c_sec = str(c.get("section", ""))
            if any(ex.lower() in c_name.lower() or ex.lower() in c_sec.lower() or ex == c_id for ex in EXCLUDED_COURSES):
                continue
            cursor.execute("""
                INSERT OR REPLACE INTO courses (course_id, name, section)
                VALUES (?, ?, ?)
            """, (c.get("id"), c_name, c.get("section", "")))
        conn.commit()

def save_assignment(assignment: Dict[str, Any]):
    c_name = assignment.get("course_name", "")
    c_id = str(assignment.get("course_id", ""))
    if any(ex.lower() in c_name.lower() or ex == c_id for ex in EXCLUDED_COURSES):
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO assignments (
                id, course_id, course_name, title, description, 
                due_date, due_time, alternate_link, task_type,
                raw_deadline, summary_thai, summary_english, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                course_name=excluded.course_name,
                title=excluded.title,
                description=excluded.description,
                due_date=excluded.due_date,
                due_time=excluded.due_time,
                alternate_link=excluded.alternate_link,
                task_type=excluded.task_type,
                raw_deadline=excluded.raw_deadline,
                summary_thai=excluded.summary_thai,
                summary_english=excluded.summary_english,
                updated_at=CURRENT_TIMESTAMP
        """, (
            assignment.get("id"),
            assignment.get("course_id", ""),
            assignment.get("course_name", ""),
            assignment.get("title", ""),
            assignment.get("description", ""),
            assignment.get("due_date"),
            assignment.get("due_time"),
            assignment.get("alternate_link", ""),
            assignment.get("task_type", "การบ้าน"),
            assignment.get("raw_deadline", ""),
            assignment.get("summary_thai", ""),
            assignment.get("summary_english", "")
        ))
        conn.commit()

def get_unsynced_calendar_assignments(days_back: int = 30) -> List[Dict[str, Any]]:
    cutoff_date = (datetime.now().date() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    with get_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT * FROM assignments 
            WHERE synced_to_calendar = 0 AND due_date IS NOT NULL AND due_date >= ?
        """
        params = [cutoff_date]
        for ex in EXCLUDED_COURSES:
            query += " AND course_name NOT LIKE ? AND course_id != ?"
            params.extend([f"%{ex}%", ex])
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

def mark_assignment_calendar_synced(assignment_id: str, event_id: Optional[str] = None, task_id: Optional[str] = None):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE assignments 
            SET synced_to_calendar = 1, calendar_event_id = ?, google_task_id = ? 
            WHERE id = ?
        """, (event_id, task_id, assignment_id))
        conn.commit()

def reset_calendar_sync():
    """Reset calendar sync flags so all assignments can be re-synced"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE assignments 
            SET synced_to_calendar = 0, calendar_event_id = NULL, google_task_id = NULL
        """)
        conn.commit()

def get_synced_calendar_event_ids() -> List[str]:
    """Get all event IDs recorded in database"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT calendar_event_id FROM assignments 
            WHERE calendar_event_id IS NOT NULL AND calendar_event_id != ''
        """)
        rows = cursor.fetchall()
        return [r["calendar_event_id"] for r in rows]

def get_synced_google_task_ids() -> List[str]:
    """Get all Google Task IDs recorded in database"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT google_task_id FROM assignments 
            WHERE google_task_id IS NOT NULL AND google_task_id != ''
        """)
        rows = cursor.fetchall()
        return [r["google_task_id"] for r in rows]

def clear_all_assignments():
    """Clear all assignments from database for clean slate resync"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM assignments")
        conn.commit()

def cleanup_old_assignments(days_back: int = 60):
    """Remove assignments older than days_back (default 60 days / 2 months) and excluded courses from SQLite"""
    cutoff_date = (datetime.now().date() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM assignments WHERE due_date IS NOT NULL AND due_date < ?", (cutoff_date,))
        cursor.execute("DELETE FROM assignments WHERE due_date IS NULL AND updated_at < ?", (cutoff_date,))
        for ex in EXCLUDED_COURSES:
            cursor.execute("DELETE FROM courses WHERE name LIKE ? OR section LIKE ? OR course_id = ?", (f"%{ex}%", f"%{ex}%", ex))
            cursor.execute("DELETE FROM assignments WHERE course_name LIKE ? OR course_id = ?", (f"%{ex}%", ex))
        conn.commit()

def remove_course_data(course_identifier: str):
    """Explicitly delete a course and its assignments from SQLite"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM courses WHERE name LIKE ? OR course_id = ?", (f"%{course_identifier}%", course_identifier))
        cursor.execute("DELETE FROM assignments WHERE course_name LIKE ? OR course_id = ?", (f"%{course_identifier}%", course_identifier))
        conn.commit()

def get_active_and_upcoming_assignments(course_name_filter: Optional[str] = None, days_back: int = 60) -> List[Dict[str, Any]]:
    """Retrieve assignments that are upcoming or within the active semester (default 60 days)"""
    cutoff_date = (datetime.now().date() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    with get_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT * FROM assignments 
            WHERE (due_date >= ? OR (due_date IS NULL AND updated_at >= ?))
        """
        params = [cutoff_date, cutoff_date]
        if course_name_filter and course_name_filter.lower() != "all":
            query += " AND course_name LIKE ?"
            params.append(f"%{course_name_filter}%")
        
        for ex in EXCLUDED_COURSES:
            query += " AND course_name NOT LIKE ? AND course_id != ?"
            params.extend([f"%{ex}%", ex])
            
        query += " ORDER BY CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

def get_all_assignments(course_name_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    return get_active_and_upcoming_assignments(course_name_filter, days_back=60)

def is_document_synced(doc_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM synced_documents WHERE id = ?", (doc_id,))
        return cursor.fetchone() is not None

def record_synced_document(doc_id: str, course_id: Optional[str], file_name: str, file_path: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO synced_documents (id, course_id, file_name, file_path, synced_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (doc_id, course_id, file_name, file_path))
        conn.commit()
