import os
import time
import random
import argparse
from pathlib import Path
from utils.logger import get_logger
from podcast_pipeline import run_podcast_pipeline
from modules.channel_scraper import get_random_unprocessed_video, mark_as_processed
from modules.facebook_publisher import upload_to_facebook_reels
from modules.youtube_publisher import upload_to_youtube_shorts

log = get_logger("auto_publisher")

def get_random_channel() -> str:
    channels_file = Path("workspace/channels.txt")
    if not channels_file.exists():
        return None
    with open(channels_file, "r") as f:
        channels = [line.strip() for line in f if line.strip()]
    return random.choice(channels) if channels else None

def start_daemon(interval_hours: int = 12):
    log.info("Starting Auto-Publisher Daemon for multiple channels...")
    log.info(f"Upload interval: Every {interval_hours} hours")
    
    while True:
        try:
            # 1. Pick a random channel
            channel_url = get_random_channel()
            if not channel_url:
                log.error("No channels found in workspace/channels.txt!")
                return
                
            log.info(f"Targeting Channel: {channel_url}")
            
            # 2. Get Random Video
            video = get_random_unprocessed_video(channel_url)
            
            if not video:
                log.warning(f"No unprocessed videos found in {channel_url}. Sleeping for 1 hour before trying another channel...")
                time.sleep(3600)
                continue
                
            log.info(f"Picked video: {video['title']} ({video['url']})")
            
            # 3. Run Transformative Pipeline
            generated_shorts = run_podcast_pipeline(video["url"], video["title"])
            
            if not generated_shorts:
                log.error("Pipeline failed to generate shorts. Marking as processed and skipping.")
                mark_as_processed(video["id"])
                continue
                
            # 4. Publish Shorts
            for short in generated_shorts:
                log.info(f"Publishing: {short['title']}")
                
                # Facebook
                fb_success = upload_to_facebook_reels(
                    video_path=short["video_path"],
                    title=short["title"],
                    description=short["description"]
                )
                
                # YouTube (Disabled per user request)
                # yt_success = upload_to_youtube_shorts(
                #     video_path=short["video_path"],
                #     title=short["title"],
                #     description=short["description"]
                # )
                
                if fb_success:
                    log.info(f"Successfully published {short['title']} to Facebook!")
                else:
                    log.error(f"Failed to publish {short['title']}.")
                    
            # 5. Mark as processed
            mark_as_processed(video["id"])
            
            # 6. Sleep
            sleep_seconds = interval_hours * 3600
            log.info(f"Cycle complete. Sleeping for {interval_hours} hours...")
            time.sleep(sleep_seconds)
            
        except Exception as e:
            log.error(f"Daemon encountered a fatal error: {e}")
            log.info("Sleeping for 1 hour before retrying...")
            time.sleep(3600)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous Podcast Shorts Publisher")
    parser.add_argument("--interval", type=int, default=12, help="Hours to wait between processing videos")
    args = parser.parse_args()
    
    start_daemon(args.interval)
