# echo.py — optimized: renamer + error UI + universal impersonate usage
# ©️ LISA-KOREA | @LISA_FAN_LK | NT_BOT_CHANNEL | TG-SORRY

import logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import os, json, time, random, asyncio, shutil
import requests, urllib.parse, filetype, tldextract
from pyrogram import filters, Client, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from plugins.config import Config
from plugins.script import Translation
from plugins.functions.ran_text import random_char
from plugins.database.add import AddUser
from plugins.functions.forcesub import handle_force_subscribe
from pyrogram.errors import UserNotParticipant
from plugins.functions.display_progress import TimeFormatter, humanbytes

# IMPORTANT: impersonate function must exist and stay unchanged as you requested.
from plugins.functions.impersonate import impersonate_final_url

# Optional cookies file
cookies_file = 'cookies.txt' if os.path.exists('cookies.txt') else None

# ----- Utility: sanitize filename (restore renamer) -----
def sanitize_filename(filename: str) -> str:
    if not filename:
        return "download"
    # remove URL params, fragments
    filename = filename.split('?')[0].split('#')[0]
    # replace dangerous chars
    dangerous_chars = ['/', '\\', '..', '<', '>', ':', '"', '|', '?', '*', ';', '&', '=']
    for ch in dangerous_chars:
        filename = filename.replace(ch, '_')
    # trim whitespace and dots
    filename = filename.strip().strip('.')
    # remove weird control chars
    filename = ''.join(c for c in filename if ord(c) >= 32)
    # safe max length
    if len(filename) > 200:
        name, ext = os.path.splitext(filename)
        filename = name[:195] + ext
    if filename == '':
        filename = "download"
    return filename

# ----- Utility: basic sanitize URL wrapper (uses impersonate) -----
def sanitize_url_for_extractor(url: str) -> str:
    try:
        if not url:
            return url
        lower = url.lower()
        if any(x in lower for x in ("get_stream", "getstream", "okcdn", "embed", "redirect")):
            # use your critical impersonate function — unchanged
            return impersonate_final_url(url)
    except Exception as e:
        logger.debug(f"sanitize_url_for_extractor fail: {e}")
    return url

# Ensure download dir
os.makedirs(Config.DOWNLOAD_LOCATION, exist_ok=True)

@Client.on_message(filters.command(["start"]) & filters.private)
async def start(bot, update):
    await update.reply_text(
        "👋 Send any video URL. I will extract formats and give download buttons.\n"
        "Features: 1080p priority, rename support, aria2c (if installed), error UI."
    )

@Client.on_message(filters.private & filters.regex(pattern=".*http.*"))
async def echo(bot, update):
    # verification & force-subscribe
    if update.from_user.id != Config.OWNER_ID:
        if not await __import__("plugins.functions.verify", fromlist=["check_verification"]).check_verification(bot, update.from_user.id) and Config.TRUE_OR_FALSE:
            btn = [[InlineKeyboardButton("✓⃝ Vᴇʀɪꜰʏ ✓⃝", url=await __import__("plugins.functions.verify", fromlist=["get_token"]).get_token(bot, update.from_user.id, f"https://telegram.me/{Config.BOT_USERNAME}?start="))]]
            await update.reply_text("Pʟᴇᴀsᴇ Vᴇʀɪꜰʏ Fɪʀsᴛ Tᴏ Usᴇ Mᴇ", reply_markup=InlineKeyboardMarkup(btn))
            return

    await AddUser(bot, update)
    if Config.UPDATES_CHANNEL:
        try:
            fsub = await handle_force_subscribe(bot, update)
            if fsub == 400:
                return
        except UserNotParticipant as e:
            logger.error(f"Force sub error: {e}")
            return

    # Parse incoming URL + optional rename / auth
    url = (update.text or "").strip()
    youtube_dl_username = None
    youtube_dl_password = None
    custom_name = None

    # if user provides rename or login in the message using '|' token
    if "|" in url:
        parts = [p.strip() for p in url.split("|")]
        if len(parts) == 2:
            url, custom_name = parts
        elif len(parts) == 4:
            url, custom_name, youtube_dl_username, youtube_dl_password = parts
        else:
            # fallback: extract entity URL
            for ent in update.entities:
                if ent.type == "text_link":
                    url = ent.url
                elif ent.type == "url":
                    o, l = ent.offset, ent.length
                    url = url[o:o + l]

    else:
        # extract URL from entities
        for ent in update.entities:
            if ent.type == "text_link":
                url = ent.url
            elif ent.type == "url":
                o, l = ent.offset, ent.length
                url = url[o:o + l]

    if url is None:
        await update.reply_text("No URL found in message.")
        return

    url = url.strip()
    if custom_name:
        custom_name = sanitize_filename(custom_name)

    # Apply global sanitize / impersonate BEFORE yt-dlp probing
    url = sanitize_url_for_extractor(url)
    logger.info(f"Using sanitized URL: {url}")

    # send processing UI
    chk = await bot.send_message(chat_id=update.chat.id, text=Translation.DOWNLOAD_START, disable_web_page_preview=True, reply_to_message_id=update.id)

    # Build yt-dlp command to probe (json)
    cmd = [
        "yt-dlp", "--no-warnings", "--allow-dynamic-mpd",
        "--no-check-certificate", "-j", url
    ]
    if cookies_file and os.path.exists(cookies_file):
        cmd.extend(["--cookies", cookies_file])
    if Config.HTTP_PROXY:
        cmd.extend(["--proxy", Config.HTTP_PROXY])
    if youtube_dl_username:
        cmd.extend(["--username", youtube_dl_username, "--password", youtube_dl_password])

    logger.info(f"Probe command: {' '.join(cmd)}")
    try:
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        stderr_text = stderr.decode().strip()
        logger.debug(stderr_text)
        if stderr_text and "nonnumeric port" not in stderr_text:
            # show useful error to user instead of long traceback
            msg = stderr_text
            if "This video is only available for registered users." in msg:
                msg += "\n" + Translation.SET_CUSTOM_USERNAME_PASSWORD
            await chk.delete()
            await bot.send_message(chat_id=update.chat.id, text=Translation.NO_VOID_FORMAT_FOUND.format(msg), reply_to_message_id=update.id, disable_web_page_preview=True)
            return

        out = stdout.decode().strip()
        if not out:
            await chk.delete()
            await bot.send_message(chat_id=update.chat.id, text=Translation.NO_VOID_FORMAT_FOUND.format("Empty response from extractor."), reply_to_message_id=update.id)
            return

        # Get first JSON line
        if "\n" in out:
            out = out.split("\n")[0]
        response_json = json.loads(out)

    except Exception as e:
        logger.exception("Probe failed")
        try:
            await chk.delete()
        except:
            pass
        await bot.send_message(chat_id=update.chat.id, text=f"❌ Extraction failed: {str(e)}", reply_to_message_id=update.id)
        return

    # Create session json
    randem = random_char(5)
    session_name = f"{update.from_user.id}{randem}.json"
    save_path = os.path.join(Config.DOWNLOAD_LOCATION, session_name)
    with open(save_path, "w", encoding="utf8") as f:
        json.dump(response_json, f, ensure_ascii=False)
    logger.info(f"Saved session: {save_path}")

    # Build simplified format buttons: 1080p priority, Best fallback, audio options
    formats = response_json.get("formats", [])
    best_audio_id = None
    for fmt in formats:
        if fmt.get("vcodec") == "none" and fmt.get("acodec") != "none":
            if fmt.get("abr", 0) > 0:
                best_audio_id = fmt.get("format_id")
                break

    format_1080 = None
    best_format = None
    for fmt in formats:
        vcodec = fmt.get("vcodec", "none")
        if vcodec == "none":
            continue
        height = fmt.get("height") or 0
        fid = fmt.get("format_id")
        ext = fmt.get("ext", "mp4")
        size = fmt.get("filesize") or fmt.get("filesize_approx") or 0

        # merge with best audio if needed
        if fmt.get("acodec") == "none" and best_audio_id:
            fid = f"{fid}+{best_audio_id}"

        if height == 1080 and not format_1080:
            format_1080 = {"id": fid, "ext": ext, "size": size, "h": height}
        if not best_format or height > best_format.get("h", 0):
            best_format = {"id": fid, "ext": ext, "size": size, "h": height}

    inline_keyboard = []
    if format_1080:
        cb = f"video|{format_1080['id']}|{format_1080['ext']}|{randem}"
        inline_keyboard.append([InlineKeyboardButton(f"🔥 1080p • {format_1080['ext'].upper()} • {humanbytes(format_1080['size'])}", callback_data=cb)])
    if best_format and (not format_1080 or best_format['h'] != 1080):
        cb = f"video|{best_format['id']}|{best_format['ext']}|{randem}"
        inline_keyboard.append([InlineKeyboardButton(f"📹 Best ({best_format['h']}p) • {best_format['ext'].upper()} • {humanbytes(best_format['size'])}", callback_data=cb)])

    # audio quick selects
    inline_keyboard.append([InlineKeyboardButton("🎵 mp3 (64k)", callback_data=f"audio|64k|mp3|{randem}"),
                            InlineKeyboardButton("🎵 mp3 (128k)", callback_data=f"audio|128k|mp3|{randem}")])
    inline_keyboard.append([InlineKeyboardButton("🎵 mp3 (320k)", callback_data=f"audio|320k|mp3|{randem}")])

    inline_keyboard.append([InlineKeyboardButton("🔁 Rename", callback_data=f"rename|{randem}"),
                            InlineKeyboardButton("🔒 Close", callback_data="close")])

    await chk.delete()
    title = response_json.get("title", "Video")
    duration = response_json.get("duration", 0)
    await bot.send_message(chat_id=update.chat.id,
                           text=f"📹 **{title}**\n\n⏱ Duration: {TimeFormatter(duration * 1000) if duration else 'Unknown'}\n\nSelect quality:",
                           reply_markup=InlineKeyboardMarkup(inline_keyboard),
                           parse_mode=enums.ParseMode.MARKDOWN,
                           disable_web_page_preview=True,
                           reply_to_message_id=update.id)
