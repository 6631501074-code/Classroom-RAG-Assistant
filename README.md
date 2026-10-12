# Classroom RAG Assistant 🎓🤖

ผู้ช่วยวิชาการส่วนตัวผ่าน Discord เชื่อมต่อกับ Google Classroom, คลังเอกสาร Vector Database (ChromaDB), และ Google Calendar

---

## 🌟 ฟีเจอร์หลัก
1. **Google Classroom Sync (`!sync`):** ดึงรายวิชา งานที่มอบหมาย (Coursework), กำหนดส่ง (Deadline), และประกาศ/สไลด์ทั้งหมด เข้าสู่ระบบ RAG
2. **Google Calendar Sync (`!calendar`):** บันทึกกำหนดส่งงานและการบ้านลง Google Calendar อัตโนมัติ พร้อมตั้งแจ้งเตือนล่วงหน้า 1 วัน และ 2 ชั่วโมง
3. **RAG Vector Database (ChromaDB + Gemini):** ค้นหาและตอบคำถามจากบริบทจริงเท่านั้น
   - หากถามเรื่องงาน/การบ้าน: สรุป **ชื่อวิชา, หัวเรื่อง, กำหนดส่ง (Deadline), และรายละเอียด**
   - หากถามเนื้อหาในเอกสาร: ตอบคำถามพร้อมระบุ **ชื่อไฟล์อ้างอิง (Source Document)**
   - หากไม่พบข้อมูล: ตอบอย่างปลอดภัยว่า *"ไม่พบข้อมูลในระบบ ลองพิมพ์ !sync หรืออัปโหลดไฟล์เพิ่มเติม"*
4. **Discord DM & File Ingestion:** 
   - สามารถลากไฟล์ **PDF** โยนเข้ามาในแชท Discord ได้โดยตรง ระบบจะดูดเข้า Vector DB ให้อัตโนมัติ
   - สามารถทัก DM ถามคำถามกับบอทได้ทันที

---

## 🛠️ โครงสร้างไฟล์
```
Classroom RAG Assistant/
├── .env                  # Discord Token & Gemini API Key
├── credentials.json      # Google OAuth 2.0 Client credentials
├── token.json            # Google OAuth token (สร้างอัตโนมัติเมื่อล็อกอินครั้งแรก)
├── requirements.txt      # รายการแพ็กเกจ Python
├── config.py             # ตั้งค่าระบบและ Scopes
├── database.py           # จัดการฐานข้อมูล SQLite (classroom_bot.db)
├── google_service.py     # ตัวจัดการเชื่อมต่อ Google Classroom, Calendar, Drive
├── rag_engine.py         # คอร์นิวเคลียส RAG (ChromaDB + Gemini API)
├── bot.py                # ระบบ Discord Bot
└── test_setup.py         # สคริปต์ทดสอบการตั้งค่าและล็อกอิน Google
```

---

## 🚀 ขั้นตอนการติดตั้งและเริ่มใช้งาน

### 1. ติดตั้ง Dependencies
เปิด Terminal / PowerShell ในโฟลเดอร์นี้ แล้วรันคำสั่ง:
```bash
pip install -r requirements.txt
```

### 2. ทดสอบระบบและล็อกอิน Google ครั้งแรก
รันสคริปต์ตรวจสอบระบบพร้อมเปิดหน้าเว็บล็อกอิน Google:
```bash
python test_setup.py --auth
```
- ระบบจะเปิดเบราว์เซอร์ขึ้นมา ให้เลือกล็อกอินด้วยบัญชี **`6631501074@lamduan.mfu.ac.th`**
- กด **"Continue"** เพื่ออนุญาตสิทธิ์เข้าถึง Classroom, Calendar, และ Drive
- เมื่อขึ้น Success แล้ว ระบบจะสร้างไฟล์ `token.json` ให้อัตโนมัติ

### 3. รัน Discord Bot
```bash
python bot.py
```

---

## 💬 คำสั่งบอทใน Discord
| คำสั่ง | คำอธิบาย |
|---|---|
| `!sync` | ดึงข้อมูล Classroom ล่าสุด และบันทึกกำหนดส่งลง Google Calendar |
| `!resync` | ลบกิจกรรมเดิมใน Calendar แล้วซิงค์ใหม่พร้อมสรุป 2 ภาษา (ไทย + อังกฤษ) |
| `!clean_calendar` | ลบกิจกรรมงานที่บอทเคยลงไว้ใน Google Calendar ทั้งหมด |
| `!homework` หรือ `!hw` | สรุปรายการการบ้าน งานที่ซ่อนอยู่ในประกาศ และกำหนดการทั้งหมด |
| `!courses` | แสดงรายชื่อวิชาทั้งหมดที่ลงทะเบียนอยู่ |
| `!ask <คำถาม>` | ถามคำถามเกี่ยวกับเนื้อหาหรือการบ้าน |
| **📓 โหมดสมุดโน้ต (NotebookLM Style)** | |
| `!notebook <ชื่อวิชา>` | เปิดห้อง Thread สมุดโน้ตแยกเฉพาะวิชานั้นๆ ทันที |
| `!studyguide <หัวข้อ>` | สร้างคู่มือสรุปเนื้อหาและประเด็นเก็งข้อสอบ |
| `!quiz <หัวข้อ>` | สร้างแบบทดสอบ 3 ข้อ พร้อมเฉลยซ่อนสปอยเลอร์ `\|\|เฉลย\|\|` |
| `!image <หัวข้อ>` | เจนภาพ Infographic / Mind Map ประกอบการเรียน |
| `!summarize <หัวข้อ>` | สรุปเนื้อหาแบบรวบรัดอ่านจบใน 1 นาที |
| **ส่งไฟล์ PDF** | ลากไฟล์ PDF ส่งในแชท เพื่อเพิ่มเข้าสู่ระบบ RAG และสแกนเดดไลน์อัตโนมัติ |
| **แชทใน DM หรือ #การศึกษา** | พิมพ์คำถามคุยกับบอทได้โดยตรง ไม่ต้องพิมพ์คำสั่ง |
