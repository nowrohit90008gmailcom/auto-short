import os
import random
import subprocess
from pathlib import Path
from utils.logger import get_logger

log = get_logger("transform_editor")

def assemble_transformative_short(podcast_clip: str, gameplay_video: str, broll_video: str, captions_ass: str, output_path: str, title_hook: str):
    """
    Assembles a highly transformative vertical short to bypass Reused Content filters.
    - Top half: Podcast
    - Bottom half: Gameplay (randomly sliced)
    - Overlay: B-roll on top half for seconds 2-5
    - Captions: Center animated
    """
    if not os.path.exists(podcast_clip):
        raise FileNotFoundError(f"Podcast clip not found: {podcast_clip}")
        
    # Get podcast duration
    try:
        import json
        probe = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", podcast_clip], capture_output=True, text=True)
        dur = float(json.loads(probe.stdout)["format"]["duration"])
    except Exception:
        dur = 60.0
        
    # Get gameplay duration to slice randomly
    gp_start = 0
    if gameplay_video and os.path.exists(gameplay_video):
        try:
            probe = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", gameplay_video], capture_output=True, text=True)
            gp_dur = float(json.loads(probe.stdout)["format"]["duration"])
            if gp_dur > dur + 10:
                gp_start = random.uniform(0, gp_dur - dur - 2)
        except Exception:
            pass

    # Build the complex FFmpeg command
    cmd = ["ffmpeg", "-y"]
    
    # Input 0: Podcast clip
    cmd.extend(["-i", podcast_clip])
    
    # Input 1: Gameplay (if exists, else generate a black background)
    if gameplay_video and os.path.exists(gameplay_video):
        cmd.extend(["-ss", str(gp_start), "-t", str(dur), "-i", gameplay_video])
        gp_idx = 1
    else:
        cmd.extend(["-f", "lavfi", "-i", f"color=c=black:s=1080x960:d={dur}"])
        gp_idx = 1
        
    # Input 2: B-roll (optional)
    has_broll = broll_video and os.path.exists(broll_video)
    if has_broll:
        cmd.extend(["-i", broll_video])
        broll_idx = 2
        
    # Filter Complex Building
    filters = []
    
    # Scale podcast to fit top half (1080x1344, which is 70% of 1920)
    filters.append(f"[0:v]scale=1080:1344:force_original_aspect_ratio=decrease,pad=1080:1344:(ow-iw)/2:(oh-ih)/2[top]")
    
    # Scale gameplay to fill bottom half (1080x576, which is 30% of 1920)
    filters.append(f"[{gp_idx}:v]scale=1080:576:force_original_aspect_ratio=increase,crop=1080:576[bottom]")
    
    # vstack top and bottom
    filters.append("[top][bottom]vstack=inputs=2[stacked]")
    
    current_out = "[stacked]"
    
    # Inject B-roll over the top half from 2s to 5s
    if has_broll:
        filters.append(f"[{broll_idx}:v]scale=1080:1344:force_original_aspect_ratio=increase,crop=1080:1344[broll_scaled]")
        # overlay from t=2 to t=5 on top of [stacked] at x=0, y=0
        filters.append(f"{current_out}[broll_scaled]overlay=x=0:y=0:enable='between(t,2,5)'[with_broll]")
        current_out = "[with_broll]"
    
    # Burn captions
    if captions_ass and os.path.exists(captions_ass):
        ass_rel = os.path.relpath(captions_ass, os.getcwd()).replace("\\", "/")
        filters.append(f"{current_out}ass='{ass_rel}'[final]")
    else:
        filters.append(f"{current_out}copy[final]")
        
    cmd.extend(["-filter_complex", ";".join(filters)])
    cmd.extend(["-map", "[final]"])
    cmd.extend(["-map", "0:a?"]) # Map audio from podcast
    
    # Output settings
    cmd.extend([
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        output_path
    ])
    
    log.info(f"Assembling transformative short: {title_hook} (Dur: {dur:.1f}s)")
    
    try:
        # 3. Execute FFmpeg
        # We increase the timeout to 7200 (2 hours) because rendering a 2-minute 1080p split-screen with burned captions takes a while on standard VPS hardware.
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=7200)
        log.info(f"Successfully generated transformative short -> {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        log.error(f"FFmpeg assembly failed: {e.stderr.decode('utf-8')[-500:]}")
        return False
