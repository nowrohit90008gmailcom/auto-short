import os
import time
import requests
from utils.logger import get_logger

log = get_logger("facebook_publisher")

MAX_UPLOAD_RETRIES = 3


def upload_to_facebook_reels(video_path: str, title: str, description: str, page_id: str, access_token: str, schedule_time: int = None):
    """
    Uploads a local MP4 file to Facebook Reels using the 3-step Graph API process.
    Includes retry logic with exponential backoff on the binary upload step.
    
    Returns: video_id (str) on success, False on failure.
    """
    if not page_id or not access_token:
        log.warning("FB_PAGE_ID or FB_PAGE_TOKEN not provided. Skipping Facebook upload.")
        return False
        
    if not os.path.exists(video_path):
        log.error(f"Video file not found: {video_path}")
        return False
        
    file_size = os.path.getsize(video_path)
    file_size_mb = file_size / (1024 * 1024)
    log.info(f"Preparing Facebook Reels upload: '{title}' ({file_size_mb:.1f}MB)")
    
    # STEP 1: Initialize (with retry)
    log.info(f"Initializing Facebook Reels upload...")
    init_url = f"https://graph.facebook.com/v20.0/{page_id}/video_reels"
    init_payload = {
        'upload_phase': 'start',
        'access_token': access_token
    }
    
    video_id = None
    upload_url = None
    
    for attempt in range(1, MAX_UPLOAD_RETRIES + 1):
        try:
            init_res = requests.post(init_url, data=init_payload, timeout=30)
            init_res.raise_for_status()
            init_data = init_res.json()
            video_id = init_data.get('video_id')
            upload_url = init_data.get('upload_url')
            
            if not video_id or not upload_url:
                log.error(f"Failed to get video_id or upload_url. Response: {init_data}")
                return False
            break
        except Exception as e:
            err_det = ""
            if hasattr(e, "response") and e.response is not None:
                try:
                    err_det = e.response.text
                except Exception:
                    pass
            if attempt < MAX_UPLOAD_RETRIES:
                wait = 5 * (2 ** (attempt - 1))
                log.warning(f"Facebook init attempt {attempt}/{MAX_UPLOAD_RETRIES} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                log.error(f"Facebook Initialize Step failed after {MAX_UPLOAD_RETRIES} attempts: {e} - Details: {err_det}")
                return False
        
    # STEP 2: Upload Binary (with retry + progress logging)
    log.info(f"Uploading binary video data to Facebook (ID: {video_id}, {file_size_mb:.1f}MB)...")
    
    upload_success = False
    for attempt in range(1, MAX_UPLOAD_RETRIES + 1):
        try:
            with open(video_path, 'rb') as f:
                upload_headers = {
                    'Authorization': f'OAuth {access_token}',
                    'offset': '0',
                    'file_size': str(file_size),
                    'Content-Type': 'application/octet-stream'
                }
                upload_res = requests.post(upload_url, data=f, headers=upload_headers, timeout=900)
                upload_res.raise_for_status()
                log.info(f"Facebook binary upload complete (attempt {attempt})")
                upload_success = True
                break
        except Exception as e:
            err_det = ""
            if hasattr(e, "response") and e.response is not None:
                try:
                    err_det = e.response.text
                except Exception:
                    pass
            if attempt < MAX_UPLOAD_RETRIES:
                wait = 10 * (2 ** (attempt - 1))
                log.warning(f"Facebook upload attempt {attempt}/{MAX_UPLOAD_RETRIES} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                log.error(f"Facebook Upload Step failed after {MAX_UPLOAD_RETRIES} attempts: {e} - Details: {err_det}")
                return False
    
    if not upload_success:
        return False
        
    # STEP 3: Publish / Schedule (with retry)
    log.info("Publishing/Scheduling Reel to Facebook Page...")
    full_description = f"{title}\n\n{description}"
    
    publish_payload = {
        'access_token': access_token,
        'video_id': video_id,
        'upload_phase': 'finish',
        'description': full_description
    }
    
    if schedule_time:
        publish_payload['video_state'] = 'SCHEDULED'
        publish_payload['scheduled_publish_time'] = schedule_time
        log.info(f"Scheduling Facebook Reel for timestamp: {schedule_time}")
    else:
        publish_payload['video_state'] = 'PUBLISHED'
    
    for attempt in range(1, MAX_UPLOAD_RETRIES + 1):
        try:
            pub_res = requests.post(init_url, data=publish_payload, timeout=60)
            pub_res.raise_for_status()
            log.info(f"SUCCESS: Reel processed on Facebook! Video ID: {video_id}")
            return video_id  # Return the ID for verification
        except Exception as e:
            err_det = ""
            if hasattr(e, "response") and e.response is not None:
                try:
                    err_det = e.response.text
                except Exception:
                    pass
            if attempt < MAX_UPLOAD_RETRIES:
                wait = 5 * (2 ** (attempt - 1))
                log.warning(f"Facebook publish attempt {attempt}/{MAX_UPLOAD_RETRIES} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                log.error(f"Facebook Publish Step failed after {MAX_UPLOAD_RETRIES} attempts: {e} - Details: {err_det}")
                return False
