# button.py — optimized: aria2c + renamer + improved error UI + session cleanup
# ©️ LISA-KOREA | @LISA_FAN_LK | NT_BOT_CHANNEL

import logging, asyncio, json, os, shutil, time, re
from datetime import datetime
from urllib.parse import urlparse
from pyrogram import enums
from pyrogram.types import InputMediaPhoto
from plugins.config import Config
from plugins.script import Translation
from plugins.thumbnail import *
from plugins.functions.display_progress import progress_for_pyrogram, humanbytes
from plugins.database.database import db
from plugins.functions.ran_text import random_char
from PIL import Image

# impersonate — DO NOT MODIFY this function file (import only)
from plugins.functions.impersonate import impersonate_final_url

cookies_file = 'cookies.txt' if os.path.exists('cookies.txt') else None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Check aria2c
def aria2c_available():
    return shutil.which("aria2c") is not None

# sanitize filename (same as echo)
def sanitize_filename(filename: str) -> str:
    if not filename:
        return "download"
    filename = filename.split('?')[0].split('#')[0]
    dangerous_chars = ['/', '\\', '..', '<', '>', ':', '"', '|', '?', '*', ';', '&', '=']
    for ch in dangerous_chars:
        filename = filename.replace(ch, '_')
    filename = filename.strip().strip('.')
    filename = ''.join(c for c in filename if ord(c) >= 32)
    if len(filename) > 200:
        name, ext = os.path.splitext(filename)
        filename = name[:195] + ext
    if filename == '':
        filename = "download"
    return filename

async def youtube_dl_call_back(bot, update):
    # handle close button quickly
    if update.data == "close":
        try:
            await update.message.delete()
        except:
            pass
        return True

    cb_data = update.data.decode() if isinstance(update.data, bytes) else update.data
    try:
        tg_send_type, youtube_dl_format, youtube_dl_ext, ranom = cb_data.split("|")
    except Exception as e:
        logger.error(f"Invalid callback data: {cb_data} — {e}")
        await update.message.edit_caption(caption="❌ Invalid callback request.")
        return False

    # Load session JSON
    save_ytdl_json_path = os.path.join(Config.DOWNLOAD_LOCATION, f"{update.from_user.id}{ranom}.json")
    if not os.path.exists(save_ytdl_json_path):
        await update.message.edit_caption(caption="❌ Session expired or missing. Please send the URL again.")
        return False

    try:
        with open(save_ytdl_json_path, "r", encoding="utf8") as f:
            response_json = json.load(f)
    except Exception as e:
        logger.error(f"Failed reading session json: {e}")
        await update.message.edit_caption(caption="❌ Corrupt session data. Please resend URL.")
        return False

    # Extract URL from replied message
    youtube_dl_url = update.message.reply_to_message.text or ""
    # if user included custom name or auth in message
    if "|" in youtube_dl_url:
        p = [x.strip() for x in youtube_dl_url.split("|")]
        if len(p) >= 2:
            youtube_dl_url = p[0]
            custom_file_name = sanitize_filename(p[1]) if p[1] else None
        else:
            custom_file_name = None
    else:
        custom_file_name = None
        for ent in update.message.reply_to_message.entities or []:
            if ent.type == "text_link":
                youtube_dl_url = ent.url
            elif ent.type == "url":
                o, l = ent.offset, ent.length
                youtube_dl_url = youtube_dl_url[o:o + l]

    youtube_dl_url = youtube_dl_url.strip()

    # Apply universal impersonate BEFORE downloading
    try:
        if any(x in youtube_dl_url.lower() for x in ("get_stream", "getstream", "okcdn", "embed", "redirect")):
            youtube_dl_url = impersonate_final_url(youtube_dl_url)
            logger.info(f"Impersonated final link: {youtube_dl_url}")
    except Exception as e:
        logger.debug(f"Impersonate failed: {e}")

    # Build filename from JSON title if not custom
    title = response_json.get("title") or "video"
    if not custom_file_name:
        # build safe file name
        basename = sanitize_filename(title)
        custom_file_name = f"{basename}_{youtube_dl_format}.{youtube_dl_ext}"

    # Ensure temp dir
    random1 = random_char(5)
    tmp_dir = os.path.join(Config.DOWNLOAD_LOCATION, f"{update.from_user.id}{random1}")
    os.makedirs(tmp_dir, exist_ok=True)
    download_path = os.path.join(tmp_dir, custom_file_name)

    # Build yt-dlp command with aria2c if available
    command_to_exec = [
        "yt-dlp", "-c", "--max-filesize", str(Config.TG_MAX_FILE_SIZE),
        "--hls-prefer-ffmpeg", "--embed-subs", "-f", f"{youtube_dl_format}+bestaudio/best",
        "--newline", "-o", download_path
    ]

    if cookies_file and os.path.exists(cookies_file):
        command_to_exec.extend(["--cookies", cookies_file])

    # Use aria2c advanced args when available
    if aria2c_available():
        command_to_exec.extend([
            "--external-downloader", "aria2c",
            "--external-downloader-args", "-x 16 -s 16 -k 1M --max-connection-per-server=16 --min-split-size=1M"
        ])
        # extra performance options
        command_to_exec.extend(["--buffer-size", "16K", "--http-chunk-size", "10M", "--retries", "10", "--fragment-retries", "10"])
    else:
        # fallback to internal concurrency
        command_to_exec.extend(["-N", "8", "--retries", "5"])

    # audio specific
    if tg_send_type == "audio":
        command_to_exec = [
            "yt-dlp", "-c", "--max-filesize", str(Config.TG_MAX_FILE_SIZE),
            "--extract-audio", "--audio-format", youtube_dl_ext, "--audio-quality", youtube_dl_format,
            "-o", download_path
        ]
        if cookies_file and os.path.exists(cookies_file):
            command_to_exec.extend(["--cookies", cookies_file])
        if aria2c_available():
            # aria2c plugin for audio fragments too
            command_to_exec.extend(["--external-downloader", "aria2c", "--external-downloader-args", "-x 16 -s 16 -k 1M"])

    # proxy if set
    if Config.HTTP_PROXY:
        command_to_exec.extend(["--proxy", Config.HTTP_PROXY])

    # extras
    command_to_exec.append("--no-warnings")

    logger.info(f"Executing: {' '.join(command_to_exec)}")
    await update.message.edit_caption(caption=Translation.DOWNLOAD_START.format(custom_file_name))

    start = datetime.now()
    process = await asyncio.create_subprocess_exec(*command_to_exec, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    last_update_time = time.time()

    # read and update progress lines (simple)
    async def read_progress():
        nonlocal last_update_time
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            s = line.decode(errors='ignore').strip()
            logger.debug(f"yt-dlp: {s}")
            # show progress when available
            m = re.search(r'\[download\]\s+(\d+\.\d+)%.*?at\s+([\d\.]+\w+/s)?', s)
            if m and (time.time() - last_update_time) > 3:
                percent = float(m.group(1))
                speed = m.group(2) or "Unknown"
                txt = f"⬇️ Downloading {custom_file_name}\nProgress: {percent:.1f}%\nSpeed: {speed}"
                try:
                    await update.message.edit_caption(caption=txt)
                except Exception:
                    pass
                last_update_time = time.time()

    await read_progress()
    await process.wait()
    if process.returncode != 0:
        logger.error(f"Download failed rc={process.returncode}")
        try:
            out = await process.stdout.read()
            msg = out.decode(errors='ignore')[:1000]
        except:
            msg = f"yt-dlp failed with code {process.returncode}"
        await update.message.edit_caption(caption=f"❌ Download failed: {msg}")
        # cleanup
        try:
            shutil.rmtree(tmp_dir)
        except:
            pass
        return False

    # find output file (yt-dlp may choose ext)
    final_file = download_path
    if not os.path.exists(final_file):
        base = os.path.splitext(final_file)[0]
        found = False
        for ext in ['.mp4', '.mkv', '.webm', '.flv', '.m4v', '.avi']:
            candidate = base + ext
            if os.path.exists(candidate):
                final_file = candidate
                found = True
                break
        if not found:
            await update.message.edit_caption(caption=Translation.DOWNLOAD_FAILED)
            try:
                shutil.rmtree(tmp_dir)
            except:
                pass
            return False

    file_size = os.stat(final_file).st_size
    end_one = datetime.now()
    time_for_download = (end_one - start).seconds

    if file_size > Config.TG_MAX_FILE_SIZE:
        await update.message.edit_caption(caption=Translation.RCHD_TG_API_LIMIT.format(time_for_download, humanbytes(file_size)))
        try:
            shutil.rmtree(tmp_dir)
        except:
            pass
        return False

    # start upload
    await update.message.edit_caption(caption=Translation.UPLOAD_START.format(custom_file_name))
    start_upload = time.time()

    try:
        if tg_send_type == "audio":
            duration = await Mdata03(final_file)
            thumb = await Gthumb01(bot, update)
            await update.message.reply_audio(audio=final_file, caption=response_json.get("description", "")[:1024], duration=duration, thumb=thumb, progress=progress_for_pyrogram, progress_args=(Translation.UPLOAD_START, update.message, start_upload))
        else:
            if not await db.get_upload_as_doc(update.from_user.id):
                thumb = await Gthumb01(bot, update)
                await update.message.reply_document(document=final_file, thumb=thumb, caption=response_json.get("description", "")[:1024], progress=progress_for_pyrogram, progress_args=(Translation.UPLOAD_START, update.message, start_upload))
            else:
                w,h,dur = await Mdata01(final_file)
                thumb = await Gthumb02(bot, update, dur, final_file)
                await update.message.reply_video(video=final_file, caption=response_json.get("description", "")[:1024], duration=dur, width=w, height=h, supports_streaming=True, thumb=thumb, progress=progress_for_pyrogram, progress_args=(Translation.UPLOAD_START, update.message, start_upload))

        # cleanup
        try:
            shutil.rmtree(tmp_dir)
            os.remove(os.path.join(Config.DOWNLOAD_LOCATION, f"{update.from_user.id}{ranom}.json"))
        except Exception as e:
            logger.debug(f"Cleanup error: {e}")

        end_upload = datetime.now()
        time_for_upload = (end_upload - end_one).seconds
        speed_info = " (aria2c 🚀)" if aria2c_available() else ""
        await update.message.edit_caption(caption=Translation.AFTER_SUCCESSFUL_UPLOAD_MSG_WITH_TS.format(time_for_download, time_for_upload) + speed_info)
        return True

    except Exception as e:
        logger.exception("Upload failed")
        await update.message.edit_caption(caption=f"❌ Upload failed: {str(e)}")
        try:
            shutil.rmtree(tmp_dir)
        except:
            pass
        return False
