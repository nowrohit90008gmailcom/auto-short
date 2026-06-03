import os
import time
from pathlib import Path
from utils.logger import get_logger

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False

log = get_logger("youtube_publisher")

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

# YouTube Shorts must be under 60 seconds and 256 MB
MAX_FILE_SIZE_MB = 256


def _refresh_credentials(token_file: Path, client_secrets_file: Path):
    """Load and refresh YouTube OAuth2 credentials with retry."""
    creds = None
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        except Exception:
            pass

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Retry token refresh up to 2 times
            for attempt in range(1, 3):
                try:
                    creds.refresh(Request())
                    break
                except Exception as e:
                    if attempt < 2:
                        log.warning(f"Token refresh attempt {attempt} failed: {e}. Retrying in 5s...")
                        time.sleep(5)
                    else:
                        log.error(f"Failed to refresh YouTube token after 2 attempts: {e}")
                        return None
        else:
            if not client_secrets_file.exists():
                log.error("Cannot authenticate: client_secrets.json missing.")
                return None
            
            log.info("Starting local server for YouTube authentication. PLEASE CHECK YOUR BROWSER!")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                log.error(f"YouTube Authentication failed: {e}")
                return None
                
    # Save the credentials for the next run
    try:
        with open(token_file, 'w') as token:
            token.write(creds.to_json())
    except Exception:
        pass
    
    return creds


def upload_to_youtube_shorts(video_path: str, title: str, description: str, credentials_dir: Path, privacy_status: str = "public", publish_at: str = None):
    """
    Uploads a short to YouTube using OAuth2 with chunked resumable uploads and retry logic.
    
    Returns: video_id (str) on success, False on failure.
    """
    if not HAS_GOOGLE_API:
        log.error("google-api-python-client is not installed. Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
        return False

    # Validate file exists and size
    if not os.path.exists(video_path):
        log.error(f"Video file not found: {video_path}")
        return False
    
    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        log.error(f"Video file too large: {file_size_mb:.1f}MB (max {MAX_FILE_SIZE_MB}MB for Shorts)")
        return False
    
    log.info(f"Preparing YouTube upload: {title} ({file_size_mb:.1f}MB)")

    credentials_dir.mkdir(parents=True, exist_ok=True)
    client_secrets_file = credentials_dir / "client_secrets.json"
    token_file = credentials_dir / "token.json"
    
    if not client_secrets_file.exists() and not token_file.exists():
        log.warning(f"YouTube Upload skipped: {client_secrets_file} not found.")
        return False

    creds = _refresh_credentials(token_file, client_secrets_file)
    if not creds:
        return False

    log.info(f"Uploading to YouTube Shorts: {title}...")
    try:
        youtube = build('youtube', 'v3', credentials=creds)
        
        # Must include #shorts in description or title to ensure it goes to the Shorts shelf
        full_desc = f"{description}\n\n#shorts #podcast"
        
        if publish_at:
            privacy_status = "private"
            log.info(f"Scheduling YouTube Short for: {publish_at}")
        
        status_obj = {
            'privacyStatus': privacy_status,
            'selfDeclaredMadeForKids': False,
        }
        
        if publish_at:
            status_obj['publishAt'] = publish_at
            
        body = {
            'snippet': {
                'title': title[:100],
                'description': full_desc,
                'categoryId': '24',  # Entertainment
            },
            'status': status_obj
        }
        
        # Use 10MB chunks for resumable upload (instead of -1 which uploads as single blob)
        media = MediaFileUpload(video_path, chunksize=10 * 1024 * 1024, resumable=True)
        
        request = youtube.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=media
        )
        
        response = None
        max_chunk_retries = 3
        
        while response is None:
            chunk_error = None
            for retry in range(1, max_chunk_retries + 1):
                try:
                    status, response = request.next_chunk()
                    if status:
                        log.info(f"YouTube Uploading... {int(status.progress() * 100)}%")
                    chunk_error = None
                    break  # Chunk succeeded
                except HttpError as e:
                    if e.resp.status in (500, 502, 503, 504) and retry < max_chunk_retries:
                        wait_time = 5 * (2 ** (retry - 1))  # 5s, 10s, 20s
                        log.warning(f"YouTube upload chunk retry {retry}/{max_chunk_retries} (HTTP {e.resp.status}). Waiting {wait_time}s...")
                        time.sleep(wait_time)
                        chunk_error = e
                    else:
                        raise  # Non-retryable HTTP error or max retries exceeded
                except Exception as e:
                    if retry < max_chunk_retries:
                        wait_time = 5 * (2 ** (retry - 1))
                        log.warning(f"YouTube upload chunk retry {retry}/{max_chunk_retries}: {e}. Waiting {wait_time}s...")
                        time.sleep(wait_time)
                        chunk_error = e
                    else:
                        raise
            
            if chunk_error and response is None:
                raise chunk_error

        video_id = response.get('id')
        log.info(f"SUCCESS: YouTube Short uploaded! Video ID: {video_id}")
        return video_id  # Return the ID for verification
        
    except Exception as e:
        error_details = ""
        if hasattr(e, "content"):
            error_details = e.content
        elif hasattr(e, "resp"):
            error_details = str(e.resp)
        log.error(f"YouTube Upload Step failed: {e} - Details: {error_details}")
        return False
