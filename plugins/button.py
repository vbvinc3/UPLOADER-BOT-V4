# button.py — RESTORED & ENHANCED
# Native impersonate PRIMARY + extractor_args FALLBACK
# Added: Stable 10-second download progress with beautiful bar

import logging, asyncio, json, os, shutil, time, re
from pyrogram import enums
from plugins.config import Config
from plugins.script import Translation
from plugins.thumbnail import *
from plugins.functions.display_progress import progress_for_pyrogram, humanbytes, TimeFormatter
from plugins.database.database import db
from plugins.functions.ran_text import random_char
from plugins.functions.impersonate import impersonate_final_url

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

# Regex patterns (robust)
PATTERN_FULL = re.compile(
    r'\[download\]\s+(?P<pct>\d+(?:\.\d+)?)%\s+of\s+~?(?P<size_val>\d+(?:\.\d+)?)(?P<size_unit>[KMG]iB)\s+at\s+'
    r'(?P<speed_val>\d+(?:\.\d+)?)(?P<speed_unit>[KMG]iB/s)'
)
PATTERN_FALLBACK = re.compile(
    r'\[download\]\s+(?P<pct>\d+(?:\.\d+)?)%.*?(?P<size_val>\d+(?:\.\d+)?)(?P<size_unit>[KMG]iB).*?'
    r'(?P<speed_val>\d+(?:\.\d+)?)(?P<speed_unit>[KMG]iB/s)'
)
UNIT_MULTIPLIER = {'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3}

async def show_download_progress(proc, message, filename, start_time):
    last_update = 0
    last_pct = -1
    while True:
        line = await proc.stderr.readline()
        if not line:
            break
        raw = line.decode(errors="ignore").strip()
        if '[download]' in raw:
            logger.debug(f"yt-dlp: {raw}")
        match = PATTERN_FULL.search(raw) or PATTERN_FALLBACK.search(raw)
        if not match:
            continue
        try:
            pct = float(match.group('pct'))
            size_val = float(match.group('size_val'))
            size_unit = match.group('size_unit')
            speed_val = float(match.group('speed_val'))
            speed_unit = match.group('speed_unit')
            total_bytes = int(size_val * UNIT_MULTIPLIER.get(size_unit, 1))
            downloaded_bytes = int((pct / 100) * total_bytes)
            speed_bytes = speed_val * UNIT_MULTIPLIER.get(speed_unit.replace('/s', ''), 1)
            if speed_bytes > 0:
                remaining = total_bytes - downloaded_bytes
                eta_ms = int((remaining / speed_bytes) * 1000)
            else:
                eta_ms = 0
            eta_str = TimeFormatter(milliseconds=eta_ms)
            now = time.time()
            should_update = (
                pct == 100.0 or
                now - last_update >= 10 or
                (last_pct >= 0 and pct - last_pct >= 5 and now - last_update >= 5)
            )
            if not should_update:
                continue
            last_update = now
            last_pct = pct
            filled = int(pct // 10)
            bar = "┏━━━━✦[" + ("▣" * filled) + ("▢" * (10 - filled)) + "]✦━━━━"
            progress_block = bar + Translation.PROGRESS.format(
                round(pct, 2),
                humanbytes(downloaded_bytes),
                humanbytes(total_bytes),
                humanbytes(speed_bytes),
                eta_str if eta_str else "0 s"
            )
            try:
                await message.edit_caption(
                    Translation.PROGRES.format(
                        f"📥 Downloading {filename}",
                        progress_block
                    ),
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception as edit_err:
                logger.warning(f"Caption edit failed: {edit_err}")
        except Exception as parse_err:
            logger.debug(f"Failed to parse progress line: {parse_err}")
            continue

async def youtube_dl_call_back(bot, update):
    data = update.data.decode() if isinstance(update.data, bytes) else update.data
    if data == "close":
        try: await update.message.delete()
        except: pass
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
    url = update.message.reply_to_message.text.strip()
    custom_name = None
    if "|" in url:
        parts = [x.strip() for x in url.split("|")]
        if len(parts) >= 2:
            url = parts[0]
            custom_name = sanitize_filename(parts[1])
    if any(x in url.lower() for x in ["get_stream", "getstream", "okcdn", "redirect"]):
        try:
            url = impersonate_final_url(url)
            logger.info("CDN redirect resolved")
        except Exception as e:
            logger.debug(f"CDN resolve failed: {e}")
    title = info.get("title") or "video"
    if not custom_name:
        custom_name = sanitize_filename(f"{title}_{fmt}.{ext}")
    tmp = os.path.join(Config.DOWNLOAD_LOCATION, f"{update.from_user.id}{random_char(5)}")
    os.makedirs(tmp, exist_ok=True)
    output = os.path.join(tmp, custom_name)
    cmd = ["yt-dlp", "--impersonate", "chrome", "--newline", "--progress", "--no-colors", "-c", "--max-filesize", str(Config.TG_MAX_FILE_SIZE), "-o", output, "--embed-subs", "--hls-prefer-ffmpeg", "-f", f"{fmt}+bestaudio/best"]
    if cookies_file: cmd += ["--cookies", cookies_file]
    if aria2c_available():
        cmd += ["--external-downloader", "aria2c", "--external-downloader-args", "-x 16 -s 16 -k 1M --max-connection-per-server=16 --min-split-size=1M", "--buffer-size", "16K", "--http-chunk-size", "10M", "--retries", "10", "--fragment-retries", "10"]
    else:
        cmd += ["-N", "8", "--retries", "5"]
    if Config.HTTP_PROXY: cmd += ["--proxy", Config.HTTP_PROXY]
    cmd.append(url)
    await update.message.edit_caption(Translation.DOWNLOAD_START.format(custom_name))
    logger.info(f"🔥 PRIMARY: {' '.join(cmd)}")
    start_time = time.time()
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    progress_task = asyncio.create_task(show_download_progress(proc, update.message, custom_name, start_time))
    await proc.wait(); rc = proc.returncode
    if not progress_task.done():
        progress_task.cancel();
        try: await progress_task
        except asyncio.CancelledError: pass
    if rc != 0:
        logger.warning(f"⚠️ Primary failed code={rc}, attempting fallback...")
        fallback = ["yt-dlp", "--extractor-args", "generic:impersonate=chrome", "--newline", "--progress", "--no-colors", "-c", "--max-filesize", str(Config.TG_MAX_FILE_SIZE), "-o", output, "--embed-subs", "--hls-prefer-ffmpeg", "-f", f"{fmt}+bestaudio/best"]
        if cookies_file: fallback += ["--cookies", cookies_file]
        if aria2c_available(): fallback += ["--external-downloader", "aria2c", "--external-downloader-args", "-x 16 -s 16 -k 1M --max-connection-per-server=16 --min-split-size=1M"]
        else: fallback += ["-N", "8", "--retries", "5"]
        if Config.HTTP_PROXY: fallback += ["--proxy", Config.HTTP_PROXY]
        fallback.append(url)
        logger.info(f"🔄 FALLBACK: {' '.join(fallback)}")
        start_time = time.time()
        proc = await asyncio.create_subprocess_exec(*fallback, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        progress_task = asyncio.create_task(show_download_progress(proc, update.message, f"{custom_name} (Fallback)", start_time))
        await proc.wait(); rc = proc.returncode
        if not progress_task.done():
            progress_task.cancel();
            try: await progress_task
            except asyncio.CancelledError: pass
    if rc != 0:
        await update.message.edit_caption("❌ Download failed.")
        shutil.rmtree(tmp, ignore_errors=True)
        return
    if not os.path.exists(output):
        base = os.path.splitext(output)[0]
        for e in [".mp4", ".mkv", ".webm", ".flv"]:
            if os.path.exists(base + e):
                output = base + e
                break
        else:
            await update.message.edit_caption("❌ File not found after download")
            shutil.rmtree(tmp, ignore_errors=True)
            return
    size = os.path.getsize(output)
    if size > Config.TG_MAX_FILE_SIZE:
        await update.message.edit_caption(Translation.RCHD_TG_API_LIMIT.format("?", humanbytes(size)))
        shutil.rmtree(tmp, ignore_errors=True)
        return
    await update.message.edit_caption(Translation.UPLOAD_START.format(custom_name))
    start_up = time.time()
    try:
        upload_as_video = await db.get_upload_as_doc(update.from_user.id)
        if upload_as_video:
            w, h, d = await Mdata01(output)
            thumb = await Gthumb02(bot, update, d, output)
            await update.message.reply_video(output, width=w, height=h, duration=d, supports_streaming=True, thumb=thumb, caption=title[:1024], progress=progress_for_pyrogram, progress_args=(Translation.UPLOAD_START, update.message, start_up))
        else:
            thumb = await Gthumb01(bot, update)
            await update.message.reply_document(output, thumb=thumb, caption=title[:1024], progress=progress_for_pyrogram, progress_args=(Translation.UPLOAD_START, update.message, start_up))
    except Exception as e:
        await update.message.edit_caption(f"❌ Upload failed: {e}")
        shutil.rmtree(tmp, ignore_errors=True)
        return
    shutil.rmtree(tmp, ignore_errors=True)
    try: os.remove(sess_file)
    except: pass
    await update.message.edit_caption("✅ Uploaded successfully.")