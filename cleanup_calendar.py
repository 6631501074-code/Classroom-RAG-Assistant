"""
Standalone script to delete all bot events from Google Calendar and reset database
"""
from google_service import GoogleManager

def main():
    print("🧹 Connecting to Google Calendar...")
    mgr = GoogleManager()
    print("⏳ Deleting all bot-created events from primary calendar...")
    deleted = mgr.delete_all_calendar_events()
    print(f"✅ Deleted {deleted} events successfully and reset database state.")

if __name__ == "__main__":
    main()
