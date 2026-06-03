import os
import random
import subprocess
from pathlib import Path
from utils.logger import get_logger

log = get_logger("transform_editor")

def assemble_transformative_short(podcast_clip: str, gameplay_video: str, bgm_audio: str, broll_video: str, captions_ass: str, output_path: str, title_hook: str, intro_audio_path: str = None, midro_audio_path: str = None, outro_audio_path: str = None):
    if not os.path.exists(podcast_clip):
        raise FileNotFoundError(f"Podcast clip not found: {podcast_clip}")
        
    try:
        import json
        probe = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", podcast_clip], capture_output=True, text=True)
        dur = float(json.loads(probe.stdout)["format"]["duration"])
    except Exception:
        dur = 60.0
        
    # Scale duration because of 1.23x speedup
    sped_dur = dur / 1.23
    
    gp_start = 0
    if gameplay_video and os.path.exists(gameplay_video):
        try:
            probe = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", gameplay_video], capture_output=True, text=True)
            gp_dur = float(json.loads(probe.stdout)["format"]["duration"])
            if gp_dur > sped_dur + 10:
                gp_start = random.uniform(0, gp_dur - sped_dur - 2)
        except Exception:
            pass
    
    # STEP 1: Generate the Main Podcast Short (with Cinematic Filter, Zoom, Voice Changer, Captions)
    work_dir = Path(output_path).parent
    main_mp4 = str(work_dir / "main.mp4")
    
    cmd = ["ffmpeg", "-y", "-i", podcast_clip]
    if gameplay_video and os.path.exists(gameplay_video):
        cmd.extend(["-ss", str(gp_start), "-t", str(sped_dur), "-i", gameplay_video])
        gp_idx = 1
    else:
        cmd.extend(["-f", "lavfi", "-i", f"color=c=black:s=1080x960:d={sped_dur}"])
        gp_idx = 1
        
    has_broll = broll_video and os.path.exists(broll_video)
    if has_broll:
        cmd.extend(["-i", broll_video])
        broll_idx = 2
        
    has_bgm = bgm_audio and os.path.exists(bgm_audio)
    if has_bgm:
        cmd.extend(["-stream_loop", "-1", "-i", bgm_audio])
        bgm_idx = 3 if has_broll else 2
        
    filters = []
    # Cinematic Filter + Zoompan on Top Half (Speed up video by 1.23x)
    filters.append(f"[0:v]setpts=PTS/1.23,eq=brightness=-0.1:contrast=1.3:saturation=0.7:gamma=0.7,scale=720:896:force_original_aspect_ratio=increase,crop=720:896,zoompan=z='1.05+0.05*sin(time)':d=1:s=720x896:fps=30,setsar=1:1[top]")
    filters.append(f"[{gp_idx}:v]scale=720:384:force_original_aspect_ratio=increase,crop=720:384,setsar=1:1[bottom]")
    filters.append("[top][bottom]vstack=inputs=2,setsar=1:1,setdar=9:16[stacked]")
    current_out = "[stacked]"
    
    if has_broll:
        filters.append(f"[{broll_idx}:v]scale=720:896:force_original_aspect_ratio=increase,crop=720:896[broll_scaled]")
        filters.append(f"{current_out}[broll_scaled]overlay=x=0:y=0:enable='between(t,2,5)'[with_broll]")
        current_out = "[with_broll]"
        
    if captions_ass and os.path.exists(captions_ass):
        ass_rel = os.path.relpath(captions_ass, os.getcwd()).replace("\\", "/")
        filters.append(f"{current_out}ass='{ass_rel}'[final]")
    else:
        filters.append(f"{current_out}copy[final]")
        
    # Audio: Voice Changer (pitch +1.05) + Speedup (1.23x total) + Dynamic Normalization + Volume Boost + BGM
    if has_bgm:
        filters.append(f"[0:a]asetrate=48000*1.05,aresample=48000,atempo=1.23/1.05,dynaudnorm,volume=2.5[a1];[{bgm_idx}:a]volume=0.07[a2];[a1][a2]amix=inputs=2:duration=first:dropout_transition=2[a_out]")
    else:
        filters.append(f"[0:a]asetrate=48000*1.05,aresample=48000,atempo=1.23/1.05,dynaudnorm,volume=2.5[a_out]")
        
    cmd.extend(["-filter_complex", ";".join(filters)])
    cmd.extend(["-map", "[final]", "-map", "[a_out]"])
    cmd.extend(["-c:v", "libx264", "-preset", "fast", "-r", "30", "-aspect", "9:16", "-c:a", "aac", "-b:a", "192k", main_mp4])
    
    try:
        log.info("Generating main cinematic clip...")
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=7200)
    except Exception as e:
        log.error(f"Main clip generation failed: {e}")
        return False
        
    # STEP 2: Holy Trinity Setup (If Intro exists)
    if not intro_audio_path or not os.path.exists(intro_audio_path):
        os.rename(main_mp4, output_path)
        return True
        
    try:
        log.info("Generating Holy Trinity (Intro, Midro, Outro)...")
        # Helper to generate a text+audio segment
        def make_segment(audio_file, text, out_file, bg_vid):
            dur_probe = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", audio_file], capture_output=True, text=True)
            a_dur = float(json.loads(dur_probe.stdout)["format"]["duration"]) + 0.5
            
            c = ["ffmpeg", "-y"]
            if bg_vid and os.path.exists(bg_vid):
                start = random.uniform(0, 10)
                c.extend(["-ss", str(start), "-t", str(a_dur), "-i", bg_vid])
            else:
                c.extend(["-f", "lavfi", "-i", f"color=c=black:s=720x1280:d={a_dur}"])
            
            c.extend(["-i", audio_file])
            escaped_text = text.replace("'", "\\'")
            # Crop to 9:16 to fill screen properly, reset SAR/DAR, draw text center screen
            vf = f"scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1:1,setdar=9:16,drawtext=text='{escaped_text}':fontcolor=white:fontsize=80:x=(w-text_w)/2:y=(h-text_h)/2:borderw=5:bordercolor=red"
            c.extend(["-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a"])
            c.extend(["-c:v", "libx264", "-preset", "fast", "-r", "30", "-aspect", "9:16", "-c:a", "aac", "-b:a", "192k", out_file])
            subprocess.run(c, check=True, capture_output=True)

        intro_mp4 = str(work_dir / "intro.mp4")
        midro_mp4 = str(work_dir / "midro.mp4")
        outro_mp4 = str(work_dir / "outro.mp4")
        part1_mp4 = str(work_dir / "part1.mp4")
        part2_mp4 = str(work_dir / "part2.mp4")
        
        make_segment(intro_audio_path, "WAIT FOR IT...", intro_mp4, gameplay_video)
        if midro_audio_path and os.path.exists(midro_audio_path):
            make_segment(midro_audio_path, "PART 2...", midro_mp4, gameplay_video)
        if outro_audio_path and os.path.exists(outro_audio_path):
            make_segment(outro_audio_path, "SUBSCRIBE!", outro_mp4, gameplay_video)
            
        # Split main.mp4 exactly in half
        half = sped_dur / 2
        c_part1 = ["ffmpeg", "-y", "-i", main_mp4, "-t", str(half), "-c", "copy", "-aspect", "9:16", part1_mp4]
        subprocess.run(c_part1, check=True, capture_output=True)
        c_part2 = ["ffmpeg", "-y", "-i", main_mp4, "-ss", str(half), "-c", "copy", "-aspect", "9:16", part2_mp4]
        subprocess.run(c_part2, check=True, capture_output=True)
        
        # Concat using filter_complex for YouTube compliance (avoids timebase corruption)
        files = ["intro.mp4", "part1.mp4"]
        if os.path.exists(midro_mp4): files.append("midro.mp4")
        files.append("part2.mp4")
        if os.path.exists(outro_mp4): files.append("outro.mp4")
        
        c = ["ffmpeg", "-y"]
        for f in files:
            c.extend(["-i", str(work_dir / f)])
            
        filter_str = ""
        for i in range(len(files)):
            filter_str += f"[{i}:v:0][{i}:a:0]"
        filter_str += f"concat=n={len(files)}:v=1:a=1[outv_raw][outa];[outv_raw]setsar=1:1,setdar=9:16[outv]"
        
        c.extend(["-filter_complex", filter_str, "-map", "[outv]", "-map", "[outa]"])
        c.extend(["-c:v", "libx264", "-preset", "fast", "-r", "30", "-aspect", "9:16", "-c:a", "aac", "-b:a", "192k", output_path])
        
        subprocess.run(c, check=True, capture_output=True)
        return True
    except Exception as e:
        log.error(f"Holy Trinity assembly failed: {e}")
        return False
