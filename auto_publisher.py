import os
import time
import random
import datetime
import pytz
from dotenv import load_dotenv
from pathlib import Path
from utils.logger import get_logger
from podcast_pipeline import run_podcast_pipeline
from modules.channel_scraper import get_random_unprocessed_video, mark_as_processed
from modules.facebook_publisher import upload_to_facebook_reels
from modules.youtube_publisher import upload_to_youtube_shorts

load_dotenv()
log = get_logger("auto_publisher")
IST = pytz.timezone('Asia/Kolkata')

def get_random_channel() -> str:
    channels_file = Path("workspace/channels.txt")
    if not channels_file.exists():
        return None
    with open(channels_file, "r") as f:
        channels = [line.strip() for line in f if line.strip()]
    return random.choice(channels) if channels else None

def get_seconds_until_next_run() -> int:
    """Calculates seconds until the next 12:00 AM or 12:00 PM IST."""
    now_ist = datetime.datetime.now(IST)
    
    # Target 1: Today at Noon (12:00:00)
    target_noon = now_ist.replace(hour=12, minute=0, second=0, microsecond=0)
    
    # Target 2: Tomorrow at Midnight (00:00:00)
    target_midnight = now_ist.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
    
    if now_ist < target_noon:
        next_run = target_noon
        run_type = "NOON"
    else:
        next_run = target_midnight
        run_type = "MIDNIGHT"
        
    delta = (next_run - now_ist).total_seconds()
    return int(delta), run_type, next_run

def calculate_schedule_timestamps(run_type: str, run_date: datetime.datetime):
    """
    Returns a list of 3 tuples (unix_timestamp, iso8601_string) for Facebook and YouTube.
    MIDNIGHT RUN -> 5 AM, 6 AM, 7 AM IST today.
    NOON RUN -> 5 PM, 6 PM, 7 PM IST today.
    """
    schedules = []
    
    if run_type == "MIDNIGHT":
        hours = [5, 6, 7] # 5 AM, 6 AM, 7 AM
    else:
        hours = [17, 18, 19] # 5 PM, 6 PM, 7 PM
        
    for h in hours:
        # Create datetime in IST
        target_dt = run_date.replace(hour=h, minute=0, second=0, microsecond=0)
        
        # Convert to Unix timestamp for Facebook
        unix_ts = int(target_dt.timestamp())
        
        # Convert to ISO 8601 UTC for YouTube
        iso_str = target_dt.astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        schedules.append((unix_ts, iso_str))
        
    return schedules

def start_daemon(instant_run: bool = False):
    log.info("Starting Strict Scheduled Auto-Publisher Daemon (IST Timezone)...")
    
    # If instant_run is True, we pretend we are in a valid window for the first loop
    first_loop = True
    
    while True:
        try:
            # 1. Wait for the exact time window (12 AM or 12 PM)
            sleep_sec, run_type, next_run_dt = get_seconds_until_next_run()
            
            now_ist = datetime.datetime.now(IST)
            noon_today = now_ist.replace(hour=12, minute=0, second=0, microsecond=0)
            midnight_today = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
            
            is_grace_period = False
            active_run_type = run_type
            active_run_dt = next_run_dt
            
            if 0 <= (now_ist - noon_today).total_seconds() < 1800:
                is_grace_period = True
                active_run_type = "NOON"
                active_run_dt = noon_today
                log.info("Within 30-min grace period of NOON run. Starting immediately!")
            elif 0 <= (now_ist - midnight_today).total_seconds() < 1800:
                is_grace_period = True
                active_run_type = "MIDNIGHT"
                active_run_dt = midnight_today
                log.info("Within 30-min grace period of MIDNIGHT run. Starting immediately!")
                
            if instant_run and first_loop:
                log.info("INSTANT RUN TRIGGERED! Bypassing sleep timer...")
                is_grace_period = True
                # Pick the closest run type for scheduling purposes
                active_run_type = "NOON" if (now_ist.hour >= 6 and now_ist.hour < 18) else "MIDNIGHT"
                # Keep active_run_dt as next_run_dt so the scheduled times are in the future
                active_run_dt = now_ist
                first_loop = False
                
            if not is_grace_period:
                log.info(f"Sleeping for {sleep_sec} seconds until next {run_type} run at {next_run_dt.strftime('%Y-%m-%d %H:%M:%S')} IST...")
                time.sleep(sleep_sec)
                # After sleeping, we wake up exactly at the target time
                active_run_type = run_type
                active_run_dt = next_run_dt
            
            log.info(f"=== WAKING UP FOR {active_run_type} RUN ===")
            
            # 2. Pick a random channel
            channel_url = get_random_channel()
            if not channel_url:
                log.error("No channels found in workspace/channels.txt!")
                continue
                
            log.info(f"Targeting Channel: {channel_url}")
            video = get_random_unprocessed_video(channel_url)
            
            if not video:
                log.warning(f"No unprocessed videos found in {channel_url}.")
                continue
                
            log.info(f"Picked video: {video['title']} ({video['url']})")
            
            # 3. Run Transformative Pipeline (Generates 3 shorts)
            generated_shorts = run_podcast_pipeline(video["url"], video["title"])
            
            if not generated_shorts:
                log.error("Pipeline failed to generate shorts. Marking as processed and skipping.")
                mark_as_processed(video["id"])
                continue
                
            # Calculate Schedule Timestamps
            schedules = calculate_schedule_timestamps(active_run_type, active_run_dt)
            
            # 4. Publish/Schedule Shorts
            for idx, short in enumerate(generated_shorts):
                if idx >= 3:
                    break # Safety limit, only schedule up to 3
                    
                fb_unix, yt_iso = schedules[idx]
                log.info(f"Scheduling Short {idx+1}: {short['title']}")
                
                # Facebook (Scheduled)
                fb_success = upload_to_facebook_reels(
                    video_path=short["video_path"],
                    title=short["title"],
                    description=short["description"],
                    schedule_time=fb_unix
                )
                
                # YouTube (Scheduled)
                yt_success = upload_to_youtube_shorts(
                    video_path=short["video_path"],
                    title=short["title"],
                    description=short["description"],
                    publish_at=yt_iso
                )
                
                if fb_success and yt_success:
                    log.info(f"Successfully scheduled {short['title']} to Facebook and YouTube!")
                else:
                    log.error(f"Failed to fully schedule {short['title']}.")
                    
            # 5. Mark as processed
            mark_as_processed(video["id"])
            log.info(f"=== {active_run_type} RUN COMPLETE ===")
            
        except Exception as e:
            log.error(f"Daemon encountered a fatal error: {e}")
            log.info("Sleeping for 5 minutes before retrying...")
            time.sleep(300)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--instant", action="store_true", help="Force an instant run bypassing the schedule")
    args = parser.parse_args()
    
    start_daemon(instant_run=args.instant)
