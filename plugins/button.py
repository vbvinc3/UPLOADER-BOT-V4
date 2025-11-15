# button.py — ENHANCED VERSION with Beautiful Download Progress
# Native impersonate PRIMARY + extractor_args FALLBACK
# Beautiful download progress bar matching upload progress

import logging, asyncio, json, os, shutil, time, re, math
from datetime import datetime
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


async def show_download_progress(proc, message, filename, start_time):
    """Monitor yt-dlp stderr and show beautiful progress matching upload style"""
    last_update = time.time()
    
    while True:
        line = await proc.stderr.readline()
        if not line:
            break
        
        try:
            text = line.decode().strip()
            
            # Parse yt-dlp download progress
            # Format: [download]  45.6% of 125.50MiB at 2.50MiB/s ETA 00:25
            download_match = re.search(
                r'\[download\]\s+(\d+\.?\d*)%\s+of\s+~?(\[\d\.]+)([KMG]iB)\s+at\s+(\[\d\.]+)([KMG]iB/s)',
                text
            )
            
            if download_match and time.time() - last_update > 2:
                percentage = float(download_match.group(1))
                size_val = float(download_match.group(2))
                size_unit = download_match.group(3)
                speed_val = float(download_match.group(4))
                speed_unit = download_match.group(5)
                
                # Convert to bytes
                multiplier = {'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3}
                total_size = int(size_val * multiplier.get(size_unit, 1))
                downloaded = int((percentage / 100) * total_size)
                speed = speed_val * multiplier.get(speed_unit.replace('/s', ''), 1)
                
                # Calculate ETA
                elapsed = time.time() - start_time
                if speed > 0:
                    time_to_completion = ((total_size - downloaded) / speed) * 1000
                else:
                    time_to_completion = 0
                
                eta = TimeFormatter(milliseconds=int(time_to_completion))
                
                # Build beautiful progress bar
                progress_bar = "┏━━━━✦[{0}{1}]✦━━━━".format(
                    ''.join(["▣" for i in range(int(percentage // 10))]),
                    ''.join(["▢" for i in range(10 - int(percentage // 10))])
                )
                
                progress_text = progress_bar + Translation.PROGRESS.format(
                    round(percentage, 2),
                    humanbytes(downloaded),
                    humanbytes(total_size),
                    humanbytes(speed),
                    eta if eta else "0 s"
                )
                
                await message.edit_caption(
                    Translation.PROGRES.format(
                        f"📥 Downloading {filename}",
                        progress_text
                    ),
                    parse_mode=enums.ParseMode.HTML
                )
                last_update = time.time()
                
        except Exception as e:
            logger.debug(f"Progress parse error: {e}")
            pass


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

    # Resolve CDN redirects
    if any(x in url.lower() for x in ["get_stream", "getstream", "okcdn", "redirect"]):
        try:
            url = impersonate_final_url(url)
            logger.info(f"CDN redirect resolved")
        except:
            pass

    title = info.get("title") or "video"

    if not custom_name:
        custom_name = sanitize_filename(f"{title}_{fmt}.{ext}")

    tmp = os.path.join(Config.DOWNLOAD_LOCATION, f"{update.from_user.id}{random_char(5)}")
    os.makedirs(tmp, exist_ok=True)
    output = os.path.join(tmp, custom_name)

    # 🔥 PRIMARY: Native impersonate
    cmd = [
        "yt-dlp",
        "--impersonate", "chrome",
        "--newline",
        "--progress",
        "--no-colors",
        "-c",
        "--max-filesize", str(Config.TG_MAX_FILE_SIZE),
        "-o", output,
        "--embed-subs",
        "--hls-prefer-ffmpeg",
        "-f", f"{fmt}+bestaudio/best"
    ]

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

    cmd.append(url)

    await update.message.edit_caption(Translation.DOWNLOAD_START.format(custom_name))
    logger.info(f"🔥 PRIMARY: {' '.join(cmd)}")

    # Run download
    start_time = time.time()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    # Start progress monitoring task
    progress_task = asyncio.create_task(
        show_download_progress(proc, update.message, custom_name, start_time)
    )

    await proc.wait()
    rc = proc.returncode
    
    # Cancel progress task
    progress_task.cancel()

    # 🔄 FALLBACK if native failed
    if rc != 0:
        logger.warning(f"⚠️ Native failed (code {rc}), trying FALLBACK...")
        
        cmd_fallback = [
            "yt-dlp",
            "--extractor-args", "generic:impersonate=chrome",
            "--newline",
            "--progress",
            "--no-colors",
            "-c",
            "--max-filesize", str(Config.TG_MAX_FILE_SIZE),
            "-o", output,
            "--embed-subs",
            "--hls-prefer-ffmpeg",
            "-f", f"{fmt}+bestaudio/best"
        ]

        if cookies_file:
            cmd_fallback += ["--cookies", cookies_file]

        if aria2c_available():
            cmd_fallback += [
                "--external-downloader", "aria2c",
                "--external-downloader-args", "-x 16 -s 16 -k 1M --max-connection-per-server=16 --min-split-size=1M"
            ]
        else:
            cmd_fallback += ["-N", "8", "--retries", "5"]

        if Config.HTTP_PROXY:
            cmd_fallback += ["--proxy", Config.HTTP_PROXY]

        cmd_fallback.append(url)

        logger.info(f"🔄 FALLBACK: {' '.join(cmd_fallback)}")

        start_time = time.time()
        proc = await asyncio.create_subprocess_exec(
            *cmd_fallback,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Start progress monitoring task for fallback
        progress_task = asyncio.create_task(
            show_download_progress(proc, update.message, f"{custom_name} (Fallback)", start_time)
        )

        await proc.wait()
        rc = proc.returncode
        
        # Cancel progress task
        progress_task.cancel()

    if rc != 0:
        await update.message.edit_caption(f"❌ Download failed (code {rc})")
        shutil.rmtree(tmp, ignore_errors=True)
        return

    # Find downloaded file
    if not os.path.exists(output):
        base = os.path.splitext(output)[0]
        found = False
        for e in [".mp4", ".mkv", ".webm", ".flv"]:
            if os.path.exists(base + e):
                output = base + e
                found = True
                break
        if not found:
            await update.message.edit_caption("❌ File not found after download")
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

    # 🔧 FIXED: Corrected upload logic
    try:
        # Check user preference (True = upload as video, False = upload as document)
        upload_as_video = await db.get_upload_as_doc(update.from_user.id)
        
        if upload_as_video:
            # Upload as VIDEO with streaming
            w, h, d = await Mdata01(output)
            thumb = await Gthumb02(bot, update, d, output)
            await update.message.reply_video(
                output,
                width=w,
                height=h,
                duration=d,
                supports_streaming=True,
                thumb=thumb,
                caption=title[:1024],
                progress=progress_for_pyrogram,
                progress_args=(Translation.UPLOAD_START, update.message, start_up)
            )
        else:
            # Upload as DOCUMENT
            thumb = await Gthumb01(bot, update)
            await update.message.reply_document(
                output,
                thumb=thumb,
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
