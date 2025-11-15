# button.py — FINAL MERGED VERSION
# - aria2c support
# - extractor_args "generic:impersonate="
# - universal impersonate
# - rename support
# - streaming upload
# - error UI
# - JSON session handling

import logging, asyncio, json, os, shutil, time, re
from datetime import datetime
from pyrogram import enums
from plugins.config import Config
from plugins.script import Translation
from plugins.thumbnail import *
from plugins.functions.display_progress import progress_for_pyrogram, humanbytes
from plugins.database.database import db
from plugins.functions.ran_text import random_char
from plugins.functions.impersonate import impersonate_final_url  # ⭐

logger = logging.getLogger(__name__)
cookies_file = 'cookies.txt' if os.path.exists('cookies.txt') else None

def sanitize_filename(name):
    if not name:
        return "video"
    bad = ['/', '\\', '<', '>', ':', '"', '|', '?', '*', ';', '=', '&', '..']
    for b in bad:
        name = name.replace(b, "_")
    name = ''.join(c for c in name if ord(c) >= 32)
    name = name.strip().strip(".")
    if len(name) > 200:
        base, ext = os.path.splitext(name)
        name = base[:195] + ext
    if not name:
        name = "video"
    return name

def aria2c_available():
    return shutil.which("aria2c") is not None


async def youtube_dl_call_back(bot, update):

    data = update.data.decode() if isinstance(update.data, bytes) else update.data

    if data == "close":
        try:
            await update.message.delete()
        except:
            pass
        return

    try:
        tg_type, fmt, ext, sid = data.split("|")
    except:
        await update.message.edit_caption("❌ Invalid request.")
        return

    sess_file = os.path.join(Config.DOWNLOAD_LOCATION, f"{update.from_user.id}{sid}.json")
    if not os.path.exists(sess_file):
        await update.message.edit_caption("❌ Session expired. Send link again.")
        return

    info = json.load(open(sess_file))

    # Parse original URL
    url = update.message.reply_to_message.text.strip()
    custom_name = None

    if "|" in url:
        p = [x.strip() for x in url.split("|")]
        if len(p) >= 2:
            url = p[0]
            custom_name = sanitize_filename(p[1])

    # Apply impersonate
    if any(x in url.lower() for x in ["get_stream", "getstream", "okcdn", "redirect"]):
        try:
            url = impersonate_final_url(url)
        except:
            pass

    title = info.get("title") or "video"

    if not custom_name:
        custom_name = sanitize_filename(f"{title}_{fmt}.{ext}")

    tmp = os.path.join(Config.DOWNLOAD_LOCATION, f"{update.from_user.id}{random_char(5)}")
    os.makedirs(tmp, exist_ok=True)
    output = os.path.join(tmp, custom_name)

    # Build yt-dlp download command
    cmd = [
        "yt-dlp",
        "--extractor-args", "generic:impersonate=",   # ⭐ restored old behavior
        "-c",
        "--max-filesize", str(Config.TG_MAX_FILE_SIZE),
        "-o", output
    ]

    if tg_type == "audio":
        cmd += ["--extract-audio", "--audio-format", ext, "--audio-quality", fmt]
    else:
        cmd += ["--embed-subs", "--hls-prefer-ffmpeg",
                "-f", f"{fmt}+bestaudio/best"]

    if cookies_file:
        cmd += ["--cookies", cookies_file]

    if aria2c_available():
        cmd += [
            "--external-downloader", "aria2c",
            "--external-downloader-args", "-x 16 -s 16 -k 1M --max-connection-per-server=16 --min-split-size=1M",
            "--buffer-size", "16K",
            "--http-chunk-size", "10M",
            "--retries", "10",
            "--fragment-retries", "10"
        ]
    else:
        cmd += ["-N", "8", "--retries", "5"]

    if Config.HTTP_PROXY:
        cmd += ["--proxy", Config.HTTP_PROXY]

    await update.message.edit_caption(Translation.DOWNLOAD_START.format(custom_name))
    logger.info(" ".join(cmd))

    # Run download
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE
    )

    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        text = line.decode().strip()

        m = re.search(r"(\d+\.\d+)%.*?at\s+([\d\.]+\w+/s)?", text)
        if m:
            percent = m.group(1)
            speed = m.group(2) or "Unknown"
            try:
                await update.message.edit_caption(
                    f"⬇️ {custom_name}\nProgress: {percent}%\nSpeed: {speed}"
                )
            except:
                pass

    await proc.wait()
    rc = proc.returncode

    if rc != 0:
        await update.message.edit_caption(f"❌ Download failed.\nCode: {rc}")
        shutil.rmtree(tmp, ignore_errors=True)
        return

    # find downloaded file
    if not os.path.exists(output):
        base = os.path.splitext(output)[0]
        found = False
        for e in [".mp4", ".mkv", ".webm", ".flv"]:
            if os.path.exists(base + e):
                output = base + e
                found = True
                break
        if not found:
            await update.message.edit_caption("❌ Downloaded file missing.")
            shutil.rmtree(tmp, ignore_errors=True)
            return

    size = os.path.getsize(output)
    if size > Config.TG_MAX_FILE_SIZE:
        await update.message.edit_caption(
            Translation.RCHD_TG_API_LIMIT.format("?", humanbytes(size))
        )
        shutil.rmtree(tmp, ignore_errors=True)
        return

    await update.message.edit_caption(Translation.UPLOAD_START.format(custom_name))
    start_up = time.time()

    # Upload with metadata
    try:
        if tg_type == "audio":
            dur = await Mdata03(output)
            thumb = await Gthumb01(bot, update)
            await update.message.reply_audio(
                output, duration=dur, thumb=thumb,
                caption=title[:1024],
                progress=progress_for_pyrogram,
                progress_args=(Translation.UPLOAD_START, update.message, start_up)
            )
        else:
            if not await db.get_upload_as_doc(update.from_user.id):
                thumb = await Gthumb01(bot, update)
                await update.message.reply_document(
                    output, thumb=thumb, caption=title[:1024],
                    progress=progress_for_pyrogram,
                    progress_args=(Translation.UPLOAD_START, update.message, start_up)
                )
            else:
                w, h, d = await Mdata01(output)
                thumb = await Gthumb02(bot, update, d, output)
                await update.message.reply_video(
                    output, width=w, height=h, duration=d,
                    supports_streaming=True, thumb=thumb,
                    caption=title[:1024],
                    progress=progress_for_pyrogram,
                    progress_args=(Translation.UPLOAD_START, update.message, start_up)
                )

    except Exception as e:
        await update.message.edit_caption(f"❌ Upload failed: {e}")
        shutil.rmtree(tmp, ignore_errors=True)
        return

    shutil.rmtree(tmp, ignore_errors=True)
    os.remove(sess_file)

    await update.message.edit_caption("✅ Uploaded successfully.")
