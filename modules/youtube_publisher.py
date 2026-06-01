import os
from pathlib import Path
from utils.logger import get_logger

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False

log = get_logger("youtube_publisher")

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

def upload_to_youtube_shorts(video_path: str, title: str, description: str, credentials_dir: Path, privacy_status: str = "public", publish_at: str = None) -> bool:
    """
    Uploads a short to YouTube using OAuth2.
    Requires client_secrets.json in the provided credentials_dir.
    Generates token.json upon first authentication.
    If publish_at (ISO 8601 string) is provided, privacyStatus is forced to private and it is scheduled.
    """
    if not HAS_GOOGLE_API:
        log.error("google-api-python-client is not installed. Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
        return False

    credentials_dir.mkdir(parents=True, exist_ok=True)
    
    client_secrets_file = credentials_dir / "client_secrets.json"
    token_file = credentials_dir / "token.json"
    
    if not client_secrets_file.exists() and not token_file.exists():
        log.warning(f"YouTube Upload skipped: {client_secrets_file} not found.")
        log.warning("Please download your OAuth 2.0 Client ID JSON from Google Cloud Console and place it there.")
        return False

    creds = None
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        except Exception:
            pass

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                log.error(f"Failed to refresh YouTube token: {e}")
                return False
        else:
            if not client_secrets_file.exists():
                log.error("Cannot authenticate: client_secrets.json missing.")
                return False
            
            log.info("Starting local server for YouTube authentication. PLEASE CHECK YOUR BROWSER!")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                log.error(f"YouTube Authentication failed: {e}")
                return False
                
        # Save the credentials for the next run
        with open(token_file, 'w') as token:
            token.write(creds.to_json())

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
                'categoryId': '24', # Entertainment
            },
            'status': status_obj
        }
        
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        
        request = youtube.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.info(f"YouTube Uploading... {int(status.progress() * 100)}%")

        video_id = response.get('id')
        log.info(f"SUCCESS: YouTube Short published! Video ID: {video_id}")
        return True
        
    except Exception as e:
        log.error(f"YouTube Upload Step failed: {e}")
        return False
