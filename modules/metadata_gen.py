"""
AI metadata generator — creates viral title, description, and hashtags.
"""
from utils.api_keys import chat_completion
from utils.logger import get_logger

log = get_logger("metadata_gen")


def generate_metadata(script_text: str, movie_name: str, part_num: int,
                      total_parts: int = 5) -> dict:
    """
    Generate YouTube/Facebook metadata for a short.
    
    Returns:
        {
            "title": str,
            "description": str,
            "hashtags": [str, ...],
            "tags": [str, ...]
        }
    """
    prompt = f"""Generate viral YouTube Shorts metadata for this movie explanation.

MOVIE: {movie_name}
PART: {part_num} of {total_parts}
SCRIPT: {script_text[:1000]}

RETURN EXACTLY THIS FORMAT (no extra text):
TITLE: [max 70 chars, Hinglish, use 1-2 emoji, create curiosity, include "Part {part_num}"]
DESCRIPTION: [3-4 lines in Hinglish, mention movie name, add call-to-action for other parts]
HASHTAGS: [10-15 comma-separated tags like #MovieExplained #Bollywood etc]

RULES:
- Title must create FOMO/curiosity
- Use Roman script Hinglish (NOT Devanagari)
- Include movie name in title
- End description with "Part {part_num + 1 if part_num < total_parts else ''} jaldi aa raha hai!" if not last part
- Add #Shorts tag always"""

    result = chat_completion(
        [{"role": "user", "content": prompt}],
        max_tokens=500,
        temperature=0.8,
    )
    
    raw = result["text"]
    
    # Parse the response
    title = ""
    description = ""
    hashtags = []
    
    for line in raw.split("\n"):
        line = line.strip()
        if line.upper().startswith("TITLE:"):
            title = line[6:].strip()
        elif line.upper().startswith("DESCRIPTION:"):
            description = line[12:].strip()
        elif line.upper().startswith("HASHTAGS:"):
            tags_raw = line[9:].strip()
            hashtags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        elif description and not line.upper().startswith(("TITLE:", "HASHTAGS:")):
            description += "\n" + line
    
    # Ensure #Shorts is included
    if "#Shorts" not in " ".join(hashtags):
        hashtags.append("#Shorts")
    
    # Fallback title
    if not title:
        title = f"😱 {movie_name} Movie Explained Part {part_num} | #Shorts"
    
    if not description:
        description = (f"{movie_name} ki kahani Part {part_num} mein!\n"
                       f"Full movie explanation in Hinglish.\n"
                       f"Like + Subscribe for more! 🔔")
    
    # Build tags list (for YouTube)
    tags = [movie_name, "movie explained", "hindi", "shorts",
            f"{movie_name} explained", "bollywood", "movie recap"]
    
    log.info(f"Part {part_num} metadata: '{title}' | {len(hashtags)} hashtags")
    
    return {
        "title": title,
        "description": description + "\n\n" + " ".join(hashtags),
        "hashtags": hashtags,
        "tags": tags,
    }
