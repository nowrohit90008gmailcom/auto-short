import os
import requests
from pathlib import Path
from utils.logger import get_logger

log = get_logger("pexels_api")

def download_broll(keyword: str, output_path: str) -> bool:
    """
    Searches Pexels for a portrait video matching the keyword and downloads it.
    Returns True if successful, False otherwise.
    """
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        log.warning("PEXELS_API_KEY not set. Skipping B-roll download.")
        return False
        
    url = f"https://api.pexels.com/videos/search?query={keyword}&orientation=portrait&per_page=3"
    headers = {"Authorization": api_key}
    
    try:
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        data = res.json()
        
        videos = data.get("videos", [])
        if not videos:
            log.warning(f"No Pexels videos found for keyword: {keyword}")
            return False
            
        # Get the first video, find a suitable HD video file
        video = videos[0]
        video_files = video.get("video_files", [])
        
        # Sort by resolution/quality (prefer HD)
        hd_files = [f for f in video_files if f.get("quality") == "hd"]
        if hd_files:
            download_url = hd_files[0]["link"]
        elif video_files:
            download_url = video_files[0]["link"]
        else:
            return False
            
        log.info(f"Downloading B-roll for '{keyword}' from {download_url}...")
        
        video_data = requests.get(download_url, timeout=30)
        video_data.raise_for_status()
        
        with open(output_path, "wb") as f:
            f.write(video_data.content)
            
        log.info(f"B-roll downloaded to {output_path}")
        return True
        
    except Exception as e:
        log.error(f"Pexels download failed: {e}")
        return False
