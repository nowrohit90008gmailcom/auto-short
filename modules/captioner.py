"""
Opus-style animated captions — ASS subtitle generator.
Creates word-by-word highlighted captions in Hinglish (Roman script).
Active word: Yellow/Orange bold. Surrounding words: White.
"""
from pathlib import Path
from utils.logger import get_logger

log = get_logger("captioner")

ASS_HEADER = """[Script Info]
Title: AutoShorts Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Active,Montserrat,76,&H00FFFFFF,&H000000FF,&H000000FF,&H80000000,-1,-1,0,0,100,100,2,0,1,6,2,5,40,40,0,1
Style: Inactive,Montserrat,64,&H00FFFFFF,&H000000FF,&H000000FF,&H80000000,-1,-1,0,0,100,100,2,0,1,3,2,5,40,40,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""


def _format_time(seconds: float) -> str:
    """Convert seconds to ASS time format H:MM:SS.CC"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_ass(word_timestamps: list, output_path: str,
                 words_per_group: int = 4) -> str:
    """
    Generate ASS subtitle file with word-by-word highlighting.
    
    Groups words into chunks of `words_per_group` and highlights
    each word as it's spoken (yellow active, white inactive).
    
    Args:
        word_timestamps: [{"word": str, "start": float, "end": float}, ...]
        output_path: Where to save the .ass file
        words_per_group: How many words to show at once (default 4)
    
    Returns:
        Path to the generated .ass file
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    if not word_timestamps:
        log.warning("No word timestamps provided, skipping caption generation")
        # Create empty ASS file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ASS_HEADER)
        return output_path
    
    events = []
    
    # Group words into chunks
    groups = []
    for i in range(0, len(word_timestamps), words_per_group):
        group = word_timestamps[i:i + words_per_group]
        groups.append(group)
    
    for group in groups:
        group_start = group[0]["start"]
        group_end = group[-1]["end"]
        
        # For each word in the group, create an event highlighting it
        for active_idx, active_word in enumerate(group):
            w_start = active_word["start"]
            w_end = active_word["end"]
            
            # Build the display text with active word highlighted
            # ASS override: {\c&H0080FFFF&} for yellow, {\c&HFFFFFF&} for white
            parts = []
            for j, w in enumerate(group):
                word_text = w["word"].strip().upper()
                if not word_text:
                    continue
                if j == active_idx:
                    # Active word — slightly larger
                    parts.append(
                        r"{\fscx115\fscy115}" +
                        word_text +
                        r"{\fscx100\fscy100}"
                    )
                else:
                    parts.append(word_text)
            
            line_text = " ".join(parts)
            
            start_t = _format_time(w_start)
            end_t = _format_time(w_end)
            
            events.append(
                f"Dialogue: 0,{start_t},{end_t},Active,,0,0,0,,{line_text}"
            )
    
    # Write ASS file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ASS_HEADER)
        for event in events:
            f.write(event + "\n")
    
    log.info(f"Generated {len(events)} caption events → {output_path}")
    return output_path
