import secrets
from datetime import datetime, timezone
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database.users_chats_db import mydb
from info import ADMINS, URL

def _is_admin(user_id):
    return int(user_id or 0) in ADMINS

@Client.on_message(filters.command("stream") & filters.private)
async def stream_command(client, message):
    if not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin access required.")
    if not message.reply_to_message:
        return await message.reply_text("🎬 <b>Stream Generator</b>\n\nReply to a video/document and use <code>/stream</code>.", parse_mode="html")
    target = message.reply_to_message
    media = target.video or target.document
    if not media:
        return await message.reply_text("❌ Reply to a video or document.")
    token = secrets.token_urlsafe(18).replace("-", "").replace("_", "")
    title = getattr(media, "file_name", None) or getattr(target, "caption", None) or "Video"
    size = int(getattr(media, "file_size", 0) or 0)
    mime = getattr(media, "mime_type", None) or "video/mp4"
    await mydb.stream_links.update_one({"token": token}, {"$set": {
        "token": token, "chat_id": int(target.chat.id), "message_id": int(target.id),
        "file_id": media.file_id, "title": str(title)[:255], "size": size, "mime": mime,
        "created_at": datetime.now(timezone.utc), "created_by": int(message.from_user.id),
        "active": True, "views": 0
    }}, upsert=True)
    base = (URL or "").rstrip("/") or "http://localhost:8080"
    watch_url = f"{base}/watch/{token}"
    buttons = [[InlineKeyboardButton("🎬 Open Stream", url=watch_url)],
               [InlineKeyboardButton("📋 Get URL", callback_data=f"streamcopy:{token}")],
               [InlineKeyboardButton("🗑 Disable Link", callback_data=f"streamdisable:{token}")]]
    await message.reply_text(
        f"✅ <b>Stream link generated</b>\n\n🎬 <b>{str(title)[:120]}</b>\n📦 {size} bytes\n\n🔗 <code>{watch_url}</code>\n\n🔐 Admin-only generator.",
        reply_markup=InlineKeyboardMarkup(buttons), parse_mode="html")

@Client.on_callback_query(filters.regex(r"^streamcopy:"))
async def stream_copy_callback(client, query):
    if not _is_admin(query.from_user.id):
        return await query.answer("Admin only.", show_alert=True)
    token = query.data.split(":", 1)[1]
    doc = await mydb.stream_links.find_one({"token": token, "active": True})
    if not doc:
        return await query.answer("Stream link not found.", show_alert=True)
    base = (URL or "").rstrip("/") or "http://localhost:8080"
    await query.message.reply_text(f"🔗 <code>{base}/watch/{token}</code>", parse_mode="html")
    await query.answer("URL sent.")

@Client.on_callback_query(filters.regex(r"^streamdisable:"))
async def stream_disable_callback(client, query):
    if not _is_admin(query.from_user.id):
        return await query.answer("Admin only.", show_alert=True)
    token = query.data.split(":", 1)[1]
    result = await mydb.stream_links.update_one({"token": token}, {"$set": {"active": False}})
    if not result.matched_count:
        return await query.answer("Stream link not found.", show_alert=True)
    await query.answer("Stream disabled.")
    await query.message.edit_text("🗑 <b>Stream link disabled.</b>", parse_mode="html")


@Client.on_message(filters.command("streampanel") & filters.private)
async def stream_panel(client, message):
    if not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin access required.")
    total = await mydb.stream_links.count_documents({})
    active = await mydb.stream_links.count_documents({"active": True})
    pipeline = [{"$group": {"_id": None, "views": {"$sum": "$views"}}}]
    agg = await mydb.stream_links.aggregate(pipeline).to_list(length=1)
    views = int(agg[0].get("views", 0)) if agg else 0
    recent = await mydb.stream_links.find({"active": True}).sort("created_at", -1).limit(5).to_list(length=5)
    lines = ["🎬 <b>STREAM CONTROL CENTER</b>", "", f"🔗 Total links: <b>{total}</b>", f"🟢 Active: <b>{active}</b>", f"👁 Views: <b>{views}</b>", ""]
    if recent:
        lines.append("<b>Recent streams</b>")
        for item in recent:
            lines.append(f"• {str(item.get('title') or 'Video')[:45]} — {int(item.get('views', 0))} views")
    else:
        lines.append("No stream links yet.")
    buttons = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="streampanel:refresh"),
         InlineKeyboardButton("📋 Active Links", callback_data="streampanel:list")],
        [InlineKeyboardButton("ℹ️ How to Generate", callback_data="streampanel:help")]
    ]
    await message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode="html")


@Client.on_callback_query(filters.regex(r"^streampanel:"))
async def stream_panel_callback(client, query):
    if not _is_admin(query.from_user.id):
        return await query.answer("Admin only.", show_alert=True)
    action = query.data.split(":", 1)[1]
    if action == "help":
        return await query.answer("Reply to a storage video/document and use /stream.", show_alert=True)
    if action == "list":
        items = await mydb.stream_links.find({"active": True}).sort("created_at", -1).limit(10).to_list(length=10)
        if not items:
            return await query.answer("No active stream links.", show_alert=True)
        rows = []
        base = (URL or "").rstrip("/") or "http://localhost:8080"
        for item in items:
            token = item.get("token")
            title = str(item.get("title") or "Video")[:35]
            rows.append([InlineKeyboardButton(f"🎬 {title}", url=f"{base}/watch/{token}")])
        rows.append([InlineKeyboardButton("⬅️ Dashboard", callback_data="streampanel:refresh")])
        await query.message.edit_reply_markup(InlineKeyboardMarkup(rows))
        return await query.answer("Active links")
    total = await mydb.stream_links.count_documents({})
    active = await mydb.stream_links.count_documents({"active": True})
    agg = await mydb.stream_links.aggregate([{"$group": {"_id": None, "views": {"$sum": "$views"}}]).to_list(length=1)
    views = int(agg[0].get("views", 0)) if agg else 0
    await query.message.edit_text(
        f"🎬 <b>STREAM CONTROL CENTER</b>\n\n🔗 Total links: <b>{total}</b>\n🟢 Active: <b>{active}</b>\n👁 Views: <b>{views}</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="streampanel:refresh"),
             InlineKeyboardButton("📋 Active Links", callback_data="streampanel:list")],
            [InlineKeyboardButton("ℹ️ How to Generate", callback_data="streampanel:help")]
        ]),
        parse_mode="html"
    )
    await query.answer("Refreshed")
