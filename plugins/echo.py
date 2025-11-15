# echo.py — FINAL MERGED VERSION
# Includes:
# - Universal impersonate
# - Old extractor_args restored ("generic:impersonate=")
# - Rename feature
# - 1080p / Best selection
# - Error UI
# - Clean Lisa-Korea style

import logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import os, json, time, random, asyncio, shutil
from pyrogram import filters, Client, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from plugins.config import Config
from plugins.script import Translation
from plugins.functions.ran_text import random_char
from plugins.database.add import AddUser
from plugins.functions.forcesub import handle_force_subscribe
from pyrogram.errors import UserNotParticipant
from plugins.functions.display_progress import TimeFormatter, humanbytes
from plugins.functions.impersonate import impersonate_final_url   # ⭐ universal impersonate

cookies_file = 'cookies.txt' if os.path.exists('cookies.txt') else None
os.makedirs(Config.DOWNLOAD_LOCATION, exist_ok=True)

# ----------------------------
# Filename Sanitizer (renamer)
# ----------------------------
def sanitize_filename(name):
    if not name:
        return "video"
    name = name.split("?")[0].split("#")[0]
    bad = ['/', '\\', '<', '>', ':', '"', '|', '?', '*', ';', '=', '&', '..']
    for b in bad:
        name = name.replace(b, "_")
    name = ''.join(c for c in name if ord(c) >= 32)
    if len(name) > 200:
        base, ext = os.path.splitext(name)
        name = base[:195] + ext
    if name == "":
        name = "video"
    return name

# ----------------------------
# Apply impersonate universally
# ----------------------------
def sanitize_url(url):
    if any(x in url.lower() for x in ["get_stream", "getstream", "porndos", "okcdn", "redirect"]):
        try:
            return impersonate_final_url(url)
        except:
            return url
    return url


@Client.on_message(filters.command(["start"]) & filters.private)
async def start(bot, update):
    await update.reply_text(
        "👋 Send any video URL.\nI support 1080p, rename, aria2c speed & bypass protected CDNs."
    )


@Client.on_message(filters.private & filters.regex("http"))
async def echo(bot, update):

    # 1) Verification
    if update.from_user.id != Config.OWNER_ID:
        from plugins.functions.verify import check_verification, get_token
        if not await check_verification(bot, update.from_user.id) and Config.TRUE_OR_FALSE:
            await update.reply_text(
                "Please verify first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify", url=await get_token(bot, update.from_user.id, f"https://t.me/{Config.BOT_USERNAME}?start="))]])
            )
            return

    await AddUser(bot, update)

    if Config.UPDATES_CHANNEL:
        try:
            if await handle_force_subscribe(bot, update) == 400:
                return
        except:
            return

    # 2) Parse URL + rename
    full_text = update.text.strip()
    url = full_text
    custom_name = None
    user = update.from_user.id

    if "|" in full_text:
        p = [x.strip() for x in full_text.split("|")]
        if len(p) >= 2:
            url = p[0]
            custom_name = sanitize_filename(p[1])

    url = sanitize_url(url)  # ⭐ universal impersonate applied here

    # 3) Show processing message
    wait_msg = await bot.send_message(
        update.chat.id,
        "⏳ Processing your link...",
        reply_to_message_id=update.id
    )

    # 4) Build yt-dlp probe command (JSON)  
    # ⭐ Old extractor_args behavior restored EXACT:
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--allow-dynamic-mpd",
        "--no-check-certificate",
        "--extractor-args", "generic:impersonate=",   # ⭐ old behavior
        "-j",
        url
    ]

    if cookies_file:
        cmd.extend(["--cookies", cookies_file])
    if Config.HTTP_PROXY:
        cmd.extend(["--proxy", Config.HTTP_PROXY])

    logger.info(" ".join(cmd))

    # 5) Execute yt-dlp probe
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        err = err.decode().strip()

        if err and "nonnumeric port" not in err:
            await wait_msg.delete()
            await update.reply_text(f"❌ Error:\n<code>{err}</code>", parse_mode="html")
            return
        data = out.decode().strip()
        if "\n" in data:
            data = data.split("\n")[0]

        info = json.loads(data)
    except Exception as e:
        await wait_msg.delete()
        await update.reply_text(f"❌ Extraction failed:\n{e}")
        return

    # 6) Save session JSON
    sess_id = random_char(5)
    sess_file = os.path.join(Config.DOWNLOAD_LOCATION, f"{user}{sess_id}.json")
    json.dump(info, open(sess_file, "w"), ensure_ascii=False)

    # 7) Build format buttons (1080p + Best)
    formats = info.get("formats", [])
    best_audio = None

    for f in formats:
        if f.get("vcodec") == "none" and f.get("acodec") != "none":
            best_audio = f.get("format_id")
            break

    f1080 = None
    best = None

    for f in formats:
        if f.get("vcodec") == "none":
            continue
        h = f.get("height") or 0
        fid = f.get("format_id")
        ext = f.get("ext", "mp4")
        size = f.get("filesize") or f.get("filesize_approx") or 0

        if f.get("acodec") == "none" and best_audio:
            fid = f"{fid}+{best_audio}"

        if h == 1080 and not f1080:
            f1080 = (fid, ext, size)

        if not best or h > best[2] if isinstance(best, tuple) else 0:
            best = (fid, ext, size, h)

    kb = []

    if f1080:
        fid, ext, size = f1080
        kb.append([InlineKeyboardButton(f"🔥 1080p • {ext.upper()} • {humanbytes(size)}",
                                        callback_data=f"video|{fid}|{ext}|{sess_id}")])

    if best:
        fid, ext, size, h = best
        kb.append([InlineKeyboardButton(f"📹 Best ({h}p) • {ext.upper()} • {humanbytes(size)}",
                                        callback_data=f"video|{fid}|{ext}|{sess_id}")])

    # audio
    kb.append([
        InlineKeyboardButton("🎵 mp3 64k", callback_data=f"audio|64k|mp3|{sess_id}"),
        InlineKeyboardButton("🎵 mp3 128k", callback_data=f"audio|128k|mp3|{sess_id}")
    ])
    kb.append([InlineKeyboardButton("🎵 mp3 320k", callback_data=f"audio|320k|mp3|{sess_id}")])

    # rename + close
    kb.append([
        InlineKeyboardButton("✏️ Rename", callback_data=f"rename|{sess_id}"),
        InlineKeyboardButton("🔒 Close", callback_data="close")
    ])

    await wait_msg.delete()

    title = info.get("title", "Video")
    dur = info.get("duration", 0)

    await bot.send_message(
        update.chat.id,
        f"📹 <b>{title}</b>\n⏱ {TimeFormatter(dur*1000) if dur else 'Unknown'}\n\nSelect quality:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=enums.ParseMode.HTML,
        reply_to_message_id=update.id
    )
