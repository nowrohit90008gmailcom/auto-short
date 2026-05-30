"""
Social media uploader — YouTube Shorts + Facebook Reels.
YouTube: OAuth2 resumable upload via Data API v3.
Facebook: Graph API video upload.
"""
import os
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

import utils.dns_bypass  # noqa
from utils.logger import get_logger

load_dotenv()
log = get_logger("uploader")

# YouTube credentials
YT_CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID", "")
YT_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
YT_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN", "")

# Facebook credentials
FB_PAGE_ID      = os.getenv("FACEBOOK_PAGE_ID", "")
FB_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN", "")


# ── YouTube ─────────────────────────────────────────────────────────

def _get_youtube_access_token() -> str:
    """Exchange refresh token for a fresh access token."""
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": YT_CLIENT_ID,
        "client_secret": YT_CLIENT_SECRET,
        "refresh_token": YT_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def upload_youtube(video_path: str, title: str, description: str,
                   tags: list = None) -> dict:
    """
    Upload a video as a YouTube Short.
    
    Returns: {"success": bool, "video_id": str, "url": str, "error": str}
    """
    if not all([YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN]):
        return {"success": False, "error": "YouTube credentials not configured"}
    
    try:
        access_token = _get_youtube_access_token()
    except Exception as e:
        return {"success": False, "error": f"Token refresh failed: {e}"}
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    
    # Step 1: Initialize resumable upload
    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": (tags or [])[:30],
            "categoryId": "24",  # Entertainment
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    
    init_url = ("https://www.googleapis.com/upload/youtube/v3/videos"
                "?uploadType=resumable&part=snippet,status")
    
    r = requests.post(init_url, headers=headers, json=metadata, timeout=30)
    
    if r.status_code not in (200, 308):
        return {"success": False, "error": f"Init failed: {r.status_code} {r.text[:300]}"}
    
    upload_url = r.headers.get("Location")
    if not upload_url:
        return {"success": False, "error": "No upload URL returned"}
    
    # Step 2: Upload video file
    file_size = os.path.getsize(video_path)
    log.info(f"Uploading to YouTube: {title} ({file_size / 1024 / 1024:.1f}MB)")
    
    with open(video_path, "rb") as f:
        r = requests.put(
            upload_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "video/mp4",
                "Content-Length": str(file_size),
            },
            data=f,
            timeout=600,
        )
    
    if r.status_code in (200, 201):
        video_id = r.json().get("id", "")
        url = f"https://youtube.com/shorts/{video_id}"
        log.info(f"YouTube upload success: {url}")
        return {"success": True, "video_id": video_id, "url": url, "error": ""}
    else:
        return {"success": False, "error": f"Upload failed: {r.status_code} {r.text[:300]}"}


# ── Facebook ────────────────────────────────────────────────────────

def upload_facebook(video_path: str, title: str, description: str) -> dict:
    """
    Upload a video as a Facebook Reel.
    
    Returns: {"success": bool, "post_id": str, "error": str}
    """
    if not all([FB_PAGE_ID, FB_ACCESS_TOKEN]):
        return {"success": False, "error": "Facebook credentials not configured"}
    
    file_size = os.path.getsize(video_path)
    log.info(f"Uploading to Facebook: {title} ({file_size / 1024 / 1024:.1f}MB)")
    
    try:
        # Step 1: Initialize upload
        init_url = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/video_reels"
        r = requests.post(init_url, data={
            "upload_phase": "start",
            "access_token": FB_ACCESS_TOKEN,
        }, timeout=30)
        r.raise_for_status()
        video_id = r.json().get("video_id")
        
        if not video_id:
            return {"success": False, "error": "No video_id from Facebook init"}
        
        # Step 2: Upload video data
        upload_url = f"https://rupload.facebook.com/video-upload/v18.0/{video_id}"
        with open(video_path, "rb") as f:
            r = requests.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {FB_ACCESS_TOKEN}",
                    "offset": "0",
                    "file_size": str(file_size),
                },
                data=f,
                timeout=600,
            )
        r.raise_for_status()
        
        # Step 3: Publish
        publish_url = f"https://graph.facebook.com/v18.0/{FB_PAGE_ID}/video_reels"
        r = requests.post(publish_url, data={
            "access_token": FB_ACCESS_TOKEN,
            "video_id": video_id,
            "upload_phase": "finish",
            "video_state": "PUBLISHED",
            "description": f"{title}\n\n{description}",
        }, timeout=30)
        r.raise_for_status()
        
        post_id = r.json().get("id", video_id)
        log.info(f"Facebook upload success: post_id={post_id}")
        return {"success": True, "post_id": post_id, "error": ""}
        
    except Exception as e:
        return {"success": False, "error": str(e)}
