import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Tokens and Keys
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

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

# Ensure directories exist
Path(CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)
Path(DOWNLOADS_DIR).mkdir(parents=True, exist_ok=True)
