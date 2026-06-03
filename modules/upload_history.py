"""
Upload history — persistent JSON log of every upload attempt.
Stores video IDs, timestamps, verification results for audit and retry.
"""
import json
import datetime
from pathlib import Path
from utils.logger import get_logger

log = get_logger("upload_history")


def record_upload(bot_dir: Path, entry: dict):
    """
    Append an upload record to the bot's upload_history.json.
    
    entry should contain:
        - timestamp: ISO string
        - title: video title
        - yt_video_id: YouTube video ID or None
        - fb_video_id: Facebook video ID or None
        - yt_verified: bool
        - fb_verified: bool
        - yt_status: str
        - fb_status: str
        - video_path: original file path
    """
    history_file = bot_dir / "upload_history.json"
    
    history = []
    if history_file.exists():
        try:
            with open(history_file, "r") as f:
                history = json.load(f)
        except (json.JSONDecodeError, Exception):
            history = []
    
    # Add timestamp if not present
    if "timestamp" not in entry:
        entry["timestamp"] = datetime.datetime.now().isoformat()
    
    history.append(entry)
    
    # Keep only last 500 entries to prevent file from growing forever
    if len(history) > 500:
        history = history[-500:]
    
    try:
        with open(history_file, "w") as f:
            json.dump(history, f, indent=2, default=str)
        log.info(f"Upload record saved: {entry.get('title', 'unknown')}")
    except Exception as e:
        log.error(f"Failed to save upload history: {e}")


def get_failed_uploads(bot_dir: Path) -> list:
    """
    Returns a list of upload entries where either YouTube or Facebook verification failed.
    Useful for manual retry or debugging.
    """
    history_file = bot_dir / "upload_history.json"
    
    if not history_file.exists():
        return []
    
    try:
        with open(history_file, "r") as f:
            history = json.load(f)
    except (json.JSONDecodeError, Exception):
        return []
    
    failed = []
    for entry in history:
        yt_ok = entry.get("yt_verified", False)
        fb_ok = entry.get("fb_verified", False)
        if not yt_ok or not fb_ok:
            failed.append(entry)
    
    return failed


def get_upload_stats(bot_dir: Path) -> dict:
    """
    Returns upload statistics for a bot profile.
    """
    history_file = bot_dir / "upload_history.json"
    
    if not history_file.exists():
        return {"total": 0, "yt_success": 0, "fb_success": 0, "both_success": 0, "both_failed": 0}
    
    try:
        with open(history_file, "r") as f:
            history = json.load(f)
    except (json.JSONDecodeError, Exception):
        return {"total": 0, "yt_success": 0, "fb_success": 0, "both_success": 0, "both_failed": 0}
    
    stats = {"total": len(history), "yt_success": 0, "fb_success": 0, "both_success": 0, "both_failed": 0}
    for entry in history:
        yt = entry.get("yt_verified", False)
        fb = entry.get("fb_verified", False)
        if yt:
            stats["yt_success"] += 1
        if fb:
            stats["fb_success"] += 1
        if yt and fb:
            stats["both_success"] += 1
        if not yt and not fb:
            stats["both_failed"] += 1
    
    return stats
