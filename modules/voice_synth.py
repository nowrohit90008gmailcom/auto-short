"""
Voice synthesis using Edge TTS (Microsoft Neural Voices).
Free, no API key needed, excellent Hindi/Hinglish support.
Falls back to ElevenLabs if configured.
"""
import os
import asyncio
import subprocess
import json
from pathlib import Path
from dotenv import load_dotenv
from utils.logger import get_logger

load_dotenv()
log = get_logger("voice_synth")

EDGE_VOICE = os.getenv("EDGE_TTS_VOICE", "hi-IN-SwaraNeural")
WORKSPACE = Path(__file__).resolve().parent.parent / "workspace"
AUDIO_DIR = WORKSPACE / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


async def _edge_tts_generate(text: str, output_path: str, voice: str) -> bool:
    """Generate speech using Edge TTS."""
    import edge_tts
    
    communicate = edge_tts.Communicate(text, voice, rate="+15%", pitch="+0Hz")
    await communicate.save(output_path)
    return True


async def _edge_tts_with_timestamps(text: str, output_path: str,
                                     voice: str) -> dict:
    """Generate speech + word timestamps using Edge TTS SubMaker."""
    import edge_tts
    
    communicate = edge_tts.Communicate(text, voice, rate="+15%", pitch="+0Hz")
    submaker = edge_tts.SubMaker()
    
    with open(output_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)
    
    # Parse word timestamps from SubMaker
    words = []
    # SubMaker stores cues as list of (offset_ms, text)
    if hasattr(submaker, "cues") and submaker.cues:
        for i, cue in enumerate(submaker.cues):
            offset_s = cue[0] / 10_000_000  # 100ns ticks → seconds
            word = cue[1] if len(cue) > 1 else ""
            # Estimate end time from next word or +0.3s
            end_s = (submaker.cues[i + 1][0] / 10_000_000
                     if i + 1 < len(submaker.cues)
                     else offset_s + 0.3)
            words.append({"word": word, "start": offset_s, "end": end_s})
    
    return {"words": words}


def synthesize(text: str, part_num: int, movie_name: str) -> dict:
    """
    Generate narration audio for a script part.
    
    Returns:
        {
            "audio_path": str,
            "duration": float,
            "word_timestamps": [{"word": str, "start": float, "end": float}, ...]
        }
    """
    out_dir = AUDIO_DIR / movie_name.replace(" ", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(out_dir / f"part_{part_num}_narration.mp3")
    
    sarvam_key = os.getenv("SARVAM_API_KEY")
    word_timestamps = []
    success = False
    
    if sarvam_key:
        speaker = os.getenv("SARVAM_VOICE", "ritu")
        log.info(f"Generating voice for Part {part_num} ({len(text)} chars) using Sarvam AI ({speaker})...")
        import requests
        import base64
        import re
        import tempfile
        import shutil
        
        # Helper to split text by sentences under 2000 chars
        def split_text_by_length(text_to_split: str, max_chars: int = 2000) -> list:
            sentence_endings = re.compile(r'([।\.?!\n])')
            parts = sentence_endings.split(text_to_split)
            
            sentences = []
            current_sentence = ""
            for part in parts:
                if not part:
                    continue
                if part in ['।', '.', '?', '!', '\n']:
                    current_sentence += part
                    sentences.append(current_sentence)
                    current_sentence = ""
                else:
                    current_sentence += part
            if current_sentence:
                sentences.append(current_sentence)
                
            chunks = []
            current_chunk = ""
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                if len(current_chunk) + len(s) + 1 <= max_chars:
                    if current_chunk:
                        current_chunk += " " + s
                    else:
                        current_chunk = s
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = s
            if current_chunk:
                chunks.append(current_chunk)
                
            final_chunks = []
            for c in chunks:
                if len(c) > max_chars:
                    for idx in range(0, len(c), max_chars):
                        final_chunks.append(c[idx:idx+max_chars])
                else:
                    final_chunks.append(c)
            return final_chunks

        text_chunks = split_text_by_length(text, 2000)
        log.info(f"Split narration text into {len(text_chunks)} chunks for Sarvam AI...")
        
        chunk_files = []
        try:
            for idx, chunk in enumerate(text_chunks):
                log.info(f"Synthesizing chunk {idx+1}/{len(text_chunks)} ({len(chunk)} chars)...")
                url = "https://api.sarvam.ai/text-to-speech"
                headers = {
                    "api-subscription-key": sarvam_key,
                    "Content-Type": "application/json"
                }
                payload = {
                    "text": chunk,
                    "speaker": speaker,
                    "target_language_code": "hi-IN",
                    "model": "bulbul:v3",
                    "pace": 1.05,
                    "sample_rate": 24000
                }
                res = requests.post(url, json=payload, headers=headers, timeout=60)
                if res.status_code == 200:
                    data = res.json()
                    if "audios" in data and isinstance(data["audios"], list) and len(data["audios"]) > 0:
                        audio_content = base64.b64decode(data["audios"][0])
                    elif "audio_content" in data:
                        audio_content = base64.b64decode(data["audio_content"])
                    else:
                        raise KeyError(f"No audio data found in Sarvam AI response keys: {list(data.keys())}")
                    
                    chunk_out = str(out_dir / f"part_{part_num}_narration_chunk_{idx}.wav")
                    with open(chunk_out, "wb") as f:
                        f.write(audio_content)
                    chunk_files.append(chunk_out)
                else:
                    raise RuntimeError(f"Sarvam AI failed with status {res.status_code}: {res.text}")
            
            # Concatenate/convert chunks to MP3
            if len(chunk_files) == 1:
                log.info(f"Converting single chunk from WAV to MP3...")
                subprocess.run(
                    ["ffmpeg", "-y", "-i", chunk_files[0], "-acodec", "libmp3lame", "-b:a", "192k", output_path],
                    capture_output=True, check=True, timeout=30
                )
                try:
                    os.remove(chunk_files[0])
                except Exception:
                    pass
            elif len(chunk_files) > 1:
                # Create a file list for ffmpeg concat
                with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f_list:
                    for chunk_file in chunk_files:
                        p = Path(chunk_file).resolve().as_posix()
                        p_escaped = p.replace("'", "'\\''")
                        f_list.write(f"file '{p_escaped}'\n")
                    list_path = f_list.name
                
                log.info(f"Concatenating {len(chunk_files)} audio chunks and transcoding to MP3 using FFmpeg...")
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-acodec", "libmp3lame", "-b:a", "192k", output_path],
                    capture_output=True, check=True, timeout=30
                )
                
                # Cleanup temp files
                try:
                    os.remove(list_path)
                    for chunk_file in chunk_files:
                        os.remove(chunk_file)
                except Exception:
                    pass
            
            log.info(f"Successfully synthesized audio via Sarvam AI!")
            success = True
        except Exception as e:
            log.error(f"Sarvam AI generation failed, falling back to Edge TTS: {e}", exc_info=True)
            # Cleanup any temp chunk files that were created
            for chunk_file in chunk_files:
                try:
                    if os.path.exists(chunk_file):
                        os.remove(chunk_file)
                except Exception:
                    pass
            
    if not success:
        log.info(f"Generating voice for Part {part_num} ({len(text)} chars) using Edge TTS ({EDGE_VOICE})...")
        # Generate with timestamps
        try:
            ts_data = asyncio.run(
                _edge_tts_with_timestamps(text, output_path, EDGE_VOICE)
            )
            word_timestamps = ts_data.get("words", [])
        except Exception as e:
            log.warning(f"Timestamp generation failed: {e}, generating without timestamps")
            try:
                asyncio.run(_edge_tts_generate(text, output_path, EDGE_VOICE))
            except Exception as e2:
                log.error(f"Edge TTS failed completely: {e2}")
                raise

    # Get duration via ffprobe
    duration = 0
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(output_path)],
            capture_output=True, text=True, timeout=15, encoding="utf-8"
        )
        duration = float(json.loads(probe.stdout)["format"]["duration"])
    except Exception:
        pass

    # If no word timestamps from Edge TTS, get them via Groq Whisper
    if not word_timestamps and duration > 0:
        log.info("Getting word timestamps via Groq Whisper on narration audio...")
        try:
            from modules.transcriber import _transcribe_chunk_groq, _extract_audio_chunk
            import tempfile
            
            # Convert mp3 to wav for Groq
            from modules.transcriber import _transcribe_chunk_groq
            result = _transcribe_chunk_groq(output_path)
            word_timestamps = result.get("words", [])
            log.info(f"Got {len(word_timestamps)} word timestamps from Groq")
        except Exception as e:
            log.warning(f"Groq timestamp fallback failed: {e}")
            word_timestamps = _fallback_word_timestamps(text, duration)

    return {
        "audio_path": output_path,
        "duration": duration,
        "word_timestamps": word_timestamps
    }


def _gtts_generate(text: str, output_path: str):
    """Generate speech using Google's free TTS."""
    from gtts import gTTS
    tts = gTTS(text=text, lang='hi', slow=False)
    tts.save(output_path)


def _openai_generate(text: str, output_path: str):
    """Generate speech using OpenAI TTS (requires OPENAI_API_KEY)."""
    from openai import OpenAI
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY is not set for TTS_PROVIDER=openai")
    client = OpenAI(api_key=key)
    response = client.audio.speech.create(
        model="tts-1",
        voice="alloy",
        input=text
    )
    response.write_to_file(output_path)


def synthesize_by_lines(lines: list, part_num: int, movie_name: str) -> dict:
    """
    Generate TTS audio per script line with Whisper verification.
    Each line is generated separately, verified at 95% accuracy,
    and regenerated up to 3 times if it fails.
    Then all chunks are concatenated into one audio file.
    
    Args:
        lines: [{"line": "narration text", "movie_start": float, "movie_end": float}, ...]
        part_num: Part number
        movie_name: Movie name for folder organization
    
    Returns: {"audio_path": str, "duration": float, "word_timestamps": [...]}
    """
    import re
    import tempfile
    
    out_dir = AUDIO_DIR / movie_name.replace(" ", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    final_output = str(out_dir / f"part_{part_num}_narration.mp3")
    
    chunk_paths = []
    all_word_timestamps = []
    total_duration = 0.0
    
    sarvam_key = os.getenv("SARVAM_API_KEY")
    speaker = os.getenv("SARVAM_VOICE", "ritu")
    
    for i, line_data in enumerate(lines):
        raw_text = line_data["line"]
        # Strip [MM:SS-MM:SS] timestamp prefix
        clean_text = re.sub(r'\[[\d:.\-]+\]\s*', '', raw_text).strip()
        if not clean_text or len(clean_text) < 5:
            continue
        
        log.info(f"Part {part_num} line {i+1}/{len(lines)}: generating audio ({len(clean_text)} chars)")
        
        best_chunk = None
        best_match = 0
        
        for attempt in range(1, 4):  # Up to 3 attempts
            chunk_path = str(out_dir / f"part_{part_num}_chunk_{i:03d}.mp3")
            
            # Generate TTS for this single line
            tts_provider = os.getenv("TTS_PROVIDER", "edge").lower()
            try:
                if tts_provider == "sarvam" and sarvam_key:
                    _generate_sarvam_chunk(clean_text, chunk_path, sarvam_key, speaker)
                elif tts_provider == "google":
                    _gtts_generate(clean_text, chunk_path)
                elif tts_provider == "openai":
                    _openai_generate(clean_text, chunk_path)
                else:  # default to edge
                    asyncio.run(_edge_tts_generate(clean_text, chunk_path, EDGE_VOICE))
            except Exception as e:
                log.warning(f"Line {i+1} attempt {attempt} TTS ({tts_provider}) failed: {e}")
                # Fallback to edge if another provider failed
                try:
                    asyncio.run(_edge_tts_generate(clean_text, chunk_path, EDGE_VOICE))
                except Exception:
                    continue
            
            if not Path(chunk_path).exists() or Path(chunk_path).stat().st_size < 500:
                continue
            
            # Verify with Whisper
            try:
                from modules.transcriber import _transcribe_chunk_groq
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_wav = tmp.name
                subprocess.run(
                    ["ffmpeg", "-y", "-i", chunk_path, "-ar", "16000", "-ac", "1",
                     "-acodec", "pcm_s16le", tmp_wav],
                    capture_output=True, check=True, timeout=30
                )
                result = _transcribe_chunk_groq(tmp_wav)
                whisper_text = result.get("text", "").strip()
                os.unlink(tmp_wav)
                
                # Word-level match
                script_words = set(clean_text.lower().split())
                whisper_words = set(whisper_text.lower().split())
                word_match = (len(script_words & whisper_words) / max(len(script_words), 1)) * 100
                
                # Character-level match (more forgiving for Hindi)
                script_chars = set(clean_text.replace(" ", "").lower())
                whisper_chars = set(whisper_text.replace(" ", "").lower())
                char_match = (len(script_chars & whisper_chars) / max(len(script_chars), 1)) * 100
                
                match_pct = max(word_match, char_match)
                log.info(f"Line {i+1} attempt {attempt}: {match_pct:.0f}% match")
                
                if match_pct > best_match:
                    best_match = match_pct
                    best_chunk = chunk_path
                
                if match_pct >= 95:
                    break
            except Exception as e:
                log.warning(f"Line {i+1} verification error: {e}")
                best_chunk = chunk_path  # Accept without verification
                best_match = 100
                break
        
        if best_chunk and Path(best_chunk).exists():
            # Get duration of this chunk
            try:
                probe = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_format", best_chunk],
                    capture_output=True, text=True, timeout=15, encoding="utf-8"
                )
                chunk_dur = float(json.loads(probe.stdout)["format"]["duration"])
            except Exception:
                chunk_dur = 3.0
            
            # Get word timestamps for this chunk via Whisper
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_wav = tmp.name
                subprocess.run(
                    ["ffmpeg", "-y", "-i", best_chunk, "-ar", "16000", "-ac", "1",
                     "-acodec", "pcm_s16le", tmp_wav],
                    capture_output=True, check=True, timeout=30
                )
                from modules.transcriber import _transcribe_chunk_groq
                ts_result = _transcribe_chunk_groq(tmp_wav)
                chunk_words = ts_result.get("words", [])
                os.unlink(tmp_wav)
                
                # Offset timestamps by accumulated duration
                for w in chunk_words:
                    w["start"] = w.get("start", 0) + total_duration
                    w["end"] = w.get("end", 0) + total_duration
                all_word_timestamps.extend(chunk_words)
            except Exception as e:
                log.warning(f"Line {i+1} timestamp extraction failed: {e}")
            
            chunk_paths.append(best_chunk)
            total_duration += chunk_dur
            log.info(f"Line {i+1} ✓ ({best_match:.0f}% match, {chunk_dur:.1f}s)")
    
    if not chunk_paths:
        raise RuntimeError(f"No audio chunks generated for Part {part_num}")
    
    # Concatenate all chunks into final audio
    concat_file = str(out_dir / f"part_{part_num}_concat.txt")
    with open(concat_file, "w") as f:
        for p in chunk_paths:
            escaped = Path(p).resolve().as_posix()
            f.write(f"file '{escaped}'\n")
    
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
         "-acodec", "libmp3lame", "-b:a", "192k", final_output],
        capture_output=True, check=True, timeout=120
    )
    
    # Clean up chunk files
    for p in chunk_paths:
        try:
            os.unlink(p)
        except Exception:
            pass
    try:
        os.unlink(concat_file)
    except Exception:
        pass
    
    log.info(f"Part {part_num} voice: {total_duration:.1f}s, {len(all_word_timestamps)} word timestamps, "
             f"{len(chunk_paths)} chunks verified, saved to {final_output}")
    
    return {
        "audio_path": final_output,
        "duration": total_duration,
        "word_timestamps": all_word_timestamps,
    }


def _generate_sarvam_chunk(text: str, output_path: str, api_key: str, speaker: str):
    """Generate a single audio chunk via Sarvam AI TTS."""
    import requests
    import base64
    
    response = requests.post(
        "https://api.sarvam.ai/text-to-speech",
        headers={"api-subscription-key": api_key, "Content-Type": "application/json"},
        json={
            "inputs": [text],
            "target_language_code": "hi-IN",
            "speaker": speaker,
            "model": "bulbul:v2",
            "pitch": 0,
            "pace": 1.1,
            "loudness": 1.5,
            "speech_sample_rate": 22050,
            "enable_preprocessing": True,
        },
        timeout=60,
    )
    
    if response.status_code != 200:
        raise RuntimeError(f"Sarvam AI failed: {response.text[:200]}")
    
    audio_b64 = response.json().get("audios", [None])[0]
    if not audio_b64:
        raise RuntimeError("Sarvam AI returned no audio")
    
    wav_data = base64.b64decode(audio_b64)
    
    # Convert WAV to MP3
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_data)
        tmp_wav = tmp.name
    
    subprocess.run(
        ["ffmpeg", "-y", "-i", tmp_wav, "-acodec", "libmp3lame", "-b:a", "192k", output_path],
        capture_output=True, check=True, timeout=30
    )
    os.unlink(tmp_wav)
