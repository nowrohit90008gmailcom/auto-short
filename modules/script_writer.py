"""
AI script writer — generates 5-part timestamped Hinglish movie explanation.
Each script line references exact movie timestamps for clip extraction.

Premium storytelling: cinematic, dramatic, high-energy Hinglish narration
that syncs precisely with visual scenes.
"""
import re
import json
from utils.api_keys import chat_completion
from utils.logger import get_logger

log = get_logger("script_writer")

# Each part covers a specific portion of the movie timeline
PART_COVERAGE = {
    1: "PART 1 (0%-20%) — Setup, character intro, inciting incident. OPEN with a high-energy trailer hook.",
    2: "PART 2 (20%-40%) — Escalation of tension, first major obstacle, initial secrets start leaking out.",
    3: "PART 3 (40%-60%) — Major turning point, massive betrayal or twist, emotional weight increases.",
    4: "PART 4 (60%-80%) — Suspense peak, hero backed into a corner, setup for final showdown.",
    5: "PART 5 (80%-100%) — Climax battle/reveal, biggest twist, final resolution. END with massive impact.",
}


def _get_transcript_slice(full_text: str, words: list, part_num: int, total: int = 5):
    """
    Get the relevant transcript portion for this part, formatted as timestamped blocks.
    This gives the LLM precise timestamps to reference, eliminating hallucination.
    """
    if not words:
        # Fallback if no word-level timestamps exist
        chars = len(full_text)
        chunk = chars // total
        start_idx = (part_num - 1) * chunk
        end_idx = min(start_idx + chunk + 2000, chars)
        return full_text[start_idx:end_idx], ""
    
    total_words = len(words)
    chunk_size = total_words // total
    start_i = (part_num - 1) * chunk_size
    end_i = min(start_i + chunk_size + 50, total_words)  # minor overlap
    
    slice_words = words[start_i:end_i]
    
    # Group words into ~5-10 second blocks for the LLM to read easily
    blocks = []
    current_block_words = []
    block_start_time = slice_words[0].get("start", 0) if slice_words else 0
    
    for w in slice_words:
        t = w.get("start", 0)
        word_text = w.get("word", "")
        
        # Start a new block every 8 seconds, or on a sentence-ending punctuation
        if t - block_start_time > 8.0 or (current_block_words and current_block_words[-1].endswith(('.', '?', '!'))):
            if current_block_words:
                mm, ss = int(block_start_time // 60), int(block_start_time % 60)
                blocks.append(f"[{mm:02d}:{ss:02d}] {' '.join(current_block_words)}")
            current_block_words = [word_text]
            block_start_time = t
        else:
            current_block_words.append(word_text)
            
    # Add final block
    if current_block_words:
        mm, ss = int(block_start_time // 60), int(block_start_time % 60)
        blocks.append(f"[{mm:02d}:{ss:02d}] {' '.join(current_block_words)}")
        
    transcript_slice = "\n".join(blocks)
    timestamp_guide = "The transcript below is formatted with exact timestamps. Use these EXACT timestamps in your script. DO NOT GUESS OR INVENT TIMESTAMPS."
    
    return transcript_slice[:15000], timestamp_guide


def _build_prompt(transcript_text: str, movie_name: str, part_num: int,
                  total: int, transcript_slice: str, timestamp_guide: str):
    system = """You are an ELITE Hindi movie storyteller who narrates movie explanations for YouTube Shorts.
You watch every scene carefully and explain EXACTLY what happens in the movie — the real plot, real characters, real events.

═══ #1 RULE: TELL THE ACTUAL STORY (MOST CRITICAL) ═══
- You MUST narrate the real story of the movie — what happens scene by scene.
- Extract REAL character names from the transcript. Use their actual names (e.g. "राज", "सिमरन", "विजय") — NEVER use generic words like "हीरो", "विलन", "लड़की".
- Describe SPECIFIC actions happening on screen: who does what, who says what, who goes where.
- Every single line must describe a CONCRETE scene from the movie:
  TERRIBLE: "अब कहानी में एक बड़ा धमाका होने वाला है" ← This is empty filler. NEVER write this.
  TERRIBLE: "यहाँ से कहानी में एक बड़ा ट्विस्ट आता है" ← This says nothing. NEVER write this.
  GOOD: "राज चुपचाप सिमरन के कमरे में घुसता है और अलमारी से वो खून से सनी चाकू निकालता है"
  GOOD: "विजय अपनी बीवी को फोन करता है लेकिन फोन उठाता है कोई और — उसका सबसे करीबी दोस्त अमन"
- If the transcript mentions a dialogue, paraphrase it naturally into the narration.
- Follow the chronological order of events as they appear in the transcript.

═══ WHAT TO NEVER DO ═══
- NEVER write vague hype lines that don't describe any specific scene (e.g. "यहाँ कहानी एक नया मोड़ लेती है", "अब होता है असली खेल").
- NEVER repeat the same information in different words across lines.
- NEVER use filler phrases: "तो basically", "actually", "you know", "दोस्तों", "भाइयों".
- NEVER address the viewer. Only narrate the story.
- NEVER invent scenes that aren't in the transcript. Stick to what actually happens.

═══ LANGUAGE ═══  
- HINDI IN DEVANAGARI SCRIPT ONLY (e.g. "राज चुपके से खिड़की से अंदर घुसता है").
- Do NOT use Roman/Latin script. Use pure Devanagari Hindi letters.
- Only English allowed: numbers and brackets inside timestamp tags [MM:SS-MM:SS].
- Use natural, conversational Hindi — not overly literary or formal.

═══ STORYTELLING FLOW ═══
- Part 1: Start with a gripping opening that sets up who the main character is and what their situation is.
- Parts 2-4: Continue the story naturally. Each part MUST begin by briefly connecting to where the last part ended (1 short sentence), then continue with new plot events.
- Part 5: Narrate the climax and ending. Wrap up the story satisfyingly.
- Every part (except Part 5) should end at a tense moment that makes the viewer want to watch the next part.

═══ DURATION & FORMAT (STRICT) ═══
- Target 200 to 240 words per part. NEVER exceed 240 words.
- Each line = ONE specific scene. 15-20 lines per part.
- Every line must describe what is visually happening at that timestamp.
- Keep lines short and punchy — 10 to 18 words each."""

    user = f"""MOVIE: {movie_name}
PART {part_num} OF {total} — {PART_COVERAGE.get(part_num, "")}

{timestamp_guide}

TRANSCRIPT FOR THIS SECTION:
{transcript_slice}

Write Part {part_num} narration script.
RULES:
- FORMAT STRICT: Every single line MUST start with a raw timestamp like [MM:SS-MM:SS]
- NEVER use markdown like **[MM:SS-MM:SS]**. Use exactly: [MM:SS-MM:SS] (your Hindi narration text here)
- Use timestamps strictly within the range provided above.
- WORD LIMIT: 200-240 words total. NEVER exceed 240.
- Devanagari Hindi only.
- NARRATE THE ACTUAL STORY: Extract real character names, real events, real dialogues from the transcript above. Do NOT write generic filler.
- Each line = one specific visual scene (who does what, where, how).
{"- Begin with a 1-sentence bridge from the previous part, then continue with new events." if part_num > 1 else "- Open with a gripping line that introduces the main character and situation."}"""

    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_script(raw_text: str) -> list:
    """Parse [MM:SS-MM:SS] lines into structured data."""
    lines = []
    pattern = r'\[(\d{1,2}):(\d{2})(?::(\d{2}))?[\s]*[-\u2013][\s]*(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*(.+)'
    
    for line in raw_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(pattern, line)
        if m:
            # Parse start
            s1, s2, s3 = int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None
            start = (s1 * 3600 + s2 * 60 + s3) if s3 is not None else (s1 * 60 + s2)
            # Parse end
            e1, e2, e3 = int(m.group(4)), int(m.group(5)), int(m.group(6)) if m.group(6) else None
            end = (e1 * 3600 + e2 * 60 + e3) if e3 is not None else (e1 * 60 + e2)
            text = m.group(7).strip()
            if text:
                lines.append({"line": text, "movie_start": float(start), "movie_end": float(end)})
        elif lines and line and not line.startswith("["):
            # Continuation of previous line
            lines[-1]["line"] += " " + line
    return lines


def generate_single_script(transcript: dict, movie_name: str,
                           part_num: int, num_parts: int = 5) -> dict:
    """Generate script for a single part. Tries g4f (free ChatGPT) → Gemini → Groq."""
    import os
    import requests
    
    full_text = transcript.get("full_text", "")
    words = transcript.get("words", [])
    
    transcript_slice, timestamp_guide = _get_transcript_slice(
        full_text, words, part_num, num_parts
    )
    
    messages = _build_prompt(
        full_text, movie_name, part_num, num_parts,
        transcript_slice, timestamp_guide
    )
    
    raw = None
    provider = "unknown"
    
    # ── Try 1: g4f (free ChatGPT / GPT-4) ──
    try:
        from g4f.client import Client
        log.info(f"Generating script Part {part_num}/{num_parts} via g4f (free ChatGPT)...")
        
        client = Client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
        )
        
        content = response.choices[0].message.content
        if content and len(content.strip()) > 50:
            raw = content.strip()
            provider = "g4f (ChatGPT)"
            log.info(f"Part {part_num} generated via g4f ({len(raw)} chars)")
    except Exception as e:
        log.warning(f"g4f failed for Part {part_num}: {e}")
    
    # ── Try 2: Gemini API ──
    if not raw:
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
        
        if gemini_key:
            try:
                log.info(f"Trying Gemini ({gemini_model}) for Part {part_num}...")
                parts = []
                for msg in messages:
                    role = "user" if msg["role"] in ("user", "system") else "model"
                    parts.append({"role": role, "parts": [{"text": msg["content"]}]})
                
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent",
                    params={"key": gemini_key},
                    json={"contents": parts,
                          "generationConfig": {"maxOutputTokens": 1500, "temperature": 0.7}},
                    timeout=60,
                )
                r.raise_for_status()
                raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                provider = f"gemini ({gemini_model})"
                log.info(f"Part {part_num} generated via Gemini ({len(raw)} chars)")
            except Exception as e:
                log.warning(f"Gemini failed for Part {part_num}: {e}")
    
    # ── Try 3: Groq / provider chain ──
    if not raw:
        log.info(f"Trying Groq provider chain for Part {part_num}...")
        result = chat_completion(messages, max_tokens=1500, temperature=0.7)
        raw, provider = result["text"], result["provider"]
        log.info(f"Part {part_num} generated via {provider} ({len(raw)} chars)")
    
    lines = _parse_script(raw)
    if not lines:
        log.warning(f"Part {part_num}: No timestamped lines, using raw text")
        lines = [{"line": raw, "movie_start": 0, "movie_end": 60}]
    
    full_narration = " ".join(l["line"] for l in lines)
    result = {
        "part": part_num, "raw_script": raw, "lines": lines,
        "full_text": full_narration, "provider": provider,
    }
    log.info(f"Part {part_num}: {len(lines)} lines, {len(full_narration.split())} words")
    return result


def generate_scripts(transcript: dict, movie_name: str, num_parts: int = 5) -> list:
    """Generate multi-part scripts (backward compatible). Uses Gemini."""
    import time
    parts = []
    for part_num in range(1, num_parts + 1):
        if part_num > 1:
            log.info(f"Waiting 3s before Part {part_num}...")
            time.sleep(3)
        parts.append(generate_single_script(transcript, movie_name, part_num, num_parts))
    return parts

