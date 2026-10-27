import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Tokens and Keys
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Gemini API Models with multi-model fallback priority
GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
]

# Google OAuth Paths & Scopes
CREDENTIALS_FILE = str(BASE_DIR / os.getenv("CREDENTIALS_FILE", "credentials.json"))
TOKEN_FILE = str(BASE_DIR / os.getenv("TOKEN_FILE", "token.json"))

# Allow Google OAuth scope modifications/aliases
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Database and Storage Paths
DATABASE_FILE = str(BASE_DIR / os.getenv("DATABASE_FILE", "classroom_bot.db"))
CHROMA_PERSIST_DIR = str(BASE_DIR / os.getenv("CHROMA_PERSIST_DIR", "chroma_db"))
DOWNLOADS_DIR = str(BASE_DIR / os.getenv("DOWNLOADS_DIR", "downloads"))

# Allowed channel name for bot interactions in Discord server
ALLOWED_CHANNEL_NAME = os.getenv("ALLOWED_CHANNEL_NAME", "การศึกษา")

# Automatic Background Sync & Notification Settings
AUTO_SYNC_INTERVAL_HOURS = int(os.getenv("AUTO_SYNC_INTERVAL_HOURS", "2"))
AUTO_SYNC_ENABLED = os.getenv("AUTO_SYNC_ENABLED", "true").lower() in ("true", "1", "yes")

# Courses to exclude from syncing, database, calendar, and bot responses
EXCLUDED_COURSES = [
    # Explicitly excluded by user
    "1501415 Computer Vision and Visual Analytics",
    "Computer Vision and Visual Analytics",
    "1501415",
    "855592719405",
    # Past academic years / semesters (still left ACTIVE by instructors in Google Classroom)
    "2/2568",
    "1/2568",
    "2568",
    "2567",
    "2566",
    "836837520252",  # [2/2568] 1501225 Cloud Computing
    "836840776886",  # [2/2568] 1806105 Fitness and Exercise for Life
    "821791340981",  # [2/2568] 1501401 Computer Engineering Pre-Project
    "836840331476",  # [2/2568] 1501345 Network System Security
    "821790165651",  # [2/2568] 1501209 Computer Architecture & Operating Systems
    "783189695203",  # [1/2568] 1501319 Fundamental of Electrical Engineering
    "697473210349",  # 1501430 Introduction to Data Science (1/2567)
]

# Ensure directories exist
Path(CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)
Path(DOWNLOADS_DIR).mkdir(parents=True, exist_ok=True)
