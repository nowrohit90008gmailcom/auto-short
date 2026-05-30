"""
Movie source picker — randomly selects movies from YouTube channels/playlists.
Maintains a history file to avoid picking the same movie twice.
"""
import os
import json
import random
import subprocess
from pathlib import Path
from datetime import datetime
from utils.logger import get_logger

log = get_logger("movie_picker")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = PROJECT_ROOT / "movie_history.json"

# Source channels and playlists to pick from
SOURCES = [
    # Channels (picks from recent uploads)
    "https://www.youtube.com/@ForeverMovies-w7d",
    "https://www.youtube.com/@surhollywoodjunction2387",
    "https://www.youtube.com/@SouthHindiDub",
    "https://www.youtube.com/@hindimoviefullmovie",
    # Playlists
    "https://www.youtube.com/playlist?list=PLAVxmzbGb1co29UO_swVL2DRT546cIPcR",
    "https://www.youtube.com/playlist?list=PL8yrJ8afYlsfqUE75dAW1ceUj8nfZKJQP",
    "https://www.youtube.com/playlist?list=PLUpMRgoYQCdumwAmbiVK-FlP5dLp-o7s5",
    "https://www.youtube.com/playlist?list=PLhUrBB7LIVwvODHlGimpDtOZTZZ73WY1I",
]


def _load_history() -> set:
    """Load set of previously used video IDs."""
    if not HISTORY_FILE.exists():
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return set(entry.get("video_id", "") for entry in data)


def _save_to_history(video_id: str, title: str, url: str, source: str):
    """Append a video to history so it's never picked again."""
    history = []
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    
    history.append({
        "video_id": video_id,
        "title": title,
        "url": url,
        "source": source,
        "picked_at": datetime.now().isoformat(),
    })
    
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _fetch_videos_from_source(source_url: str, max_items: int = 50) -> list:
    """
    Fetch video list from a channel or playlist using yt-dlp Python API.
    Returns: [{"id": str, "title": str, "url": str, "duration": float}, ...]
    """
    import yt_dlp
    
    log.info(f"Scanning source: {source_url}")
    
    # For channels, get the /videos page
    url = source_url
    if "/@" in url and "/playlist" not in url:
        url = url.rstrip("/") + "/videos"
    
    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "playlistend": max_items,
        "ignoreerrors": True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        if not info:
            log.warning(f"No info returned for {source_url}")
            return []
        
        entries = info.get("entries") or []
        videos = []
        
        for entry in entries:
            if not entry:
                continue
            vid_id = entry.get("id", "")
            title = entry.get("title", "Unknown")
            duration = entry.get("duration") or 0
            
            # Skip deleted, private, or unavailable videos
            if not vid_id or not title:
                continue
            title_lower = title.lower()
            if any(skip in title_lower for skip in [
                "[deleted", "[private", "deleted video",
                "private video", "unavailable"
            ]):
                continue
            
            # Skip shorts (< 1 hour / 3600s) and very long content (> 4 hours / 14400s)
            if duration and (duration < 3600 or duration > 14400):
                continue
            
            videos.append({
                "id": vid_id,
                "title": title,
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "duration": duration,
            })
        
        log.info(f"Found {len(videos)} eligible videos from {source_url}")
        return videos
    
    except Exception as e:
        log.warning(f"Error scanning {source_url}: {e}")
        return []


def pick_random_movie() -> dict:
    """
    Pick a random movie from the source channels/playlists.
    Ensures the movie hasn't been used before.
    
    Returns:
        {
            "url": str,
            "movie_name": str,
            "video_id": str,
            "duration": float,
            "source": str
        }
    
    Raises RuntimeError if no new movie found.
    """
    used_ids = _load_history()
    log.info(f"History has {len(used_ids)} previously used movies")
    
    # Shuffle sources to pick from random channels
    sources = SOURCES.copy()
    random.shuffle(sources)
    
    for source in sources:
        videos = _fetch_videos_from_source(source)
        
        # Filter out already used videos
        available = [v for v in videos if v["id"] not in used_ids]
        
        if not available:
            log.info(f"No new movies from {source}, trying next source...")
            continue
        
        # Pick random from available
        chosen = random.choice(available)
        
        # Clean up title for movie name (remove common suffixes/noise)
        movie_name = chosen["title"]
        for noise in [" Full Movie", " Hindi Dubbed", " (Hindi)", " Hindi",
                      " Full HD", " FULL HD", " HD", " | Hindi", " - Full Movie",
                      " Full Movie HD", " | Full Movie", " Restorasyonlu",
                      " (Full Movie)", " [Full Movie]", " NEW RELEASED",
                      " South Movie", " Dubbed Movie", " Action Movie",
                      " Latest Movie", " Blockbuster", " Superhit",
                      " | South Hindi Dubbed Movie", " | Türk Filmi"]:
            movie_name = movie_name.replace(noise, "").replace(noise.lower(), "")
        # Remove everything after | or - if it looks like metadata
        import re
        movie_name = re.split(r'\s*[\|]\s*', movie_name)[0]
        movie_name = movie_name.strip(" |-–()")
        
        # Save to history
        _save_to_history(chosen["id"], chosen["title"], chosen["url"], source)
        
        log.info(f"PICKED: {movie_name} ({chosen['duration']:.0f}s) from {source}")
        
        return {
            "url": chosen["url"],
            "movie_name": movie_name,
            "video_id": chosen["id"],
            "duration": chosen["duration"],
            "source": source,
        }
    
    raise RuntimeError(
        "No new movies found across all sources! "
        "All available movies have been used. "
        "Add more sources or clear movie_history.json."
    )


def add_to_queue(movie: dict):
    """Add a picked movie to queue.json."""
    queue_file = PROJECT_ROOT / "queue.json"
    queue = []
    if queue_file.exists():
        with open(queue_file, "r", encoding="utf-8") as f:
            queue = json.load(f)
    
    entry = {
        "url": movie["url"],
        "movie_name": movie["movie_name"],
        "video_id": movie.get("video_id", ""),
        "language": "hindi",
        "status": "pending",
        "added_at": datetime.now().isoformat(),
        "source": movie.get("source", ""),
        "results": {},
    }
    
    queue.append(entry)
    
    with open(queue_file, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
    
    log.info(f"Added to queue: {movie['movie_name']}")


if __name__ == "__main__":
    """CLI: python -m modules.movie_picker"""
    movie = pick_random_movie()
    print(f"\nPicked: {movie['movie_name']}")
    print(f"URL:    {movie['url']}")
    print(f"Source: {movie['source']}")
    
    add = input("\nAdd to queue? (y/n): ").strip().lower()
    if add == "y":
        add_to_queue(movie)
        print("Added to queue.json!")
