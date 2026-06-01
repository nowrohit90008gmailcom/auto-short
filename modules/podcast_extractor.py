import json
import re
from dotenv import load_dotenv
from utils.logger import get_logger

load_dotenv()

log = get_logger("podcast_extractor")

def extract_viral_highlights(transcript_words: list, total_clips: int = 3) -> list:
    """
    Passes the podcast transcript to ChatGPT to extract the most viral
    60-second continuous segments. Returns a list of segments with timestamps
    and B-roll keywords.
    """
    if not transcript_words:
        raise ValueError("No transcript words provided.")

    # Group words into 10-second timestamp blocks for the LLM
    blocks = []
    current_block = []
    block_start = transcript_words[0].get("start", 0)
    
    for w in transcript_words:
        t = w.get("start", 0)
        word = w.get("word", "")
        if t - block_start >= 10.0 or (current_block and current_block[-1].endswith(('.', '?', '!'))):
            if current_block:
                mm, ss = int(block_start // 60), int(block_start % 60)
                blocks.append(f"[{mm:02d}:{ss:02d}] {' '.join(current_block)}")
            current_block = [word]
            block_start = t
        else:
            current_block.append(word)
            
    if current_block:
        mm, ss = int(block_start // 60), int(block_start % 60)
        blocks.append(f"[{mm:02d}:{ss:02d}] {' '.join(current_block)}")

    transcript_text = "\n".join(blocks)
    # Truncate to avoid context limits if podcast is huge (18000 chars is safe for 8192 tokens)
    transcript_text = transcript_text[:18000] 

    system_prompt = """You are an elite TikTok/YouTube Shorts content curator focused on MAXIMUM WATCH TIME and VIRALITY.
Your job is to read a podcast transcript and extract the most VIRAL, EXTRAORDINARY, CONTROVERSIAL, EXPLICIT, NAUGHTY, OR SEXUALLY-RELATED segments.

CRITICAL RULES FOR VIRALITY:
1. LENGTH: Every clip MUST be between 60 and 170 seconds long. Calculate the timestamps carefully. DO NOT give me a 15-second or 30-second clip. Long clips equal higher watch time.
2. HUGE HOOK: The segment MUST start with a massive, curiosity-inducing hook (a highly controversial statement, an extraordinary crazy story, or a mind-blowing fact).
3. CLICKBAIT TITLE: Write an extreme, curiosity-driven title optimized for the YouTube Shorts algorithm (e.g., "He Revealed The TRUTH About..." or "The CRAZIEST Story Ever Told...").
4. DESCRIPTION: Write a highly engaging, SEO-optimized YouTube description with viral hashtags.
5. KEYWORDS: Provide 2-3 single-word visual keywords for B-roll (e.g. "money", "rocket", "brain", "scary").

FORMAT YOUR RESPONSE EXACTLY LIKE THIS:
[MM:SS-MM:SS]
TITLE: (Catchy viral title)
DESCRIPTION: (Viral description with #hashtags)
KEYWORDS: keyword1, keyword2, keyword3
"""

    user_prompt = f"Find the {total_clips} most viral, mind-blowing, or controversial segments in this transcript:\n\n{transcript_text}"

    # --- Triple Fallback Chain for Text Extraction ---
    import os
    import time
    
    # 1. DuckDuckGo AI (Free, Stable)
    try:
        log.info(f"Attempt 1: Asking DuckDuckGo AI (Claude-3-Haiku) to extract {total_clips} viral highlights...")
        from duckduckgo_search import DDGS
        ddgs = DDGS()
        combined_prompt = f"{system_prompt}\n\n{user_prompt}"
        output = ddgs.chat(combined_prompt, model="claude-3-haiku")
        log.info(f"DuckDuckGo highlight extraction complete:\n{output}")
        return _parse_highlights(output)
    except Exception as e:
        log.warning(f"DuckDuckGo failed: {e}")
        
    # 2. g4f (Free, Hacky Backup)
    try:
        log.info(f"Attempt 2: Asking ChatGPT via g4f fallback...")
        from g4f.client import Client as G4FClient
        g4f_client = G4FClient()
        response = g4f_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        output = response.choices[0].message.content
        log.info(f"g4f extraction complete:\n{output}")
        return _parse_highlights(output)
    except Exception as e:
        log.warning(f"g4f fallback failed: {e}")
        
    # 3. Groq API (Official, Rate-Limited)
    log.info(f"Attempt 3: Asking Groq (Llama 3 8B) API as final fallback...")
    import requests
    GROQ_KEYS = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
    
    if not GROQ_KEYS:
        log.error("CRITICAL ERROR: YOU DO NOT HAVE A '.env' FILE WITH 'GROQ_API_KEYS' ON YOUR VPS! GROQ API SKIPPED.")
    else:
        for attempt in range(len(GROQ_KEYS)):
            groq_key = GROQ_KEYS[attempt % len(GROQ_KEYS)]
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "llama3-8b-8192",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 2000
            }
            try:
                r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=60)
                if r.status_code == 429:
                    log.warning(f"Groq text extraction rate limited on key {attempt+1}. Trying next key...")
                    continue
                r.raise_for_status()
                output = r.json()["choices"][0]["message"]["content"]
                log.info(f"Groq highlight extraction complete:\n{output}")
                return _parse_highlights(output)
            except Exception as e:
                log.error(f"Groq extraction attempt {attempt+1} failed: {e}")
                time.sleep(1)
                
    log.error("All text extraction fallbacks (DDG -> g4f -> Groq) completely failed.")
    return []

def _parse_highlights(text: str) -> list:
    highlights = []
    blocks = text.split('[')
    
    for block in blocks:
        if not block.strip():
            continue
        try:
            # Parse [MM:SS-MM:SS]
            ts_str, rest = block.split(']', 1)
            start_str, end_str = ts_str.split('-')
            
            s_m, s_s = start_str.split(':')
            start_time = int(s_m) * 60 + int(s_s)
            
            e_m, e_s = end_str.split(':')
            end_time = int(e_m) * 60 + int(e_s)
            
            # Extract title, desc, and keywords
            title = "Viral Clip"
            description = "Check out this crazy moment! #shorts #viral"
            keywords = ["podcast"]
            
            for line in rest.split('\n'):
                line = line.strip()
                if line.startswith('TITLE:'):
                    title = line.replace('TITLE:', '').strip()
                elif line.startswith('DESCRIPTION:'):
                    description = line.replace('DESCRIPTION:', '').strip()
                elif line.startswith('KEYWORDS:'):
                    kw_str = line.split(":", 1)[1].strip()
                    keywords = [k.strip() for k in kw_str.split(',')]
            
            highlights.append({
                "start": start_time,
                "end": end_time,
                "title": title,
                "description": description,
                "keywords": keywords
            })
        except Exception as e:
            log.warning(f"Failed to parse highlight block: {e}")
            
    return highlights
