"""
Video editor — assembles the final 9:16 YouTube Short / Facebook Reel.
Combines: visual clips + narration audio + ASS captions + Top White Banner → final output.
"""
import os
import subprocess
import json
import platform
from pathlib import Path
from utils.logger import get_logger

log = get_logger("video_editor")

def get_font_file() -> str:
    system = platform.system()
    if system == "Windows":
        win_paths = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "/Windows/Fonts/arial.ttf"
        ]
        for p in win_paths:
            if os.path.exists(p):
                return p
    elif system == "Darwin":
        mac_paths = [
            "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Supplemental/Arial.ttf"
        ]
        for p in mac_paths:
            if os.path.exists(p):
                return p
    else:
        linux_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
        ]
        for p in linux_paths:
            if os.path.exists(p):
                return p
    return None


WORKSPACE = Path(__file__).resolve().parent.parent / "workspace"
OUTPUT_DIR = WORKSPACE / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def assemble_short(visual_path: str, audio_path: str, ass_path: str,
                    part_num: int, movie_name: str,
                    hook_text: str = "") -> str:
    """
    Assemble final 9:16 short with a sleek top overlay bar showing
    a hook line from the script, narration audio, and word-by-word captions.
    
    The visual track length is adjusted to match narration duration.
    Movie audio is completely muted — only narration plays.
    
    Returns: Path to final output MP4
    """
    out_dir = OUTPUT_DIR / movie_name.replace(" ", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(out_dir / f"part_{part_num}_final.mp4")
    
    # Get narration duration
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", audio_path],
         capture_output=True, text=True, timeout=15, encoding="utf-8"
    )
    narration_dur = float(json.loads(probe.stdout)["format"]["duration"])
    
    log.info(f"Assembling Part {part_num}: visual={visual_path}, "
             f"audio={audio_path} ({narration_dur:.1f}s), captions={ass_path}")
    
    # Escape the ASS path for FFmpeg filter (handle backslashes and colons)
    ass_escaped = str(Path(ass_path).resolve()).replace("\\", "/").replace(":", "\\:")
    
    # Check if ASS file has content
    ass_has_content = False
    try:
        with open(ass_path, "r") as f:
            content = f.read()
            ass_has_content = "Dialogue:" in content
    except Exception:
        pass
    
    # Top overlay — white outlined text centered at top (like viral Hindi shorts)
    if not hook_text:
        hook_text = movie_name.replace("_", " ").replace("Full Movie", "").strip()
    
    # Truncate for burn text
    if len(hook_text) > 50:
        hook_text = hook_text[:50].strip()
    
    # Remove characters that break FFmpeg drawtext
    import re as _re
    hook_clean = _re.sub(r'[^\w\s\u0900-\u097F!?.]', '', hook_text).strip()
    if not hook_clean:
        hook_clean = movie_name.replace("_", " ")
    
    # Escape for FFmpeg drawtext
    hook_esc = hook_clean.replace("'", "").replace(":", "\\:").replace(",", "\\,").replace('"', '').replace("%", "%%").replace("\\", "/")
    
    # Find a valid font to avoid Fontconfig crash
    font_path = get_font_file()
    font_option = ""
    if font_path:
        escaped_font = font_path.replace("\\", "/").replace(":", "\\:")
        font_option = f"fontfile='{escaped_font}':"
    
    # Use relative path for ASS file to bypass FFmpeg absolute path colon issues on Windows
    ass_rel = os.path.relpath(ass_path, os.getcwd()).replace("\\", "/")
    
    # Build filter chain — 9:16 pad (no crop) + big hook text overlay + pop-up captions
    vf_parts = [
        # 1. Scale to fit 1080x1920, pad with black bars (no cropping)
        "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2[base]",
        # 2. Hook text — giant white text with thick outline and shadow, moved down slightly
        f"[base]drawtext={font_option}text='{hook_esc}':"
        f"fontcolor=white:fontsize=80:borderw=5:bordercolor=black:"
        f"shadowcolor=black:shadowx=4:shadowy=4:x=(w-text_w)/2:y=180[combined]",
    ]
    
    if ass_has_content:
        # ASS filter works best with relative forward-slash paths
        vf_parts.append(f"[combined]ass='{ass_rel}'[out]")
        final_label = "[out]"
    else:
        final_label = "[combined]"
    
    filter_complex = ";".join(vf_parts)
    
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",  # Loop visual to match audio
        "-i", visual_path,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", f"{final_label}",
        "-map", "1:a",  # Use narration audio only
        "-t", str(narration_dur),  # Trim to narration length
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-r", "30",
        "-pix_fmt", "yuv420p",
        "-shortest",
        output_path,
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=600, encoding="utf-8")
    
    if result.returncode != 0:
        log.error(f"FFmpeg assembly failed: {result.stderr[:2000]}")
        raise RuntimeError(f"Video assembly failed for Part {part_num}")
    
    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    log.info(f"Part {part_num} assembled: {output_path} "
             f"({narration_dur:.1f}s, {size_mb:.1f}MB)")
    
    return output_path


def make_thumbnail(video_path: str, output_path: str, timestamp: float = 2.0) -> str:
    """Extract a 9:16 thumbnail from the video."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", video_path,
        "-vframes", "1",
        "-f", "image2",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=30)
    return output_path
