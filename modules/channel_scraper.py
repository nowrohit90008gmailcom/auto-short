import os
import json
import random
import subprocess
import sys
from pathlib import Path
from utils.logger import get_logger

log = get_logger("channel_scraper")

def _load_history(history_file: Path) -> set:
    if not history_file.exists():
        return set()
    try:
        with open(history_file, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def _save_history(history: set, history_file: Path):
    history_file.parent.mkdir(parents=True, exist_ok=True)
    with open(history_file, "w") as f:
        json.dump(list(history), f)

def mark_as_processed(video_id: str, history_file: Path):
    history = _load_history(history_file)
    history.add(video_id)
    _save_history(history, history_file)
    log.info(f"Marked video {video_id} as processed in {history_file.name}")

def get_random_unprocessed_video(channel_url: str, history_file: Path) -> dict:
    """
    Fetches all videos from a channel/playlist, filters out processed ones,
    and returns a random video dict {"id": "...", "title": "...", "url": "..."}.
    """
    log.info(f"Scraping channel for videos: {channel_url}")
    
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist",
        "--dump-json",
        channel_url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        log.error(f"Failed to scrape channel: {e.stderr}")
        return None

    videos = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            data = json.loads(line)
            # Ignore videos shorter than 5 minutes (300 seconds) to avoid picking Shorts
            if data.get("duration", 0) > 300:
                videos.append({
                    "id": data.get("id"),
                    "title": data.get("title", "Unknown Title"),
                    "url": f"https://www.youtube.com/watch?v={data.get('id')}"
                })
        except Exception:
            continue

    if not videos:
        log.warning("No videos found in channel.")
        return None

    history = _load_history(history_file)
    unprocessed = [v for v in videos if v["id"] not in history]
    
    if not unprocessed:
        log.warning("All videos in this channel have already been processed!")
        return None
        
    selected = random.choice(unprocessed)
    log.info(f"Randomly selected unprocessed video: {selected['title']} ({selected['id']})")
    return selected
