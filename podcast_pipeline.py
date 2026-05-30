import os
import subprocess
from pathlib import Path
from utils.logger import get_logger

from modules.downloader import download
from modules.transcriber import transcribe_full_movie
from modules.podcast_extractor import extract_viral_highlights
from modules.pexels_api import download_broll
from modules.captioner import generate_ass
from modules.transform_editor import assemble_transformative_short

log = get_logger("podcast_pipeline")

WORKSPACE = Path("workspace")
PODCASTS_DIR = WORKSPACE / "podcasts"
OUTPUT_DIR = WORKSPACE / "podcast_shorts"
ASSETS_DIR = WORKSPACE / "assets"
GAMEPLAY_FILE = ASSETS_DIR / "gameplay.mp4"

for d in [PODCASTS_DIR, OUTPUT_DIR, ASSETS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

def _ensure_gameplay_video():
    """Downloads a royalty-free gameplay video if we don't have one."""
    if not GAMEPLAY_FILE.exists():
        log.info("Downloading base gameplay video for split-screen...")
        # A generic 10-minute non-copyrighted parkour/gameplay video
        url = "https://www.youtube.com/watch?v=n_Dv4JMiwK8" 
        cmd = ["python", "-m", "yt_dlp", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4", "-o", str(GAMEPLAY_FILE), url]
        subprocess.run(cmd, check=True)

def run_podcast_pipeline(url: str, title: str):
    log.info(f"Starting Transformative Podcast Pipeline for: {title}")
    
    _ensure_gameplay_video()
    
    # 1. Download
    download_res = download(url, title)
    video_path = download_res["video_path"]
    
    # 2. Transcribe
    log.info("Transcribing podcast to find viral moments...")
    transcript_data = transcribe_full_movie(video_path, title)
    words = transcript_data.get("words", [])
    
    # 3. Extract Highlights
    log.info("Sending to LLM to extract viral highlights...")
    
    highlights = []
    max_retries = 3
    for attempt in range(max_retries):
        raw_highlights = extract_viral_highlights(words, total_clips=3)
        if raw_highlights:
            for h in raw_highlights:
                dur = h["end"] - h["start"]
                if 60 <= dur <= 170:
                    highlights.append(h)
        
        # Deduplicate by title
        seen = set()
        unique_highlights = []
        for h in highlights:
            if h["title"] not in seen:
                seen.add(h["title"])
                unique_highlights.append(h)
        highlights = unique_highlights
                
        if len(highlights) >= 3:
            highlights = highlights[:3]
            break
            
        log.warning(f"Attempt {attempt + 1}: Not enough clips > 60s (found {len(highlights)}). Retrying...")
    
    if not highlights:
        log.error("Failed to extract any highlights > 60 seconds after 3 retries.")
        return
    generated_shorts = []
    
    import re
    clean_title = re.sub(r'[\\/*?:"<>|#]', "", title).strip()
    
    for i, highlight in enumerate(highlights, 1):
        log.info(f"--- Processing Short {i}: {highlight['title']} ---")
        
        short_dir = OUTPUT_DIR / f"{clean_title.replace(' ', '_')}_short_{i}"
        short_dir.mkdir(parents=True, exist_ok=True)
        
        clip_path = str(short_dir / "podcast_clip.mp4")
        broll_path = str(short_dir / "broll.mp4")
        captions_path = str(short_dir / "captions.ass")
        final_path = str(short_dir / f"final_short_{i}.mp4")
        
        start_t = highlight["start"]
        end_t = highlight["end"]
        dur = end_t - start_t
        
        # 4. Extract 60s slice from podcast
        cmd = ["ffmpeg", "-y", "-ss", str(start_t), "-i", video_path, "-t", str(dur), "-c", "copy", clip_path]
        subprocess.run(cmd, capture_output=True)
        
        # 5. Get B-Roll from Pexels
        keyword = highlight["keywords"][0] if highlight["keywords"] else "podcast"
        has_broll = download_broll(keyword, broll_path)
        
        # 6. Generate Captions
        segment_words = [w for w in words if start_t <= w["start"] <= end_t]
        for w in segment_words:
            w["start"] -= start_t
            w["end"] -= start_t
        generate_ass(segment_words, captions_path)
        
        # 7. Assemble Transformative Video
        b_vid = broll_path if has_broll else None
        success = assemble_transformative_short(
            podcast_clip=clip_path,
            gameplay_video=str(GAMEPLAY_FILE),
            broll_video=b_vid,
            captions_ass=captions_path,
            output_path=final_path,
            title_hook=highlight["title"]
        )
        
        if success:
            log.info(f"SHORT {i} COMPLETE: {final_path}")
            generated_shorts.append({
                "video_path": final_path,
                "title": highlight["title"],
                "description": f"Check out this crazy moment from {title}! #shorts #podcast #viral"
            })
            
    return generated_shorts

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    
    run_podcast_pipeline(args.url, args.title)
