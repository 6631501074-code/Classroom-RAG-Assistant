import os
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import discord
from discord.ext import commands, tasks

from config import (
    DISCORD_TOKEN, 
    DOWNLOADS_DIR, 
    ALLOWED_CHANNEL_NAME,
    AUTO_SYNC_INTERVAL_HOURS,
    AUTO_SYNC_ENABLED
)
import database
from google_service import GoogleManager
from rag_engine import RAGEngine
import io
import study_features
from pypdf import PdfReader
from task_extractor import extract_tasks_from_text

# Setup Discord bot
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Initialize subsystems
database.init_db()
rag = RAGEngine()
google_mgr: GoogleManager = None
last_daily_reminder_date = ""

def get_google_mgr():
    global google_mgr
    if google_mgr is None:
        google_mgr = GoogleManager()
    return google_mgr

async def run_auto_sync_cycle(feedback_channel=None):
    """Executes a full background synchronization and posts alerts if new items are found"""
    global last_daily_reminder_date
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔄 เริ่มต้น Auto-Sync ในเบื้องหลัง...")
    try:
        mgr = get_google_mgr()
        
        # 1. Cleanup old assignments older than 60 days
        await asyncio.to_thread(database.cleanup_old_assignments, 60)

        # 2. Fetch Coursework
        assignments = await asyncio.to_thread(mgr.fetch_all_coursework, 60)
        await asyncio.to_thread(rag.add_assignments_batch, assignments)

        # 3. Fetch announcements and materials
        items = await asyncio.to_thread(mgr.fetch_course_materials_and_announcements, 60, 120)
        await asyncio.to_thread(rag.add_classroom_items_batch, items)

        # 4. Sync new events & tasks to Google Calendar
        new_calendar_items = await asyncio.to_thread(mgr.sync_to_google_calendar, 60)

        # 5. Find target channel #การศึกษา
        target_channel = feedback_channel
        if not target_channel:
            for guild in bot.guilds:
                for channel in guild.text_channels:
                    if ALLOWED_CHANNEL_NAME.lower() in channel.name.lower():
                        target_channel = channel
                        break
                if target_channel:
                    break

        # 6. If new items were synced to Calendar/Tasks, alert in the channel!
        if target_channel and new_calendar_items:
            embed = discord.Embed(
                title="🔔 [ระบบอัตโนมัติ] ตรวจพบกำหนดการ / งานใหม่จาก Google Classroom!",
                description=f"บอทได้ทำการซิงค์และบันทึกลง Google Calendar & Tasks เรียบร้อยแล้ว **{len(new_calendar_items)}** รายการ:",
                color=discord.Color.green()
            )
            for ev in new_calendar_items[:6]:
                cat = "☑️ หมวดงาน (Task)" if ev.get("is_task") else "📅 กิจกรรม (Event)"
                embed.add_field(
                    name=f"[{cat}] {ev.get('course_name')}",
                    value=f"• **{ev.get('title')}**\n• กำหนดส่ง/นัดหมาย: `{ev.get('due_date')}`",
                    inline=False
                )
            if len(new_calendar_items) > 6:
                embed.set_footer(text=f"และอีก {len(new_calendar_items) - 6} รายการ (พิมพ์ !homework เพื่อดูทั้งหมด)")
            else:
                embed.set_footer(text="พิมพ์ !homework เพื่อดูสรุปงานทั้งหมด")
            await target_channel.send(embed=embed)
        elif feedback_channel and not new_calendar_items:
            await feedback_channel.send("ℹ️ Auto-Sync เสร็จสิ้น: ข้อมูลเป็นปัจจุบันแล้ว และไม่มีรายการใหม่ที่ต้องซิงค์ลง Calendar")

        # 7. Check for upcoming deadlines today & tomorrow (Daily Reminder)
        today_str = datetime.now().strftime("%Y-%m-%d")
        tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        if target_channel and last_daily_reminder_date != today_str:
            upcoming = database.get_active_and_upcoming_assignments(days_back=0)
            due_soon = [
                t for t in upcoming 
                if t.get("due_date") in (today_str, tomorrow_str)
            ]
            if due_soon:
                rem_embed = discord.Embed(
                    title="⏰ แจ้งเตือนงานที่ใกล้ถึงกำหนดส่ง (วันนี้ & พรุ่งนี้)!",
                    description="อย่าลืมตรวจเช็กและส่งงานให้ตรงเวลากันนะครับ:",
                    color=discord.Color.orange()
                )
                for t in due_soon[:8]:
                    when = "🔴 วันนี้!" if t.get("due_date") == today_str else "🟡 พรุ่งนี้"
                    due_t = f"{t.get('due_date')} {t.get('due_time', '')}".strip()
                    rem_embed.add_field(
                        name=f"{when} | {t.get('course_name')}",
                        value=f"• **{t.get('title')}**\n• กำหนดส่ง: `{due_t}`",
                        inline=False
                    )
                rem_embed.set_footer(text="พิมพ์ !homework เพื่อดูรายละเอียดงานทั้งหมด")
                await target_channel.send(embed=rem_embed)
                last_daily_reminder_date = today_str

        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Auto-Sync เสร็จสิ้นเรียบร้อย (ซิงค์ปฏิทินใหม่: {len(new_calendar_items)} รายการ)")

    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ Auto-Sync Error: {e}")
        if feedback_channel:
            await feedback_channel.send(f"❌ เกิดข้อผิดพลาดระหว่าง Auto-Sync: {e}")

@tasks.loop(hours=AUTO_SYNC_INTERVAL_HOURS)
async def auto_sync_loop():
    if AUTO_SYNC_ENABLED:
        await run_auto_sync_cycle()

@auto_sync_loop.before_loop
async def before_auto_sync():
    await bot.wait_until_ready()
    # Wait 10 seconds after bot is online before doing the first sync
    await asyncio.sleep(10)

@bot.event
async def on_ready():
    print(f"==================================================")
    print(f"🤖 Classroom RAG Assistant is online as {bot.user}")
    print(f"==================================================")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching, 
            name="Google Classroom | พิมพ์ !help"
        )
    )
    if AUTO_SYNC_ENABLED and not auto_sync_loop.is_running():
        auto_sync_loop.start()
        print(f"⏰ Background Auto-Sync loop started (every {AUTO_SYNC_INTERVAL_HOURS} hours)")

@bot.command(name="help")
async def help_cmd(ctx):
    """Show help guide"""
    embed = discord.Embed(
        title="📚 Classroom RAG Assistant",
        description="ผู้ช่วยวิชาการส่วนตัว เชื่อมต่อ Google Classroom, คลังเอกสาร RAG และ Google Calendar",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="⚡ คำสั่งหลัก",
        value=(
            "• `!sync` - ดึงข้อมูลงานล่าสุดจาก Classroom และซิงค์ลง Google Calendar\n"
            "• `!autosync` - ตรวจสอบหรือตั้งค่าระบบซิงค์อัตโนมัติในเบื้องหลัง\n"
            "• `!resync` - ลบกิจกรรมเดิมใน Calendar แล้วซิงค์ใหม่พร้อมสรุป 2 ภาษา (ไทย+อังกฤษ)\n"
            "• `!clean_calendar` - ลบกิจกรรมของบอทที่เคยลงไว้ใน Google Calendar ทั้งหมด\n"
            "• `!homework` หรือ `!hw` - ดูรายการการบ้านและงานทั้งหมดที่ต้องทำ\n"
            "• `!courses` - ดูรายชื่อวิชาทั้งหมดที่ลงทะเบียนเรียนอยู่\n"
            "• `!ask <คำถาม>` - ถามคำถามเนื้อหาหรือการบ้าน (หรือพิมพ์ถามใน DM ได้เลย)"
        ),
        inline=False
    )
    embed.add_field(
        name="📓 โหมดสมุดโน้ต & ทบทวนบทเรียน (NotebookLM Style)",
        value=(
            "• `!notebook <ชื่อวิชา>` - เปิดห้อง Thread สมุดโน้ตแยกเฉพาะวิชานั้นๆ\n"
            "• `!studyguide <หัวข้อ/วิชา>` - สร้างคู่มือสรุปเนื้อหาและประเด็นเก็งข้อสอบ\n"
            "• `!quiz <หัวข้อ/วิชา>` - สร้างแบบทดสอบ 3 ข้อ พร้อมเฉลยซ่อนสปอยเลอร์\n"
            "• `!image <หัวข้อ>` - เจนภาพ Infographic / Mind Map ประกอบการเรียน\n"
            "• `!summarize <หัวข้อ>` - สรุปเนื้อหาแบบรวบรัดอ่านจบใน 1 นาที"
        ),
        inline=False
    )
    embed.add_field(
        name="📎 การอัปโหลดเอกสาร",
        value="ลากไฟล์ **PDF** ส่งเข้ามาในแชทนี้ได้เลย บอทจะนำเข้าสู่ระบบ RAG และสแกนหากำหนดการให้อัตโนมัติ",
        inline=False
    )
    embed.set_footer(text="ระบบตอบคำถามโดยอ้างอิงจากข้อมูลจริงเท่านั้น")
    await ctx.send(embed=embed)

@bot.command(name="courses")
async def list_courses(ctx):
    """List enrolled courses"""
    msg = await ctx.send("🔍 กำลังดึงรายชื่อวิชาจาก Google Classroom...")
    try:
        mgr = get_google_mgr()
        courses = await asyncio.to_thread(mgr.fetch_courses)
        if not courses:
            await msg.edit(content="⚠️ ไม่พบคอร์สเรียนที่เปิดใช้งานอยู่ในขณะนี้")
            return

        lines = ["**📚 รายชื่อวิชาทั้งหมด:**"]
        for idx, c in enumerate(courses, 1):
            section = f" (กลุ่ม {c['section']})" if c.get("section") else ""
            lines.append(f"{idx}. **{c.get('name')}**{section}")
            
        await msg.edit(content="\n".join(lines))
    except Exception as e:
        await msg.edit(content=f"❌ เกิดข้อผิดพลาด: {str(e)}")

@bot.command(name="sync")
async def sync_data(ctx):
    """Sync coursework, announcements, and Google Calendar"""
    status_msg = await ctx.send("⏳ กำลังเริ่มซิงค์ข้อมูลจาก Google Classroom (กรองเฉพาะช่วงปัจจุบัน)...")
    
    try:
        mgr = get_google_mgr()
        
        # Prune old assignments from database so it doesn't accumulate ancient items
        await asyncio.to_thread(database.cleanup_old_assignments)

        # 1. Fetch Coursework
        await status_msg.edit(content="⏳ [1/3] กำลังดึงข้อมูลการบ้านและงานที่มอบหมาย...")
        assignments = await asyncio.to_thread(mgr.fetch_all_coursework)
        await asyncio.to_thread(rag.add_assignments_batch, assignments)

        # 2. Fetch Announcements & Materials
        await status_msg.edit(content="⏳ [2/3] กำลังดึงประกาศและเอกสารเนื้อหาล่าสุด...")
        items = await asyncio.to_thread(mgr.fetch_course_materials_and_announcements)
        await asyncio.to_thread(rag.add_classroom_items_batch, items)

        # 3. Sync to Google Calendar
        await status_msg.edit(content="⏳ [3/3] กำลังบันทึกกำหนดส่งงานลง Google Calendar...")
        calendar_events = await asyncio.to_thread(mgr.sync_to_google_calendar)

        # Build report
        report = [
            "✅ **ซิงค์ข้อมูลสำเร็จเรียบร้อยแล้ว!**",
            f"• บันทึกการบ้าน: **{len(assignments)}** รายการ",
            f"• บันทึกประกาศและเนื้อหา: **{len(items)}** รายการ",
            f"• ซิงค์ลง Calendar / Tasks: **{len(calendar_events)}** รายการใหม่",
        ]
        
        if calendar_events:
            report.append("\n**📌 รายการที่บันทึกลง Calendar / Tasks:**")
            for ev in calendar_events[:5]:
                cat = "☑️ หมวดงาน (Task - ติ๊กแล้วจาง)" if ev.get("is_task") else "📅 กิจกรรม (Event)"
                report.append(f"- [{cat}] **{ev['course_name']}**: {ev['title']} (ครบกำหนด: `{ev['due_date']}`)")
            if len(calendar_events) > 5:
                report.append(f"_...และอีก {len(calendar_events) - 5} รายการ_")

        report.append("\n💡 *ตอนนี้คุณสามารถพิมพ์ถามคำถามเนื้อหา หรือเช็กการบ้านผ่าน `!homework` ได้เลยครับ*")
        await status_msg.edit(content="\n".join(report))

    except Exception as e:
        await status_msg.edit(content=f"❌ เกิดข้อผิดพลาดระหว่างการซิงค์: {str(e)}")

@bot.command(name="autosync")
async def autosync_cmd(ctx, action: str = "status"):
    """Manage background auto-sync"""
    global AUTO_SYNC_ENABLED
    action_clean = action.strip().lower()
    
    if action_clean in ["on", "start", "enable"]:
        AUTO_SYNC_ENABLED = True
        if not auto_sync_loop.is_running():
            auto_sync_loop.start()
        await ctx.send(f"✅ **เปิดใช้งานระบบซิงค์อัตโนมัติเรียบร้อยแล้ว** (ทำงานทุกๆ {AUTO_SYNC_INTERVAL_HOURS} ชั่วโมง พร้อมแจ้งเตือนใน #{ALLOWED_CHANNEL_NAME})")
    elif action_clean in ["off", "stop", "disable"]:
        AUTO_SYNC_ENABLED = False
        if auto_sync_loop.is_running():
            auto_sync_loop.stop()
        await ctx.send("⏸️ **ปิดใช้งานระบบซิงค์อัตโนมัติชั่วคราวแล้ว** (คุณยังสามารถพิมพ์ `!sync` ได้ตามปกติ)")
    elif action_clean in ["now", "run"]:
        await ctx.send("⚡ กำลังสั่งให้ระบบ Auto-Sync ทำงานทันทีในเบื้องหลัง...")
        asyncio.create_task(run_auto_sync_cycle(feedback_channel=ctx.channel))
    else:
        status_text = "🟢 กำลังทำงาน (Active)" if (auto_sync_loop.is_running() and AUTO_SYNC_ENABLED) else "🔴 ปิดอยู่ (Inactive)"
        embed = discord.Embed(
            title="⚙️ สถานะระบบ Auto-Sync & แจ้งเตือนอัตโนมัติ",
            color=discord.Color.blue()
        )
        embed.add_field(name="สถานะการทำงาน", value=status_text, inline=True)
        embed.add_field(name="รอบความถี่", value=f"ทุกๆ {AUTO_SYNC_INTERVAL_HOURS} ชั่วโมง", inline=True)
        embed.add_field(name="ห้องแจ้งเตือนงาน", value=f"#{ALLOWED_CHANNEL_NAME}", inline=True)
        embed.add_field(
            name="💡 คำสั่งที่เกี่ยวข้อง",
            value=(
                "• `!autosync now` - สั่งให้ระบบเริ่มซิงค์และแจ้งเตือนทันที\n"
                "• `!autosync on` - เปิดระบบซิงค์อัตโนมัติ\n"
                "• `!autosync off` - ปิดระบบซิงค์อัตโนมัติชั่วคราว"
            ),
            inline=False
        )
        await ctx.send(embed=embed)

@bot.command(name="calendar")
async def sync_calendar_only(ctx):
    """Sync deadlines directly to Google Calendar"""
    msg = await ctx.send("📅 กำลังตรวจสอบและลงตาราง Google Calendar & Google Tasks...")
    try:
        mgr = get_google_mgr()
        results = await asyncio.to_thread(mgr.sync_to_google_calendar)
        if not results:
            await msg.edit(content="ℹ️ ไม่มีรายการงานใหม่ที่ต้องซิงค์ลง Calendar (ข้อมูลเป็นปัจจุบันแล้ว)")
            return
        
        lines = [f"✅ **บันทึกลง Google Calendar / Tasks เรียบร้อย {len(results)} รายการ:**"]
        for ev in results:
            cat = "☑️ หมวดงาน (Task)" if ev.get("is_task") else "📅 กิจกรรม (Event)"
            lines.append(f"• [{cat}] **{ev['course_name']}**: {ev['title']} (กำหนดส่ง: `{ev['due_date']}`)")
        await msg.edit(content="\n".join(lines))
    except Exception as e:
        await msg.edit(content=f"❌ เกิดข้อผิดพลาด: {str(e)}")

@bot.command(name="clean_calendar", aliases=["clearcale", "delete_calendar"])
async def clean_calendar_cmd(ctx):
    """Delete all previously synced events from Google Calendar"""
    msg = await ctx.send("🧹 กำลังค้นหาและลบกิจกรรมของบอทที่เคยบันทึกไว้ใน Google Calendar...")
    try:
        mgr = get_google_mgr()
        deleted_count = await asyncio.to_thread(mgr.delete_all_calendar_events)
        await msg.edit(content=f"🗑️ ลบกิจกรรมงานใน Google Calendar สำเร็จเรียบร้อยแล้ว **{deleted_count}** รายการ (พร้อมรีเซ็ตสถานะเพื่อซิงค์ใหม่)")
    except Exception as e:
        await msg.edit(content=f"❌ เกิดข้อผิดพลาดในการลบปฏิทิน: {str(e)}")

@bot.command(name="resync")
async def resync_cmd(ctx):
    """Clean old calendar events and re-sync everything fresh with bilingual summaries"""
    status_msg = await ctx.send("🔄 เริ่มต้นการล้างข้อมูลเดิมและซิงค์ใหม่แบบ 2 ภาษา (ไทย & อังกฤษ)...")
    try:
        mgr = get_google_mgr()
        
        # 1. Clean old calendar events, database assignments, and Chroma collection
        await status_msg.edit(content="🧹 [1/4] กำลังลบกิจกรรมเดิมใน Google Calendar และล้างฐานข้อมูลเดิม...")
        deleted_count = await asyncio.to_thread(mgr.delete_all_calendar_events)
        await asyncio.to_thread(database.clear_all_assignments)
        await asyncio.to_thread(rag.reset_collection)

        # 2. Fetch Coursework & update Vector DB
        await status_msg.edit(content="⏳ [2/4] กำลังดึงข้อมูลการบ้านล่าสุด (คัดกรองเฉพาะสัปดาห์ล่าสุดและอนาคต)...")
        assignments = await asyncio.to_thread(mgr.fetch_all_coursework)
        await asyncio.to_thread(rag.add_assignments_batch, assignments)

        # 3. Fetch announcements/materials
        await status_msg.edit(content="⏳ [3/4] กำลังดึงประกาศและเอกสารล่าสุด...")
        items = await asyncio.to_thread(mgr.fetch_course_materials_and_announcements)
        await asyncio.to_thread(rag.add_classroom_items_batch, items)

        # 4. Sync bilingual to Google Calendar
        await status_msg.edit(content="⏳ [4/4] กำลังบันทึกกิจกรรมลง Google Calendar พร้อมสรุป 🇹🇭 ไทย และ 🇬🇧 อังกฤษ...")
        calendar_events = await asyncio.to_thread(mgr.sync_to_google_calendar)

        report = [
            "✨ **รีซิงค์ข้อมูลใหม่สำเร็จเรียบร้อย!**",
            f"• ลบกิจกรรมเดิมออก: **{deleted_count}** รายการ",
            f"• ล้างข้อมูลเก่า และซิงค์การบ้านช่วงปัจจุบัน: **{len(assignments)}** รายการ",
            f"• บันทึกประกาศและเนื้อหาล่าสุด (รวม CE Internship): **{len(items)}** รายการ",
            f"• บันทึกลง Calendar / Tasks พร้อมสรุป 2 ภาษา: **{len(calendar_events)}** รายการ",
        ]
        if calendar_events:
            report.append("\n**📌 ตัวอย่างรายการที่บันทึกลง Calendar / Tasks:**")
            for ev in calendar_events[:5]:
                cat = "☑️ หมวดงาน (Task - ติ๊กแล้วจาง)" if ev.get("is_task") else "📅 กิจกรรม (Event)"
                report.append(f"- [{cat}] **{ev['course_name']}**: {ev['title']} (`{ev['due_date']}`)")
            if len(calendar_events) > 5:
                report.append(f"_...และอีก {len(calendar_events) - 5} รายการ_")

        await status_msg.edit(content="\n".join(report))
    except Exception as e:
        await status_msg.edit(content=f"❌ เกิดข้อผิดพลาดระหว่างการรีซิงค์: {str(e)}")

@bot.command(name="homework", aliases=["hw", "tasks"])
async def show_homework(ctx, *, course_filter: str = ""):
    """Summarize homework assignments, exams, and schedules"""
    filter_lower = course_filter.strip().lower()
    days_back = 60
    target_course = None
    
    if filter_lower and filter_lower not in ["all", "ทั้งหมด", "history", "ประวัติ"]:
        target_course = course_filter.strip()
        header_title = f"📋 **สรุปงานและกำหนดการวิชา '{course_filter.strip()}':**\n"
    else:
        header_title = "📋 **สรุปงาน กำหนดการ และการสอบทั้งหมดในภาคเรียน (รอบ 60 วัน):**\n"

    all_tasks = database.get_active_and_upcoming_assignments(target_course, days_back=days_back)
    if not all_tasks:
        await ctx.send("ไม่พบข้อมูลในระบบ ลองพิมพ์ !sync หรืออัปโหลดไฟล์เพิ่มเติม (หรือไม่มีงานที่ต้องส่งในช่วงนี้)")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    upcoming_tasks = [t for t in all_tasks if (t.get("due_date") and t.get("due_date") >= today_str) or not t.get("due_date")]
    past_tasks = [t for t in all_tasks if t.get("due_date") and t.get("due_date") < today_str]

    lines = [header_title]

    if upcoming_tasks:
        lines.append("⏳ **【เร็วๆ นี้ / กำลังจะถึง】**")
        for t in upcoming_tasks:
            due = f"{t.get('due_date', 'ไม่มีกำหนด')} {t.get('due_time', '')}".strip()
            task_type = t.get('task_type') or 'การบ้าน'
            lines.append(f"📌 **[{task_type}] {t.get('title')}**")
            lines.append(f"• **วิชา:** {t.get('course_name')}")
            lines.append(f"• **กำหนดส่ง / นัดหมาย:** `{due}`")
            if t.get('raw_deadline'):
                lines.append(f"• **ข้อความเดิมในประกาศ:** _{t.get('raw_deadline')}_")
            if t.get('summary_thai'):
                lines.append(f"• **สรุปงาน:** {t.get('summary_thai')}")
            elif t.get('description'):
                desc = t['description'][:150] + ("..." if len(t['description']) > 150 else "")
                lines.append(f"• **รายละเอียด:** {desc}")
            if t.get('alternate_link'):
                lines.append(f"🔗 [เปิดดูใน Classroom]({t['alternate_link']})")
            lines.append("──────────────────────")

    if past_tasks:
        lines.append("\n📜 **【การสอบ / กำหนดการที่ผ่านมาในภาคเรียน】**")
        for t in past_tasks:
            due = f"{t.get('due_date', 'ไม่มีกำหนด')} {t.get('due_time', '')}".strip()
            task_type = t.get('task_type') or 'การบ้าน'
            lines.append(f"• **[{task_type}]** {t.get('title')} ({t.get('course_name')}) — `{due}`")

    lines.append("\n💡 *พิมพ์ `!sync` หรือ `!resync` เพื่ออัปเดตข้อมูลล่าสุด หรือพิมพ์ `!homework <ชื่อวิชา>`*")

    # Send in chunks if message is long
    full_message = "\n".join(lines)
    if len(full_message) <= 2000:
        await ctx.send(full_message)
    else:
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 2 > 1900:
                await ctx.send(chunk)
                chunk = line + "\n"
            else:
                chunk += line + "\n"
        if chunk:
            await ctx.send(chunk)

@bot.command(name="ask")
async def ask_question(ctx, *, question: str):
    """Answer question with RAG"""
    async with ctx.typing():
        response = await asyncio.to_thread(rag.answer_question, question)
        await ctx.send(response)

async def send_split_message(channel, text: str):
    """Send message split into chunks if longer than Discord limit"""
    if len(text) <= 2000:
        await channel.send(text)
        return
    chunks = []
    lines = text.split("\n")
    curr = ""
    for line in lines:
        if len(curr) + len(line) + 2 > 1900:
            chunks.append(curr)
            curr = line + "\n"
        else:
            curr += line + "\n"
    if curr:
        chunks.append(curr)
    for c in chunks:
        await channel.send(c)

@bot.command(name="notebook", aliases=["thread", "note"])
async def create_notebook_thread(ctx, *, topic: str):
    """Create a dedicated Notebook thread for a course or study topic"""
    if isinstance(ctx.channel, discord.Thread):
        await ctx.send("⚠️ คุณอยู่ในห้องสมุดโน้ต (Thread) อยู่แล้วครับ!")
        return

    thread_name = f"📓 โน้ต: {topic}"[:95]
    try:
        thread = await ctx.message.create_thread(
            name=thread_name,
            auto_archive_duration=1440
        )
        embed = discord.Embed(
            title=f"📓 สมุดโน้ตวิชาการ: {topic}",
            description=(
                f"ยินดีต้อนรับสู่พื้นที่ทบทวนบทเรียนสำหรับ **{topic}** (สไตล์ NotebookLM)\n\n"
                "💡 **คำสั่งที่คุณสามารถใช้ในห้องนี้:**\n"
                f"• `!studyguide {topic}` - สร้างคู่มือสรุปเนื้อหาเตรียมสอบ\n"
                f"• `!quiz {topic}` - ทดสอบความรู้ด้วยแบบฝึกหัด (มีเฉลยซ่อน)\n"
                f"• `!image {topic}` - เจนภาพ Mind Map / Infographic ประกอบบทเรียน\n"
                f"• หรือ **พิมพ์คุยถามข้อสงสัยได้โดยตรงเลย** (บอทจะอิงจากเอกสารที่มีในระบบ)"
            ),
            color=discord.Color.teal()
        )
        await thread.send(embed=embed)
        await ctx.send(f"✅ เปิดสมุดโน้ตเรียบร้อยแล้ว: {thread.mention}")
    except Exception as e:
        await ctx.send(f"❌ ไม่สามารถสร้างห้องโน้ตได้: {str(e)}")

@bot.command(name="studyguide", aliases=["guide"])
async def studyguide_cmd(ctx, *, topic: str):
    """Generate NotebookLM-style study guide"""
    msg = await ctx.send(f"📖 กำลังค้นคว้าเอกสารและสร้าง Study Guide สำหรับ `{topic}`...")
    try:
        contexts = await asyncio.to_thread(rag.query_context, topic, 6)
        context_text = "\n\n".join([c["text"] for c in contexts]) if contexts else f"หัวข้อการเรียน: {topic}"
        guide = await asyncio.to_thread(study_features.generate_study_guide, topic, context_text)
        await msg.delete()
        await send_split_message(ctx.channel, guide)
    except Exception as e:
        await msg.edit(content=f"❌ เกิดข้อผิดพลาดในการสร้าง Study Guide: {str(e)}")

@bot.command(name="quiz", aliases=["test"])
async def quiz_cmd(ctx, *, topic: str):
    """Generate practice quiz with spoiler answers"""
    msg = await ctx.send(f"🎯 กำลังสร้างแบบฝึกหัดทบทวนสำหรับ `{topic}`...")
    try:
        contexts = await asyncio.to_thread(rag.query_context, topic, 5)
        context_text = "\n\n".join([c["text"] for c in contexts]) if contexts else topic
        quiz_text = await asyncio.to_thread(study_features.generate_quiz, topic, context_text)
        await msg.delete()
        await send_split_message(ctx.channel, quiz_text)
    except Exception as e:
        await msg.edit(content=f"❌ เกิดข้อผิดพลาดในการสร้างแบบฝึกหัด: {str(e)}")

@bot.command(name="image", aliases=["diagram", "mindmap", "img"])
async def generate_image_cmd(ctx, *, topic: str):
    """Generate educational diagram or mind map"""
    msg = await ctx.send(f"🎨 กำลังออกแบบและสร้างภาพประกอบ/Mind Map สำหรับ `{topic}` (อาจใช้เวลาประมาณ 10-15 วินาที)...")
    try:
        contexts = await asyncio.to_thread(rag.query_context, topic, 2)
        context_snippet = contexts[0]["text"] if contexts else topic
        img_bytes = await asyncio.to_thread(study_features.generate_study_image, topic, context_snippet)
        if img_bytes:
            file = discord.File(io.BytesIO(img_bytes), filename="study_diagram.png")
            embed = discord.Embed(
                title=f"🎨 ภาพประกอบการเรียนรู้: {topic}",
                description="ภาพจำลอง / Mind Map สำหรับช่วยทบทวนบทเรียน",
                color=discord.Color.purple()
            )
            embed.set_image(url="attachment://study_diagram.png")
            await msg.delete()
            await ctx.send(file=file, embed=embed)
        else:
            await msg.edit(content="⚠️ ไม่สามารถสร้างภาพได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง")
    except Exception as e:
        await msg.edit(content=f"❌ เกิดข้อผิดพลาดในการสร้างภาพ: {str(e)}")

@bot.command(name="summarize", aliases=["summary", "brief"])
async def summarize_cmd(ctx, *, topic: str):
    """Generate concise summary"""
    msg = await ctx.send(f"⚡ กำลังสรุปเนื้อหา `{topic}`...")
    try:
        prompt = f"สรุปเนื้อหาเรื่อง '{topic}' อย่างกระชับ ได้ใจความสำคัญ สำหรับอ่านทบทวนใน 1 นาที (Bullet points + Bold):"
        answer = await asyncio.to_thread(rag.answer_question, prompt)
        await msg.delete()
        await send_split_message(ctx.channel, f"📋 **สรุปประเด็นสำคัญ: {topic}**\n\n{answer}")
    except Exception as e:
        await msg.edit(content=f"❌ เกิดข้อผิดพลาด: {str(e)}")

def is_channel_allowed(channel) -> bool:
    """Check if the bot is allowed to respond (DMs, #การศึกษา, or Threads inside #การศึกษา)."""
    if isinstance(channel, discord.DMChannel):
        return True
    if isinstance(channel, discord.Thread):
        if channel.parent and hasattr(channel.parent, "name"):
            return ALLOWED_CHANNEL_NAME.lower() in channel.parent.name.lower()
        return True
    if hasattr(channel, "name") and channel.name:
        return ALLOWED_CHANNEL_NAME.lower() in channel.name.lower()
    return False

@bot.event
async def on_message(message: discord.Message):
    # Ignore bot's own messages
    if message.author.bot:
        return

    # Restrict bot strictly to DMs or the allowed channel (e.g. "การศึกษา")
    if not is_channel_allowed(message.channel):
        return

    # Check for attachments (PDF files)
    if message.attachments:
        for attachment in message.attachments:
            if attachment.filename.lower().endswith(".pdf"):
                feedback = await message.channel.send(f"📥 กำลังดาวน์โหลดและประมวลผลไฟล์ `{attachment.filename}`...")
                try:
                    save_path = Path(DOWNLOADS_DIR) / attachment.filename
                    await attachment.save(save_path)
                    
                    chunks_indexed = await asyncio.to_thread(rag.index_pdf_file, str(save_path))
                    if chunks_indexed > 0:
                        # Also extract schedules/assignments from PDF text
                        pdf_tasks_count = 0
                        try:
                            reader = PdfReader(str(save_path))
                            full_pdf_text = "\n".join([page.extract_text() or "" for page in reader.pages[:10]])
                            pdf_tasks = await asyncio.to_thread(
                                extract_tasks_from_text, 
                                full_pdf_text, 
                                attachment.filename, 
                                f"ไฟล์ PDF: {attachment.filename}"
                            )
                            for pt in pdf_tasks:
                                task_id = f"ext_pdf_{abs(hash(pt['title'] + str(pt.get('due_date'))))}"
                                database.save_assignment({
                                    "id": task_id,
                                    "course_id": "",
                                    "course_name": attachment.filename,
                                    "title": pt["title"],
                                    "description": pt.get("description", ""),
                                    "due_date": pt.get("due_date"),
                                    "due_time": pt.get("due_time", "23:59"),
                                    "task_type": pt.get("task_type", "กำหนดการ"),
                                    "raw_deadline": pt.get("raw_deadline", ""),
                                    "summary_thai": pt.get("summary_thai", ""),
                                    "summary_english": pt.get("summary_english", "")
                                })
                            pdf_tasks_count = len(pdf_tasks)
                        except Exception as ex:
                            print(f"[PDF Task Extraction Warning]: {ex}")

                        extra_info = f"\n🗓️ *AI ตรวจพบกำหนดการ/งานในเอกสารนี้อีก **{pdf_tasks_count}** รายการ (พิมพ์ `!calendar` เพื่อลงปฏิทินได้ทันที)*" if pdf_tasks_count > 0 else ""
                        await feedback.edit(
                            content=f"✅ นำเข้าไฟล์ `{attachment.filename}` เรียบร้อย ({chunks_indexed} ส่วน){extra_info}\nคุณสามารถถามคำถามจากเนื้อหาในเอกสารนี้ได้ทันทีครับ!"
                        )
                    else:
                        await feedback.edit(content=f"⚠️ ไม่สามารถอ่านข้อความจากไฟล์ `{attachment.filename}` ได้ หรือไฟล์ว่างเปล่า")
                except Exception as e:
                    await feedback.edit(content=f"❌ เกิดข้อผิดพลาดในการประมวลผลไฟล์: {str(e)}")

    # Process bot commands (e.g. !sync, !help, !homework)
    ctx = await bot.get_context(message)
    if ctx.valid:
        await bot.process_commands(message)
        return

    # If it's in the allowed channel (or DM) and not a command, treat text as a question to the assistant!
    if message.content.strip() and not message.content.startswith("!"):
        async with message.channel.typing():
            answer = await asyncio.to_thread(rag.answer_question, message.content.strip())
            await message.channel.send(answer)

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ Error: DISCORD_TOKEN is missing in .env")
        exit(1)
    bot.run(DISCORD_TOKEN)
