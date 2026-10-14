"""
Setup and Verification Script for Classroom RAG Assistant
This script verifies:
1. API Keys & Configurations
2. Gemini API Connectivity
3. ChromaDB Initialization
4. Google OAuth Flow (generates token.json on first run)
"""

import os
import sys
import requests
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import (
    DISCORD_TOKEN,
    GEMINI_API_KEY,
    CREDENTIALS_FILE,
    TOKEN_FILE,
    GOOGLE_SCOPES,
    GEMINI_MODELS
)

def test_config():
    print("========================================")
    print("1. Checking Environment & Credentials")
    print("========================================")
    
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN is missing in .env")
        return False
    print(f"✅ Discord Token configured: {DISCORD_TOKEN[:10]}...")

    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY is missing in .env")
        return False
    print(f"✅ Gemini API Key configured: {GEMINI_API_KEY[:10]}...")

    if not os.path.exists(CREDENTIALS_FILE):
        print(f"❌ Google credentials file not found at: {CREDENTIALS_FILE}")
        return False
    print(f"✅ Google credentials.json found.")
    return True

def test_gemini_api():
    print("\n========================================")
    print("2. Testing Gemini API Connection")
    print("========================================")
    
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    payload = {
        "contents": [
            {"parts": [{"text": "ทดสอบระบบ ตอบสั้นๆ ว่า: Classroom RAG Assistant พร้อมทำงาน"}]}
        ]
    }
    for model_name in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        print(f"Connecting to Gemini ({model_name})...")
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=20)
            if res.status_code == 200:
                data = res.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                print(f"✅ Gemini Response ({model_name}): {text.strip()}")
                return True
            else:
                print(f"⚠️ Model {model_name} returned HTTP {res.status_code}, trying next model...")
                continue
        except Exception as e:
            print(f"⚠️ Exception connecting to {model_name}: {e}")
            continue

    print("❌ All Gemini models exhausted or unavailable.")
    return False

def test_google_auth(force: bool = False):
    print("\n========================================")
    print("3. Testing / Initializing Google OAuth")
    print("========================================")
    try:
        from google_service import get_credentials
        print("ℹ️ Opening Google OAuth authentication if token.json is not yet created or scopes updated...")
        creds = get_credentials(force_reauth=force)
        if creds and creds.valid:
            print("✅ Google OAuth authenticated successfully! (token.json created/verified)")
            return True
        else:
            print("❌ Google OAuth failed.")
            return False
    except Exception as e:
        print(f"❌ Google OAuth error: {e}")
        return False

def main():
    if not test_config():
        sys.exit(1)
        
    if not test_gemini_api():
        sys.exit(1)

    print("\nAll initial tests passed!")
    print("Would you like to test Google Login now? If so, run:")
    print("   python test_setup.py --auth")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ["--auth", "--reauth", "-a"]:
        force = sys.argv[1] == "--reauth"
        if test_config():
            test_gemini_api()
            test_google_auth(force=force)
    else:
        main()
