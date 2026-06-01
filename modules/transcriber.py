"""
Full-movie transcription using Groq Whisper API.

Splits movie audio into 5-minute chunks (under Groq's 25MB limit),
transcribes each chunk via cloud API, and merges into one unified
transcript with absolute timestamps.

Uses DNS-over-HTTPS bypass and key rotation.
"""
import os
import json
import hashlib
import subprocess
import tempfile
from pathlib import Path
from dotenv import load_dotenv

import utils.dns_bypass  # Auto-installs DoH patch
from utils.logger import get_logger

load_dotenv()
log = get_logger("transcriber")

GROQ_KEYS = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
CACHE_DIR = Path(__file__).resolve().parent.parent / "workspace" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

import random as _random


def _next_key() -> str:
    return _random.choice(GROQ_KEYS)


def _extract_audio_chunk(video_path: str, start: float, duration: float,
                         output_path: str) -> str:
    """Extract audio chunk as WAV (16kHz mono) for Groq upload."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-vn",                    # No video
        "-ar", "16000",           # 16kHz sample rate
        "-ac", "1",               # Mono
        "-acodec", "pcm_s16le",   # WAV format
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=120)
    return output_path


def _transcribe_chunk_groq(audio_path: str) -> dict:
    """Send audio chunk to Groq Whisper API. Returns {text, words, segments}."""
    import requests
    
    for attempt in range(len(GROQ_KEYS)):
        key = _next_key()
        try:
            with open(audio_path, "rb") as f:
                r = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key}"},
                    files={"file": (os.path.basename(audio_path), f, "audio/wav")},
                    data={
                        "model": "whisper-large-v3",
                        "response_format": "verbose_json",
                        "timestamp_granularities[]": "word",
                        "language": "hi",
                    },
                    timeout=180,
                )
            
            if r.status_code == 429:
                log.warning(f"Groq rate limit, rotating key...")
                import time
                time.sleep(3)
                continue
            
            r.raise_for_status()
            data = r.json()
            
            from indic_transliteration import sanscript
            
            # Extract words (Groq returns them as dicts)
            words = []
            for w in (data.get("words") or []):
                word = w.get("word", w) if isinstance(w, dict) else str(w)
                word = sanscript.transliterate(word, sanscript.DEVANAGARI, sanscript.ITRANS)
                start = w.get("start", 0) if isinstance(w, dict) else 0
                end = w.get("end", 0) if isinstance(w, dict) else 0
                words.append({"word": word, "start": start, "end": end})
            
            # Extract segments
            segments = []
            for s in (data.get("segments") or []):
                text = s.get("text", "").strip()
                text = sanscript.transliterate(text, sanscript.DEVANAGARI, sanscript.ITRANS)
                segments.append({
                    "start": s.get("start", 0),
                    "end": s.get("end", 0),
                    "text": text,
                })
            
            return {
                "text": sanscript.transliterate(data.get("text", ""), sanscript.DEVANAGARI, sanscript.ITRANS),
                "words": words,
                "segments": segments
            }
        except Exception as e:
            if attempt == len(GROQ_KEYS) - 1:
                raise
            log.warning(f"Groq attempt {attempt + 1} failed: {e}")
            import time
            time.sleep(2)
    
    raise RuntimeError("All Groq keys exhausted for transcription")


def _transcribe_chunk_local(audio_path: str) -> dict:
    """Local fallback using openai-whisper running on CPU."""
    import whisper
    from indic_transliteration import sanscript
    log.info("Falling back to local CPU whisper for transcription (this may take a bit longer)...")
    model = whisper.load_model("base")
    result = model.transcribe(audio_path, language="hi", word_timestamps=True)
    
    words = []
    segments = []
    for s in result.get("segments", []):
        text = s.get("text", "").strip()
        text = sanscript.transliterate(text, sanscript.DEVANAGARI, sanscript.ITRANS)
        segments.append({
            "start": s.get("start", 0),
            "end": s.get("end", 0),
            "text": text,
        })
        for w in s.get("words", []):
            word = w.get("word", "").strip()
            word = sanscript.transliterate(word, sanscript.DEVANAGARI, sanscript.ITRANS)
            words.append({
                "word": word,
                "start": w.get("start", 0),
                "end": w.get("end", 0)
            })
            
    return {
        "text": sanscript.transliterate(result.get("text", ""), sanscript.DEVANAGARI, sanscript.ITRANS),
        "words": words,
        "segments": segments
    }


def _transcribe_with_retry(audio_path: str, max_retries: int = 3) -> dict:
    """Transcribe with exponential backoff retry for transient errors."""
    import time
    for attempt in range(max_retries):
        try:
            return _transcribe_chunk_groq(audio_path)
        except Exception as e:
            if "exhausted" in str(e).lower() or attempt == max_retries - 1:
                log.warning(f"Groq transcription failed ({e}). Falling back to Local Whisper...")
                return _transcribe_chunk_local(audio_path)
            
            wait = 5 * (2 ** attempt)  # 5s, 10s, 20s
            log.warning(f"Transcription attempt {attempt + 1} failed: {e}, "
                        f"retrying in {wait}s...")
            time.sleep(wait)


def transcribe_full_movie(video_path: str, movie_name: str) -> dict:
    """
    Transcribe the full movie audio.
    
    Splits into 10-minute chunks, transcribes each via Groq,
    and merges into one unified transcript.
    
    Returns:
        {
            "full_text": str,
            "segments": [{"start": float, "end": float, "text": str}, ...],
            "words": [{"word": str, "start": float, "end": float}, ...],
            "duration": float
        }
    """
    # Check cache first (use movie_name only so cache persists across downloads/UUID shifts)
    import hashlib
    cache_key = hashlib.md5(movie_name.encode()).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}_transcript.json"
    
    if cache_file.exists():
        log.info(f"Using cached transcript: {cache_file}")
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    
    # Get video duration
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", str(video_path)],
        capture_output=True, text=True, timeout=30, encoding="utf-8"
    )
    total_duration = float(json.loads(probe.stdout)["format"]["duration"])
    log.info(f"Movie duration: {total_duration:.0f}s ({total_duration / 60:.1f} min)")
    
    # Split into 5-minute chunks (smaller = more reliable upload)
    chunk_duration = 300  # 5 minutes
    chunks = []
    offset = 0.0
    
    while offset < total_duration:
        chunk_len = min(chunk_duration, total_duration - offset)
        chunks.append((offset, chunk_len))
        offset += chunk_len
    
    log.info(f"Split into {len(chunks)} chunks of ~{chunk_duration}s each")
    
    # Transcribe each chunk
    all_text = []
    all_segments = []
    all_words = []
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        for i, (start, duration) in enumerate(chunks):
            log.info(f"Transcribing chunk {i + 1}/{len(chunks)} "
                     f"({start:.0f}s - {start + duration:.0f}s)...")
            
            # Extract audio chunk
            chunk_path = os.path.join(tmp_dir, f"chunk_{i:03d}.wav")
            _extract_audio_chunk(video_path, start, duration, chunk_path)
            
            # Check file size (Groq limit: 25MB)
            size_mb = os.path.getsize(chunk_path) / 1024 / 1024
            if size_mb > 24:
                log.warning(f"Chunk {i} is {size_mb:.1f}MB, splitting further...")
                # Split this chunk in half
                half = duration / 2
                for sub_idx, sub_start in enumerate([start, start + half]):
                    sub_path = os.path.join(tmp_dir, f"chunk_{i:03d}_sub{sub_idx}.wav")
                    _extract_audio_chunk(video_path, sub_start, half, sub_path)
                    result = _transcribe_chunk_groq(sub_path)
                    
                    all_text.append(result["text"])
                    for s in result["segments"]:
                        all_segments.append({
                            "start": s["start"] + sub_start,
                            "end": s["end"] + sub_start,
                            "text": s["text"],
                        })
                    for w in result["words"]:
                        all_words.append({
                            "word": w["word"],
                            "start": w["start"] + sub_start,
                            "end": w["end"] + sub_start,
                        })
                continue
            
            result = _transcribe_with_retry(chunk_path)
            
            all_text.append(result["text"])
            
            # Offset timestamps to absolute movie time
            for s in result["segments"]:
                all_segments.append({
                    "start": s["start"] + start,
                    "end": s["end"] + start,
                    "text": s["text"],
                })
            for w in result["words"]:
                all_words.append({
                    "word": w["word"],
                    "start": w["start"] + start,
                    "end": w["end"] + start,
                })
    
    transcript = {
        "full_text": " ".join(all_text),
        "segments": all_segments,
        "words": all_words,
        "duration": total_duration,
    }
    
    # Cache it
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)
    
    log.info(f"Transcription complete: {len(all_segments)} segments, "
             f"{len(all_words)} words, cached to {cache_file}")
    
    return transcript
