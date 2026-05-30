"""
Clip extractor — uses FFmpeg scene detection to find natural scene cuts,
then extracts the best matching scene for each narration line.

Instead of blindly cutting at script timestamps (which often lands mid-action),
we detect real scene boundaries and snap clips to them for professional results.
"""
import subprocess
import re
import os
from pathlib import Path
from utils.logger import get_logger

log = get_logger("clip_extractor")

WORKSPACE = Path(__file__).resolve().parent.parent / "workspace"
CLIPS_DIR = WORKSPACE / "clips"


def _detect_scenes(video_path: str, start_time: float, end_time: float,
                   threshold: float = 0.3) -> list:
    """
    Detect scene change timestamps in a portion of the video using FFmpeg.
    
    Returns a sorted list of scene-change timestamps (in seconds, absolute).
    Threshold: 0.3 = moderate sensitivity (catches most real scene cuts).
    """
    duration = end_time - start_time
    if duration <= 0:
        return []
    
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(max(0, start_time)),
        "-i", str(video_path),
        "-t", str(duration),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-vsync", "vfr",
        "-f", "null", "-"
    ]
    
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, encoding="utf-8"
        )
        stderr = result.stderr or ""
    except Exception as e:
        log.warning(f"Scene detection failed: {e}")
        return []
    
    # Parse pts_time from ffmpeg showinfo output
    scenes = []
    for match in re.finditer(r"pts_time:\s*([\d.]+)", stderr):
        t = float(match.group(1)) + start_time  # Convert relative to absolute
        scenes.append(t)
    
    # Always include the range boundaries as fallback anchor points
    scenes = [start_time] + scenes + [end_time]
    scenes = sorted(set(scenes))
    
    return scenes


def _find_best_scene(scenes: list, target_time: float, min_dur: float = 3.0, max_dur: float = 8.0) -> tuple:
    """
    Find the scene boundary closest to target_time and intelligently determine the duration.
    - Snaps to the nearest scene cut.
    - Ends at the next cut.
    - If the shot is too short (<3s), merges it with the next shot.
    - If the shot is too long (>8s), trims it.
    """
    if not scenes:
        return (max(0, target_time - 1), 6.0)
    
    # Find closest scene boundary to the target timestamp
    best = min(scenes, key=lambda s: abs(s - target_time))
    start_time = max(0, best)
    
    # Intelligently calculate duration by looking at upcoming scenes
    idx = scenes.index(best)
    end_time = start_time + max_dur # default to max duration
    
    if idx + 1 < len(scenes):
        next_cut = scenes[idx + 1]
        dur = next_cut - start_time
        
        # If the shot is too short, try to merge it with the following shot
        if dur < min_dur and idx + 2 < len(scenes):
            next_cut = scenes[idx + 2]
            dur = next_cut - start_time
            
        # Clamp duration
        dur = max(min_dur, min(max_dur, dur))
    else:
        dur = max_dur
        
    return (start_time, dur)


def extract_script_clips(video_path: str, script_lines: list,
                         part_num: int, movie_name: str) -> str:
    """
    Extract clips intelligently: snap cuts exactly to cinematic scene boundaries,
    merge micro-shots, and concatenate them for a professional, fast-paced recap.
    """
    part_dir = CLIPS_DIR / movie_name.replace(" ", "_") / f"part_{part_num}"
    part_dir.mkdir(parents=True, exist_ok=True)
    
    if not script_lines:
        raise ValueError("No timestamped lines found in script")
        
    all_starts = [l["movie_start"] for l in script_lines]
    all_ends = [l["movie_end"] for l in script_lines]
    range_start = max(0, min(all_starts) - 5)
    range_end = max(all_ends) + 15
    
    log.info(f"Part {part_num}: Intelligently detecting scenes {range_start:.0f}s - {range_end:.0f}s...")
    scenes = _detect_scenes(video_path, range_start, range_end, threshold=0.25)
    log.info(f"Part {part_num}: Found {len(scenes)} precise scene boundaries.")
    
    clip_paths = []
    for i, line in enumerate(script_lines):
        target = line["movie_start"]
        
        # Snap to exact scene cut and intelligently calculate duration
        clip_start, clip_dur = _find_best_scene(scenes, target)
        clip_path = part_dir / f"clip_{i:03d}.mp4"
        
        log.debug(f"Intelligent Cut {i}: target={target:.1f}s -> snapped to {clip_start:.1f}s (dur={clip_dur:.1f}s)")
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(clip_start),
            "-i", str(video_path),
            "-t", str(clip_dur),
            "-c:v", "libx264", "-preset", "ultrafast",
            "-r", "30",
            "-pix_fmt", "yuv420p",
            "-an",  # no audio
            str(clip_path)
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=120)
            if clip_path.exists() and clip_path.stat().st_size > 1000:
                clip_paths.append(clip_path)
        except Exception as e:
            log.warning(f"Clip {i} extraction failed: {e}")
            
    if not clip_paths:
        raise RuntimeError(f"Intelligent extraction failed for Part {part_num}")
        
    # Concatenate clips
    concat_file = part_dir / "concat.txt"
    with open(concat_file, "w") as f:
        for p in clip_paths:
            escaped = str(p.resolve()).replace("\\", "/")
            f.write(f"file '{escaped}'\n")
            
    visual_path = str(part_dir / f"part_{part_num}_visual.mp4")
    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        visual_path
    ]
    
    subprocess.run(concat_cmd, capture_output=True, check=True, timeout=300)
    
    size_mb = Path(visual_path).stat().st_size / 1024 / 1024
    log.info(f"Part {part_num}: {len(clip_paths)} intelligently cut clips -> {visual_path} ({size_mb:.1f}MB)")
    
    return visual_path
