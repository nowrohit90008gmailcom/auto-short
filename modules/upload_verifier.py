"""
Upload verifier — confirms videos are actually live/processing on YouTube and Facebook
after the upload API returns success.
"""
import time
import requests
from pathlib import Path
from utils.logger import get_logger

log = get_logger("upload_verifier")


def verify_youtube_upload(video_id: str, credentials_dir: Path, max_retries: int = 3, wait_seconds: int = 30) -> dict:
    """
    Verify a YouTube upload by checking its processing status via the Data API.
    
    Returns: {"verified": bool, "status": str, "reason": str}
    """
    if not video_id:
        return {"verified": False, "status": "unknown", "reason": "No video_id provided"}
    
    try:
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        log.warning("Google API client not installed, skipping YouTube verification")
        return {"verified": False, "status": "skipped", "reason": "google-api-python-client not installed"}
    
    token_file = credentials_dir / "token.json"
    if not token_file.exists():
        return {"verified": False, "status": "skipped", "reason": "No token.json found"}
    
    try:
        creds = Credentials.from_authorized_user_file(
            str(token_file),
            ['https://www.googleapis.com/auth/youtube.readonly']
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
    except Exception as e:
        return {"verified": False, "status": "auth_error", "reason": str(e)}
    
    for attempt in range(1, max_retries + 1):
        try:
            youtube = build('youtube', 'v3', credentials=creds)
            response = youtube.videos().list(
                id=video_id,
                part='status,processingDetails'
            ).execute()
            
            items = response.get('items', [])
            if not items:
                if attempt < max_retries:
                    log.info(f"YouTube verification attempt {attempt}/{max_retries}: Video {video_id} not found yet, waiting {wait_seconds}s...")
                    time.sleep(wait_seconds)
                    continue
                return {"verified": False, "status": "not_found", "reason": f"Video {video_id} not found after {max_retries} attempts"}
            
            video = items[0]
            upload_status = video.get('status', {}).get('uploadStatus', 'unknown')
            privacy_status = video.get('status', {}).get('privacyStatus', 'unknown')
            processing = video.get('processingDetails', {})
            processing_status = processing.get('processingStatus', 'unknown')
            
            # 'uploaded' means it's still processing, 'processed' means done
            if upload_status in ('uploaded', 'processed'):
                log.info(f"YouTube upload VERIFIED: {video_id} (upload={upload_status}, privacy={privacy_status}, processing={processing_status})")
                return {
                    "verified": True,
                    "status": upload_status,
                    "reason": f"privacy={privacy_status}, processing={processing_status}"
                }
            elif upload_status == 'rejected':
                rejection_reason = video.get('status', {}).get('rejectionReason', 'unknown')
                log.error(f"YouTube upload REJECTED: {video_id} — Reason: {rejection_reason}")
                return {"verified": False, "status": "rejected", "reason": rejection_reason}
            elif upload_status == 'failed':
                failure_reason = video.get('status', {}).get('failureReason', 'unknown')
                log.error(f"YouTube upload FAILED: {video_id} — Reason: {failure_reason}")
                return {"verified": False, "status": "failed", "reason": failure_reason}
            else:
                if attempt < max_retries:
                    log.info(f"YouTube verification attempt {attempt}/{max_retries}: status={upload_status}, waiting {wait_seconds}s...")
                    time.sleep(wait_seconds)
                    continue
                return {"verified": False, "status": upload_status, "reason": f"Unexpected status after {max_retries} attempts"}
                
        except Exception as e:
            if attempt < max_retries:
                log.warning(f"YouTube verification attempt {attempt}/{max_retries} failed: {e}")
                time.sleep(wait_seconds)
                continue
            return {"verified": False, "status": "error", "reason": str(e)}
    
    return {"verified": False, "status": "timeout", "reason": "Max retries exceeded"}


def verify_facebook_upload(video_id: str, access_token: str, max_retries: int = 3, wait_seconds: int = 20) -> dict:
    """
    Verify a Facebook Reel upload by checking its status via the Graph API.
    
    Returns: {"verified": bool, "status": str, "reason": str}
    """
    if not video_id or not access_token:
        return {"verified": False, "status": "skipped", "reason": "No video_id or access_token"}
    
    for attempt in range(1, max_retries + 1):
        try:
            url = f"https://graph.facebook.com/v20.0/{video_id}"
            params = {
                "fields": "status,published,title",
                "access_token": access_token
            }
            r = requests.get(url, params=params, timeout=15)
            
            if r.status_code == 200:
                data = r.json()
                status = data.get("status", {})
                video_status = status.get("video_status", "unknown") if isinstance(status, dict) else str(status)
                published = data.get("published", False)
                
                if video_status in ("ready", "processing", "complete") or published:
                    log.info(f"Facebook upload VERIFIED: {video_id} (status={video_status}, published={published})")
                    return {"verified": True, "status": video_status, "reason": f"published={published}"}
                elif video_status == "error":
                    log.error(f"Facebook upload FAILED: {video_id} — status=error")
                    return {"verified": False, "status": "error", "reason": "Facebook reported video error"}
                else:
                    if attempt < max_retries:
                        log.info(f"Facebook verification attempt {attempt}/{max_retries}: status={video_status}, waiting {wait_seconds}s...")
                        time.sleep(wait_seconds)
                        continue
                    # After retries, if status isn't error, consider it verified (still processing)
                    log.info(f"Facebook upload likely OK: {video_id} (status={video_status})")
                    return {"verified": True, "status": video_status, "reason": "Still processing but not error"}
            else:
                if attempt < max_retries:
                    log.warning(f"Facebook verification attempt {attempt}/{max_retries}: HTTP {r.status_code}")
                    time.sleep(wait_seconds)
                    continue
                return {"verified": False, "status": f"http_{r.status_code}", "reason": r.text[:300]}
                
        except Exception as e:
            if attempt < max_retries:
                log.warning(f"Facebook verification attempt {attempt}/{max_retries} failed: {e}")
                time.sleep(wait_seconds)
                continue
            return {"verified": False, "status": "error", "reason": str(e)}
    
    return {"verified": False, "status": "timeout", "reason": "Max retries exceeded"}
