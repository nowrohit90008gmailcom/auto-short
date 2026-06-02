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
6. NARRATOR SCRIPTS: Write 3 extremely short (1 sentence maximum) scripts for an AI Voiceover Narrator based on the context of the clip:
   - INTRO: A massive, context-aware hook to introduce the clip (e.g., "You won't believe what X just admitted about Y...").
   - MIDRO: A pattern interrupt halfway through (e.g., "Hold on, this next part is actually insane...").
   - OUTRO: A call to action related to the clip (e.g., "Do you agree with him? Subscribe for more!").

FORMAT YOUR RESPONSE EXACTLY LIKE THIS:
[MM:SS-MM:SS]
TITLE: (Catchy viral title)
DESCRIPTION: (Viral description with #hashtags)
KEYWORDS: keyword1, keyword2, keyword3
INTRO: (Narrator Intro)
MIDRO: (Narrator Midro)
OUTRO: (Narrator Outro)
"""

    user_prompt = f"Find the {total_clips} most viral, mind-blowing, or controversial segments in this transcript:\n\n{transcript_text}"

    # --- The Ultimate Enterprise Fallback Chain ---
    import os
    import time
    import requests
    
    # 1. Define the ultimate list of free providers (in order of preference)
    providers = [
        {
            "name": "Gemini (Google)",
            "type": "gemini",
            "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            "keys_env": "GEMINI_API_KEY",
            "model_env": "GEMINI_MODEL",
            "default_model": "gemini-3.5-flash"
        },
        {
            "name": "Cerebras",
            "type": "openai",
            "url": "https://api.cerebras.ai/v1/chat/completions",
            "keys_env": "CEREBRAS_API_KEYS",
            "model_env": "CEREBRAS_MODEL",
            "default_model": "gpt-oss-120b"
        },
        {
            "name": "Groq",
            "type": "openai",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "keys_env": "GROQ_API_KEYS",
            "model_env": "GROQ_MODEL",
            "default_model": "meta-llama/llama-4-maverick-17b-128e-instruct"
        },
        {
            "name": "SambaNova",
            "type": "openai",
            "url": "https://api.sambanova.ai/v1/chat/completions",
            "keys_env": "SAMBANOVA_API_KEY",
            "model_env": "SAMBANOVA_MODEL",
            "default_model": "Meta-Llama-3.3-70B-Instruct"
        },
        {
            "name": "OpenRouter",
            "type": "openai",
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "keys_env": "OPENROUTER_API_KEY",
            "model_env": "OPENROUTER_MODEL",
            "default_model": "openrouter/auto"
        }
    ]
    
    for provider in providers:
        keys_str = os.getenv(provider["keys_env"], "")
        keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        if not keys:
            log.warning(f"Skipping {provider['name']} - No keys found in {provider['keys_env']}")
            continue
            
        model = os.getenv(provider["model_env"], provider["default_model"])
        
        # Failsafe: Override deprecated Cerebras models from old .env files
        if model == "llama3.1-70b":
            model = "gpt-oss-120b"
            log.warning("Detected deprecated Cerebras model 'llama3.1-70b' in .env! Automatically upgrading to 'gpt-oss-120b'.")
        
        for key_idx, key in enumerate(keys):
            log.info(f"Attempting {provider['name']} extraction using model '{model}' (Key {key_idx+1})...")
            
            try:
                if provider["type"] == "gemini":
                    # Gemini REST API Format
                    url = provider["url"].format(model=model, key=key)
                    headers = {"Content-Type": "application/json"}
                    payload = {
                        "contents": [{"parts": [{"text": user_prompt}]}],
                        "systemInstruction": {"parts": [{"text": system_prompt}]}
                    }
                    r = requests.post(url, headers=headers, json=payload, timeout=60)
                    if r.status_code == 429:
                        log.warning(f"{provider['name']} rate limited. Trying next...")
                        continue
                    r.raise_for_status()
                    
                    # Extract Gemini Response
                    output = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    log.info(f"{provider['name']} highlight extraction complete:\n{output}")
                    return _parse_highlights(output)
                    
                elif provider["type"] == "openai":
                    # OpenAI Compatible REST API Format
                    headers = {
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json"
                    }
                    # OpenRouter specific header
                    if provider["name"] == "OpenRouter":
                        headers["HTTP-Referer"] = "https://github.com/nowrohit90008gmailcom/auto-short"
                        
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.7
                    }
                    r = requests.post(provider["url"], headers=headers, json=payload, timeout=60)
                    if r.status_code == 429:
                        log.warning(f"{provider['name']} rate limited. Trying next...")
                        continue
                    r.raise_for_status()
                    
                    # Extract OpenAI Response
                    output = r.json()["choices"][0]["message"]["content"]
                    log.info(f"{provider['name']} highlight extraction complete:\n{output}")
                    return _parse_highlights(output)
                    
            except requests.exceptions.RequestException as e:
                error_details = e.response.text if e.response is not None else str(e)
                log.error(f"{provider['name']} failed: {e} - Details: {error_details}")
                time.sleep(1)
            except Exception as e:
                log.error(f"{provider['name']} generic failure: {e}")
                time.sleep(1)

    log.error("CRITICAL: Every single provider in the Ultimate Fallback Chain failed!")
    return []

def _parse_highlights(text: str) -> list:
    highlights = []
    blocks = text.split('[')
    
    for block in blocks:
        if not block.strip() or ']' not in block:
            continue
        try:
            # Parse [MM:SS-MM:SS]
            ts_str, rest = block.split(']', 1)
            start_str, end_str = ts_str.split('-')
            
            s_m, s_s = start_str.strip().split(':')
            start_time = int(s_m) * 60 + int(s_s)
            
            e_m, e_s = end_str.strip().split(':')
            end_time = int(e_m) * 60 + int(e_s)
            
            # Extract title, desc, and keywords
            title = "Viral Clip"
            description = "Check out this crazy moment! #shorts #viral"
            keywords = ["podcast"]
            intro_script = "You won't believe what happened in this clip!"
            midro_script = "Wait, it gets even crazier..."
            outro_script = "Subscribe for more viral podcasts!"
            
            for line in rest.split('\n'):
                line = line.strip()
                if line.startswith('TITLE:'):
                    title = line.replace('TITLE:', '').strip()
                elif line.startswith('DESCRIPTION:'):
                    description = line.replace('DESCRIPTION:', '').strip()
                elif line.startswith('KEYWORDS:'):
                    kw_str = line.split(":", 1)[1].strip()
                    keywords = [k.strip() for k in kw_str.split(',')]
                elif line.startswith('INTRO:'):
                    intro_script = line.replace('INTRO:', '').strip()
                elif line.startswith('MIDRO:'):
                    midro_script = line.replace('MIDRO:', '').strip()
                elif line.startswith('OUTRO:'):
                    outro_script = line.replace('OUTRO:', '').strip()
            
            highlights.append({
                "start": start_time,
                "end": end_time,
                "title": title,
                "description": description,
                "keywords": keywords,
                "intro": intro_script,
                "midro": midro_script,
                "outro": outro_script
            })
        except Exception as e:
            log.warning(f"Failed to parse highlight block: {e}")
            
    return highlights
