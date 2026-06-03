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
from modules.upload_verifier import verify_youtube_upload, verify_facebook_upload
from modules.upload_history import record_upload
from modules.calendar import get_next_available_slot, update_calendar_slot

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
                            "run_times": config.get("run_times", ["08:00", "20:00"])
                        }
                except Exception as e:
                    log.error(f"Error loading {config_file}: {e}")
    return profiles

def calculate_schedule_timestamps(target_dt: datetime.datetime):
    unix_ts = int(target_dt.timestamp())
    iso_str = target_dt.astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return [(unix_ts, iso_str)]

def run_profile(bot_name: str, bot_dir: Path, target_dt: datetime.datetime):
    log.info(f"=== PROCESSING PROFILE: {bot_name} ===")
    
    channel_url = get_random_channel(bot_dir)
    if not channel_url:
        log.error(f"[{bot_name}] No channels found in channels.txt!")
        return False
        
    history_file = bot_dir / "processed_history.json"
    
    # Retry up to 5 different videos if YouTube randomly blocks one
    max_retries = 5
    generated_shorts = None
    video = None
    for attempt in range(1, max_retries + 1):
        video = get_random_unprocessed_video(channel_url, history_file)
        
        if not video:
            log.warning(f"[{bot_name}] No unprocessed videos found in {channel_url}.")
            return False
            
        log.info(f"[{bot_name}] Attempt {attempt}/{max_retries}: Trying video: {video['title']} ({video['url']})")
        
        try:
            generated_shorts = run_podcast_pipeline(video["url"], video["title"])
        except Exception as e:
            error_str = str(e)
            if "Sign in to confirm" in error_str or "Requested format is not available" in error_str:
                log.warning(f"[{bot_name}] YouTube blocked this video (attempt {attempt}/{max_retries}). Skipping to next video...")
                mark_as_processed(video["id"], history_file)
                time.sleep(5)
                continue
            else:
                log.error(f"[{bot_name}] Non-retryable error: {e}")
                mark_as_processed(video["id"], history_file)
                return False
        
        if not generated_shorts:
            log.error(f"[{bot_name}] Pipeline failed to generate shorts.")
            mark_as_processed(video["id"], history_file)
            continue
        
        # SUCCESS - we got shorts, proceed to publish
        break
    else:
        log.error(f"[{bot_name}] All {max_retries} video attempts were blocked by YouTube. Giving up this cycle.")
        return False
        
    env_vars = dotenv_values(bot_dir / ".env")
    page_id = env_vars.get("FB_PAGE_ID")
    page_token = env_vars.get("FB_PAGE_TOKEN")
    credentials_dir = bot_dir / "credentials"
    
    schedules = calculate_schedule_timestamps(target_dt)
    
    success = False
    for idx, short in enumerate(generated_shorts):
        if idx >= 1:
            break
            
        fb_unix, yt_iso = schedules[idx]
        log.info(f"[{bot_name}] Scheduling Short for {target_dt.strftime('%Y-%m-%d %H:%M:%S')} IST...")
        
        # --- Upload to Facebook ---
        fb_result = upload_to_facebook_reels(
            video_path=short["video_path"],
            title=short["title"],
            description=short["description"],
            page_id=page_id,
            access_token=page_token,
            schedule_time=fb_unix
        )
        fb_video_id = fb_result if fb_result and fb_result is not False else None
        fb_success = fb_video_id is not None
        
        # --- Upload to YouTube ---
        yt_result = upload_to_youtube_shorts(
            video_path=short["video_path"],
            title=short["title"],
            description=short["description"],
            credentials_dir=credentials_dir,
            publish_at=yt_iso
        )
        yt_video_id = yt_result if yt_result and yt_result is not False else None
        yt_success = yt_video_id is not None
        
        # --- Retry failed platform once more ---
        if not yt_success and fb_success:
            log.info(f"[{bot_name}] YouTube failed, retrying once more...")
            time.sleep(10)
            yt_result = upload_to_youtube_shorts(
                video_path=short["video_path"],
                title=short["title"],
                description=short["description"],
                credentials_dir=credentials_dir,
                publish_at=yt_iso
            )
            yt_video_id = yt_result if yt_result and yt_result is not False else None
            yt_success = yt_video_id is not None
            
        if not fb_success and yt_success:
            log.info(f"[{bot_name}] Facebook failed, retrying once more...")
            time.sleep(10)
            fb_result = upload_to_facebook_reels(
                video_path=short["video_path"],
                title=short["title"],
                description=short["description"],
                page_id=page_id,
                access_token=page_token,
                schedule_time=fb_unix
            )
            fb_video_id = fb_result if fb_result and fb_result is not False else None
            fb_success = fb_video_id is not None
        
        # --- Verify uploads ---
        yt_verified = False
        fb_verified = False
        
        if yt_success and yt_video_id:
            log.info(f"[{bot_name}] Verifying YouTube upload: {yt_video_id}...")
            yt_verify = verify_youtube_upload(yt_video_id, credentials_dir)
            yt_verified = yt_verify.get("verified", False)
            if not yt_verified:
                log.warning(f"[{bot_name}] YouTube verification warning: {yt_verify.get('reason', 'unknown')}")
        
        if fb_success and fb_video_id:
            log.info(f"[{bot_name}] Verifying Facebook upload: {fb_video_id}...")
            fb_verify = verify_facebook_upload(fb_video_id, page_token)
            fb_verified = fb_verify.get("verified", False)
            if not fb_verified:
                log.warning(f"[{bot_name}] Facebook verification warning: {fb_verify.get('reason', 'unknown')}")
        
        # --- Record upload history ---
        record_upload(bot_dir, {
            "title": short["title"],
            "yt_video_id": yt_video_id,
            "fb_video_id": fb_video_id,
            "yt_verified": yt_verified,
            "fb_verified": fb_verified,
            "yt_status": "success" if yt_success else "failed",
            "fb_status": "success" if fb_success else "failed",
            "scheduled_for": target_dt.isoformat(),
            "video_path": short["video_path"],
        })
        
        # Success = at least ONE platform uploaded successfully
        if yt_success or fb_success:
            platforms = []
            if yt_success: platforms.append(f"YouTube({yt_video_id})")
            if fb_success: platforms.append(f"Facebook({fb_video_id})")
            log.info(f"[{bot_name}] Upload SUCCESS on: {', '.join(platforms)} for {target_dt}!")
            success = True
        else:
            log.error(f"[{bot_name}] BOTH uploads failed for {short['title']}")
            
        # Only delete video file if at least one upload succeeded
        # Keep the file if both failed so it can be retried
        if success:
            try:
                if os.path.exists(short["video_path"]): os.remove(short["video_path"])
            except:
                pass
        else:
            log.warning(f"[{bot_name}] Keeping video file for retry: {short['video_path']}")

    if success:
        mark_as_processed(video["id"], history_file)
        update_calendar_slot(bot_dir, target_dt)
        return True
    return False

def start_daemon():
    log.info("Starting Multi-Bot 75-Day Rolling Buffer Factory...")
    
    while True:
        profiles = load_profiles()
        if not profiles:
            log.error("No profiles found in workspace/profiles/")
            time.sleep(300)
            continue
            
        all_bots_full = True
        
        for bot_name, data in profiles.items():
            bot_dir = data["path"]
            run_times = data["run_times"]
            
            target_dt = get_next_available_slot(bot_dir, run_times)
            
            now = datetime.datetime.now(IST)
            days_in_future = (target_dt - now).days
            
            if days_in_future >= 74:
                log.info(f"[{bot_name}] Queue is full! (Scheduled {days_in_future} days in advance). Sleeping this bot.")
                continue
                
            all_bots_full = False
            log.info(f"[{bot_name}] Slot available for {target_dt}. Starting generation...")
            
            try:
                run_profile(bot_name, bot_dir, target_dt)
            except Exception as e:
                log.error(f"[{bot_name}] Encountered fatal error: {e}")
                
            # Sleep a tiny bit between bots to avoid API spamming
            time.sleep(10)
            
        if all_bots_full:
            log.info("ALL BOTS ARE MAXED OUT AT 75 DAYS! Factory sleeping for 1 hour to await new profiles...")
            time.sleep(3600)

if __name__ == "__main__":
    start_daemon()
