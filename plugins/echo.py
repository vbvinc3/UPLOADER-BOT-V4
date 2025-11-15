# echo.py — FIXED VERSION - VIDEO ONLY
# Native impersonate PRIMARY + extractor_args FALLBACK
# Video quality selection only (1080p, 720p, 480p, Best)

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
from plugins.functions.impersonate import impersonate_final_url

cookies_file = 'cookies.txt' if os.path.exists('cookies.txt') else None
os.makedirs(Config.DOWNLOAD_LOCATION, exist_ok=True)

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

def sanitize_url(url):
    """Resolve CDN redirects using curl-impersonate"""
    if any(x in url.lower() for x in ["get_stream", "getstream", "porndos", "okcdn", "redirect"]):
        try:
            resolved = impersonate_final_url(url)
            logger.info(f"CDN redirect resolved: {url} -> {resolved}")
            return resolved
        except:
            return url
    return url


@Client.on_message(filters.command(["start"]) & filters.private)
async def start(bot, update):
    await update.reply_text(
        "👋 Send any video URL.\n"
        "✅ Native impersonate support\n"
        "✅ Multiple quality options\n"
        "✅ Rename feature\n"
        "✅ Fast aria2c downloads"
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

    url = sanitize_url(url)

    # 3) Show processing message
    wait_msg = await bot.send_message(
        update.chat.id,
        "⏳ Processing your link...",
        reply_to_message_id=update.id
    )

    # 4) Try NATIVE impersonate first
    cmd_native = [
        "yt-dlp",
        "--no-warnings",
        "--allow-dynamic-mpd",
        "--no-check-certificate",
        "--impersonate", "chrome",
        "-j",
        url
    ]

    if cookies_file:
        cmd_native.extend(["--cookies", cookies_file])
    if Config.HTTP_PROXY:
        cmd_native.extend(["--proxy", Config.HTTP_PROXY])

    logger.info(f"🔥 PRIMARY: {' '.join(cmd_native)}")

    info = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_native,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()

        if proc.returncode == 0 and out:
            data = out.decode().strip()
            if "\n" in data:
                data = data.split("\n")[0]
            info = json.loads(data)
            logger.info("✅ Native impersonate SUCCESS")

    except Exception as e:
        logger.warning(f"⚠️ Native failed: {e}")

    # 5) FALLBACK to extractor_args
    if not info:
        logger.info("🔄 Trying FALLBACK extractor_args...")
        
        cmd_fallback = [
            "yt-dlp",
            "--no-warnings",
            "--allow-dynamic-mpd",
            "--no-check-certificate",
            "--extractor-args", "generic:impersonate=chrome",
            "-j",
            url
        ]

        if cookies_file:
            cmd_fallback.extend(["--cookies", cookies_file])
        if Config.HTTP_PROXY:
            cmd_fallback.extend(["--proxy", Config.HTTP_PROXY])

        logger.info(f"🔄 FALLBACK: {' '.join(cmd_fallback)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_fallback,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            out, err = await proc.communicate()
            err_text = err.decode().strip()

            if err_text and "nonnumeric port" not in err_text:
                await wait_msg.delete()
                await update.reply_text(f"❌ Error:\n<code>{err_text}</code>", parse_mode=enums.ParseMode.HTML)
                return

            data = out.decode().strip()
            if "\n" in data:
                data = data.split("\n")[0]

            info = json.loads(data)
            logger.info("✅ Fallback SUCCESS")

        except Exception as e:
            await wait_msg.delete()
            await update.reply_text(f"❌ Extraction failed:\n{e}")
            return

    # 6) Save session
    sess_id = random_char(5)
    sess_file = os.path.join(Config.DOWNLOAD_LOCATION, f"{user}{sess_id}.json")
    json.dump(info, open(sess_file, "w"), ensure_ascii=False)

    # 7) Build VIDEO format buttons only
    formats = info.get("formats", [])
    best_audio = None

    # Find best audio for merging
    for f in formats:
        if f.get("vcodec") == "none" and f.get("acodec") != "none":
            best_audio = f.get("format_id")
            break

    # Collect video formats
    video_formats = {}
    
    for f in formats:
        if f.get("vcodec") == "none":
            continue
            
        h = f.get("height") or 0
        fid = f.get("format_id")
        ext = f.get("ext", "mp4")
        size = f.get("filesize") or f.get("filesize_approx") or 0

        # Merge with audio if video-only
        if f.get("acodec") == "none" and best_audio:
            fid = f"{fid}+{best_audio}"

        # Store only best format for each resolution
        if h not in video_formats or size > video_formats[h][2]:
            video_formats[h] = (fid, ext, size, h)

    # Build buttons for common resolutions
    kb = []
    
    # 1080p
    if 1080 in video_formats:
        fid, ext, size, h = video_formats[1080]
        kb.append([InlineKeyboardButton(
            f"🔥 1080p • {ext.upper()} • {humanbytes(size)}",
            callback_data=f"video|{fid}|{ext}|{sess_id}"
        )])
    
    # 720p
    if 720 in video_formats:
        fid, ext, size, h = video_formats[720]
        kb.append([InlineKeyboardButton(
            f"📹 720p • {ext.upper()} • {humanbytes(size)}",
            callback_data=f"video|{fid}|{ext}|{sess_id}"
        )])
    
    # 480p
    if 480 in video_formats:
        fid, ext, size, h = video_formats[480]
        kb.append([InlineKeyboardButton(
            f"📺 480p • {ext.upper()} • {humanbytes(size)}",
            callback_data=f"video|{fid}|{ext}|{sess_id}"
        )])
    
    # 360p
    if 360 in video_formats:
        fid, ext, size, h = video_formats[360]
        kb.append([InlineKeyboardButton(
            f"📱 360p • {ext.upper()} • {humanbytes(size)}",
            callback_data=f"video|{fid}|{ext}|{sess_id}"
        )])
    
    # Best available (highest resolution)
    if video_formats:
        best_h = max(video_formats.keys())
        fid, ext, size, h = video_formats[best_h]
        kb.append([InlineKeyboardButton(
            f"⭐ Best ({h}p) • {ext.upper()} • {humanbytes(size)}",
            callback_data=f"video|{fid}|{ext}|{sess_id}"
        )])

    # Rename + Close
    kb.append([
        InlineKeyboardButton("✏️ Rename", callback_data=f"rename|{sess_id}"),
        InlineKeyboardButton("🔒 Close", callback_data="close")
    ])

    await wait_msg.delete()

    title = info.get("title", "Video")
    dur = info.get("duration", 0)

    await bot.send_message(
        update.chat.id,
        f"📹 **{title}**\n⏱ {TimeFormatter(dur*1000) if dur else 'Unknown'}\n\nSelect video quality:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_to_message_id=update.id
    )
