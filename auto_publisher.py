import os
import time
import random
import datetime
import json
import pytz
from dotenv import dotenv_values
from pathlib import Path
from utils.logger import get_logger
from podcast_pipeline import run_podcast_pipeline
from modules.channel_scraper import get_random_unprocessed_video, mark_as_processed
from modules.facebook_publisher import upload_to_facebook_reels
from modules.youtube_publisher import upload_to_youtube_shorts

log = get_logger("auto_publisher")
IST = pytz.timezone('Asia/Kolkata')
PROFILES_DIR = Path("workspace") / "profiles"

def get_random_channel(profile_dir: Path) -> str:
    channels_file = profile_dir / "channels.txt"
    if not channels_file.exists():
        return None
    with open(channels_file, "r") as f:
        channels = [line.strip() for line in f if line.strip()]
    return random.choice(channels) if channels else None

def load_profiles() -> dict:
    profiles = {}
    if not PROFILES_DIR.exists():
        return profiles
    for bot_dir in PROFILES_DIR.iterdir():
        if bot_dir.is_dir():
            config_file = bot_dir / "config.json"
            if config_file.exists():
                try:
                    with open(config_file, "r") as f:
                        config = json.load(f)
                        profiles[bot_dir.name] = {
                            "path": bot_dir,
                            "run_times": config.get("run_times", [])
                        }
                except Exception as e:
                    log.error(f"Error loading {config_file}: {e}")
    return profiles

def get_next_event(profiles: dict):
    now_ist = datetime.datetime.now(IST)
    events = []
    
    for bot_name, data in profiles.items():
        for time_str in data["run_times"]:
            hour, minute = map(int, time_str.split(":"))
            
            target = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now_ist:
                # Target is tomorrow
                target += datetime.timedelta(days=1)
                
            events.append((target, bot_name, time_str))
            
    if not events:
        return None, None, None
        
    events.sort(key=lambda x: x[0])
    return events[0] # (next_dt, bot_name, time_str)

def get_seconds_until(target_dt: datetime.datetime) -> int:
    now_ist = datetime.datetime.now(IST)
    delta = (target_dt - now_ist).total_seconds()
    return max(0, int(delta))

def calculate_schedule_timestamps(target_dt: datetime.datetime):
    schedules = []
    for offset_hr in [5, 6, 7]: 
        # Schedule the videos to drop 5, 6, 7 hours after the event time
        # E.g., if event is 00:00, videos drop at 05:00, 06:00, 07:00
        drop_dt = target_dt + datetime.timedelta(hours=offset_hr)
        unix_ts = int(drop_dt.timestamp())
        iso_str = drop_dt.astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        schedules.append((unix_ts, iso_str))
    return schedules

def run_profile(bot_name: str, bot_dir: Path, target_dt: datetime.datetime):
    log.info(f"=== PROCESSING PROFILE: {bot_name} ===")
    
    channel_url = get_random_channel(bot_dir)
    if not channel_url:
        log.error(f"[{bot_name}] No channels found in channels.txt!")
        return
        
    history_file = bot_dir / "processed_history.json"
    video = get_random_unprocessed_video(channel_url, history_file)
    
    if not video:
        log.warning(f"[{bot_name}] No unprocessed videos found in {channel_url}.")
        return
        
    log.info(f"[{bot_name}] Picked video: {video['title']} ({video['url']})")
    
    generated_shorts = run_podcast_pipeline(video["url"], video["title"])
    
    if not generated_shorts:
        log.error(f"[{bot_name}] Pipeline failed to generate shorts.")
        mark_as_processed(video["id"], history_file)
        return
        
    env_vars = dotenv_values(bot_dir / ".env")
    page_id = env_vars.get("FB_PAGE_ID")
    page_token = env_vars.get("FB_PAGE_TOKEN")
    credentials_dir = bot_dir / "credentials"
    
    schedules = calculate_schedule_timestamps(target_dt)
    
    for idx, short in enumerate(generated_shorts):
        if idx >= 3:
            break
            
        fb_unix, yt_iso = schedules[idx]
        log.info(f"[{bot_name}] Scheduling Short {idx+1}: {short['title']}")
        
        fb_success = upload_to_facebook_reels(
            video_path=short["video_path"],
            title=short["title"],
            description=short["description"],
            page_id=page_id,
            access_token=page_token,
            schedule_time=fb_unix
        )
        
        yt_success = upload_to_youtube_shorts(
            video_path=short["video_path"],
            title=short["title"],
            description=short["description"],
            credentials_dir=credentials_dir,
            publish_at=yt_iso
        )
        
        if fb_success and yt_success:
            log.info(f"[{bot_name}] Successfully scheduled {short['title']}!")
        else:
            log.error(f"[{bot_name}] Failed to fully schedule {short['title']}.")
            
    mark_as_processed(video["id"], history_file)
    log.info(f"=== {bot_name} RUN COMPLETE ===")

def start_daemon(instant_run: bool = False):
    log.info("Starting Multi-Bot Event Scheduler (IST Timezone)...")
    
    first_loop = True
    
    while True:
        try:
            profiles = load_profiles()
            if not profiles:
                log.error("No profiles found in workspace/profiles/")
                time.sleep(300)
                continue
                
            next_dt, bot_name, time_str = get_next_event(profiles)
            
            if not next_dt:
                log.error("No run_times configured in any profile config.json")
                time.sleep(300)
                continue
                
            now_ist = datetime.datetime.now(IST)
            sleep_sec = get_seconds_until(next_dt)
            
            is_grace_period = False
            active_bot = None
            active_dt = None
            
            for b_name, data in profiles.items():
                for t_str in data["run_times"]:
                    hour, minute = map(int, t_str.split(":"))
                    past_target = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if past_target > now_ist:
                        past_target -= datetime.timedelta(days=1)
                    
                    diff = (now_ist - past_target).total_seconds()
                    if 0 <= diff < 1800:
                        is_grace_period = True
                        active_bot = b_name
                        active_dt = past_target
                        log.info(f"Within 30-min grace period for {b_name} ({t_str}). Starting immediately!")
                        break
                if is_grace_period:
                    break
            
            if instant_run and first_loop:
                log.info("INSTANT RUN TRIGGERED! Forcing processing of all profiles sequentially right now...")
                for b_name, data in profiles.items():
                    run_profile(b_name, data["path"], now_ist)
                first_loop = False
                continue
                
            if is_grace_period:
                run_profile(active_bot, profiles[active_bot]["path"], active_dt)
            else:
                log.info(f"Sleeping for {sleep_sec} seconds until next event: {bot_name} at {next_dt.strftime('%Y-%m-%d %H:%M:%S')} IST...")
                time.sleep(sleep_sec)
                
                run_profile(bot_name, profiles[bot_name]["path"], next_dt)
                
        except Exception as e:
            log.error(f"Daemon encountered a fatal error: {e}")
            log.info("Sleeping for 5 minutes before retrying...")
            time.sleep(300)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--instant", action="store_true", help="Force an instant run of all bots bypassing schedule")
    args = parser.parse_args()
    
    start_daemon(instant_run=args.instant)
