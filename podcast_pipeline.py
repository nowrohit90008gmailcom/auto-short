import os
import subprocess
import sys
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
GAMEPLAYS_DIR = ASSETS_DIR / "gameplays"
MUSIC_DIR = ASSETS_DIR / "music"

GAMEPLAY_PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLdxE72LlkFodEb4jBP8ewH1-qfUcneR7Z"

BEAT_CONFIGS = [
    {
        "name": "lofi_chill",
        "filter": (
            "aevalsrc='0.3*sin(2*PI*220*t)*exp(-3*mod(t,0.5))"
            "+0.2*sin(2*PI*330*t)*exp(-4*mod(t,0.75))"
            "+0.15*sin(2*PI*165*t)*exp(-2*mod(t,1.0))"
            "+0.1*sin(2*PI*440*t)*exp(-5*mod(t,0.25))'"
            ":s=44100:d=60,tremolo=f=2:d=0.3,lowpass=f=3000"
        ),
    },
    {
        "name": "dark_phonk",
        "filter": (
            "aevalsrc='0.4*sin(2*PI*55*t)*exp(-2*mod(t,0.5))"
            "+0.3*sin(2*PI*82.5*t)*exp(-3*mod(t,0.25))"
            "+0.1*random(0)*exp(-10*mod(t,0.125))'"
            ":s=44100:d=60,lowpass=f=800,volume=1.5"
        ),
    },
    {
        "name": "ambient_pad",
        "filter": (
            "aevalsrc='0.2*sin(2*PI*174*t+sin(0.1*t))"
            "+0.2*sin(2*PI*220*t+sin(0.15*t))"
            "+0.15*sin(2*PI*261*t+sin(0.08*t))"
            "+0.1*sin(2*PI*130*t)'"
            ":s=44100:d=60,lowpass=f=4000"
        ),
    },
    {
        "name": "trap_pulse",
        "filter": (
            "aevalsrc='0.35*sin(2*PI*65*t)*exp(-4*mod(t,0.25))"
            "+0.2*sin(2*PI*130*t)*exp(-6*mod(t,0.5))"
            "+0.05*random(0)*exp(-20*mod(t,0.125))'"
            ":s=44100:d=60,lowpass=f=2000"
        ),
    },
    {
        "name": "cinematic_drone",
        "filter": (
            "aevalsrc='0.25*sin(2*PI*82*t)"
            "+0.2*sin(2*PI*123*t+sin(0.05*t)*2)"
            "+0.15*sin(2*PI*164*t+sin(0.07*t))"
            "+0.1*sin(2*PI*41*t)'"
            ":s=44100:d=60,lowpass=f=2500"
        ),
    },
]

for d in [PODCASTS_DIR, OUTPUT_DIR, ASSETS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

def _generate_royalty_free_beats():
    """Generate royalty-free background beats using FFmpeg audio synthesis.
    100% original, zero copyright risk, zero network dependency."""
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    
    existing = list(MUSIC_DIR.glob("*.mp3"))
    if len(existing) >= len(BEAT_CONFIGS):
        return  # All beats already generated
    
    log.info(f"Generating {len(BEAT_CONFIGS)} royalty-free background beats...")
    
    for i, beat in enumerate(BEAT_CONFIGS):
        target = MUSIC_DIR / f"bgm_{i}_{beat['name']}.mp3"
        if target.exists() and target.stat().st_size > 10000:
            continue
        
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", beat["filter"],
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(target)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and target.exists():
                size_kb = target.stat().st_size / 1024
                log.info(f"Generated royalty-free beat: {beat['name']} ({size_kb:.0f} KB)")
            else:
                log.warning(f"Failed to generate beat {beat['name']}: {result.stderr[:200]}")
        except Exception as e:
            log.warning(f"Beat generation error for {beat['name']}: {e}")

def _setup_assets():
    """Downloads royalty-free gameplay videos and generates background beats."""
    GAMEPLAYS_DIR.mkdir(parents=True, exist_ok=True)
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    
    cookies_file = WORKSPACE / "cookies.txt"
    cookies_args = ["--cookies", str(cookies_file)] if cookies_file.exists() else []

    from dotenv import load_dotenv
    load_dotenv()
    proxy_url = os.getenv("YOUTUBE_PROXY")
    proxy_args = ["--proxy", proxy_url] if proxy_url else []

    # Download Gameplays
    existing_gameplays = list(GAMEPLAYS_DIR.glob("*.mp4"))
    if len(existing_gameplays) == 0:
        log.info("Downloading diverse gameplay videos for split-screen from playlist...")
        target_template = str(GAMEPLAYS_DIR / "gameplay_%(autonumber)s.mp4")
        cmd = [sys.executable, "-m", "yt_dlp"] + cookies_args + proxy_args + ["--force-ipv4", "-f", "bv*[height<=480]+ba/b/bestvideo+bestaudio/best", "--merge-output-format", "mp4", "--playlist-end", "50", "--match-filter", "duration <= 900 & !is_live", "--max-filesize", "500M", "-o", target_template, GAMEPLAY_PLAYLIST_URL]
        subprocess.run(cmd)
                
    # Generate royalty-free beats (replaces YouTube music downloads)
    _generate_royalty_free_beats()

def run_podcast_pipeline(url: str, title: str):
    log.info(f"Starting Transformative Podcast Pipeline for: {title}")
    
    _setup_assets()
    
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
        raw_highlights = extract_viral_highlights(words, total_clips=1)
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
        intro_audio_path = str(short_dir / "intro_audio.mp3")
        midro_audio_path = str(short_dir / "midro_audio.mp3")
        outro_audio_path = str(short_dir / "outro_audio.mp3")
        final_path = str(short_dir / f"final_short_{i}.mp4")
        
        # --- Deepgram AI Narrator (Holy Trinity) ---
        deepgram_key = os.getenv("DEEPGRAM_API_KEY", "")
        intro_text = highlight.get("intro", f"You won't believe what happened... {highlight['title']}!")
        midro_text = highlight.get("midro", "Hold on, it gets even crazier...")
        outro_text = highlight.get("outro", "Drop a follow for daily viral podcasts!")
        
        generated_trinity = False
        if deepgram_key:
            try:
                import requests
                headers = {
                    "Authorization": f"Token {deepgram_key}",
                    "Content-Type": "application/json"
                }
                
                # Generate Intro
                r1 = requests.post("https://api.deepgram.com/v1/speak?model=aura-angus-en", headers=headers, json={"text": intro_text}, timeout=30)
                if r1.status_code == 200:
                    with open(intro_audio_path, "wb") as f: f.write(r1.content)
                
                # Generate Midro
                r2 = requests.post("https://api.deepgram.com/v1/speak?model=aura-angus-en", headers=headers, json={"text": midro_text}, timeout=30)
                if r2.status_code == 200:
                    with open(midro_audio_path, "wb") as f: f.write(r2.content)
                    
                # Generate Outro
                r3 = requests.post("https://api.deepgram.com/v1/speak?model=aura-angus-en", headers=headers, json={"text": outro_text}, timeout=30)
                if r3.status_code == 200:
                    with open(outro_audio_path, "wb") as f: f.write(r3.content)
                    
                if r1.status_code == 200 and r2.status_code == 200 and r3.status_code == 200:
                    log.info(f"Generated Deepgram AI Holy Trinity (Angus)")
                    generated_trinity = True
                else:
                    log.warning("Deepgram TTS failed for one or more files.")
            except Exception as e:
                log.warning(f"Deepgram TTS error: {e}")
                
        if not generated_trinity:
            intro_audio_path = None
            midro_audio_path = None
            outro_audio_path = None
            
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
        
        # Randomize Assets
        import random
        gameplays = list(GAMEPLAYS_DIR.glob("*.mp4"))
        music_tracks = list(MUSIC_DIR.glob("*.mp3"))
        selected_gameplay = str(random.choice(gameplays)) if gameplays else None
        selected_music = str(random.choice(music_tracks)) if music_tracks else None
        
        success = assemble_transformative_short(
            podcast_clip=clip_path,
            gameplay_video=selected_gameplay,
            bgm_audio=selected_music,
            broll_video=b_vid,
            captions_ass=captions_path,
            output_path=final_path,
            title_hook=highlight["title"],
            intro_audio_path=intro_audio_path,
            midro_audio_path=midro_audio_path,
            outro_audio_path=outro_audio_path
        )
        
        if success:
            log.info(f"SHORT {i} COMPLETE: {final_path}")
            generated_shorts.append({
                "video_path": final_path,
                "title": highlight["title"],
                "description": highlight.get("description", f"Check out this crazy moment from {title}! #shorts #podcast #viral")
            })
            
    # Auto-delete massive raw podcast video to save disk space
    try:
        if os.path.exists(video_path):
            os.remove(video_path)
            log.info(f"Auto-deleted raw podcast cache to save space: {video_path}")
    except Exception as e:
        log.warning(f"Failed to auto-delete raw podcast video: {e}")
            
    return generated_shorts

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    
    run_podcast_pipeline(args.url, args.title)
