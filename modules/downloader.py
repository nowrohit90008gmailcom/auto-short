"""
Movie downloader using yt-dlp Python API.
Downloads video from YouTube or any supported URL.
Uses UUID filenames to avoid path issues with special characters.
"""
import os
import uuid
import json
import subprocess
from pathlib import Path
from utils.logger import get_logger

log = get_logger("downloader")

WORKSPACE = Path(__file__).resolve().parent.parent / "workspace"
MOVIES_DIR = WORKSPACE / "movies"


def download(url: str, movie_name: str) -> dict:
    """
    Download video from URL using yt-dlp Python API.
    
    Returns:
        {"video_path": str, "title": str, "duration": float, "thumbnail_url": str}
    """
    import yt_dlp
    import re
    
    clean_name = re.sub(r'[\\/*?:"<>|#]', "", movie_name).strip()
    movie_dir = MOVIES_DIR / clean_name.replace(" ", "_")
    movie_dir.mkdir(parents=True, exist_ok=True)
    
    # Cache Check: Reuse existing video file in this directory to avoid re-downloads!
    for f in movie_dir.glob("*"):
        if f.suffix in (".mp4", ".mkv", ".webm") and f.stat().st_size > 10_000_000:
            log.info(f"Cache Hit: Reusing existing movie file: {f}")
            duration = 0
            try:
                probe = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_format", str(f)],
                    capture_output=True, text=True, timeout=30, encoding="utf-8"
                )
                duration = float(json.loads(probe.stdout)["format"]["duration"])
            except Exception:
                pass
            return {
                "video_path": str(f),
                "title": movie_name,
                "duration": duration,
                "thumbnail_url": "",
            }
            
    file_id = uuid.uuid4().hex[:12]
    output_template = str(movie_dir / f"{file_id}.%(ext)s")
    
    # yt-dlp options
    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "noplaylist": True,
        "retries": 3,
        "socket_timeout": 30,
        "no_warnings": False,
        "ignoreerrors": False,
    }
    
    cookies_file = WORKSPACE / "cookies.txt"
    if cookies_file.exists():
        ydl_opts["cookiefile"] = str(cookies_file)
        
    from dotenv import load_dotenv
    load_dotenv()
    proxy_url = os.getenv("YOUTUBE_PROXY")
    if proxy_url:
        ydl_opts["proxy"] = proxy_url
        log.info(f"Using Residential Proxy for download...")
        
    log.info(f"Downloading: {movie_name} from {url}")
    
    # Download
    title = movie_name
    duration = 0
    thumbnail = ""
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                title = info.get("title", movie_name)
                duration = info.get("duration", 0) or 0
                thumbnail = info.get("thumbnail", "")
    except Exception as e:
        log.error(f"yt-dlp download failed: {e}")
        raise RuntimeError(f"Download failed for {url}: {e}")
    
    # Find the downloaded file
    output_path = None
    for f in movie_dir.glob(f"{file_id}.*"):
        if f.suffix in (".mp4", ".mkv", ".webm"):
            output_path = f
            break
    
    if not output_path or not output_path.exists() or output_path.stat().st_size < 1000:
        raise RuntimeError(f"Downloaded file is empty or missing for {url}")
    
    # Get actual duration via ffprobe if needed
    if duration == 0:
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", str(output_path)],
                capture_output=True, text=True, timeout=30, encoding="utf-8"
            )
            duration = float(json.loads(probe.stdout)["format"]["duration"])
        except Exception:
            pass
    
    size_mb = output_path.stat().st_size / 1024 / 1024
    log.info(f"Downloaded: {output_path} ({duration:.0f}s, {size_mb:.1f}MB)")
    
    return {
        "video_path": str(output_path),
        "title": title,
        "duration": duration,
        "thumbnail_url": thumbnail,
    }
