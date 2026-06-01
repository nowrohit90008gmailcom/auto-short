import os
import argparse
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Please run: pip install google-auth-oauthlib")
    exit(1)

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

def authenticate_profile(bot_name: str):
    credentials_dir = Path("workspace") / "profiles" / bot_name / "credentials"
    client_secrets_file = credentials_dir / "client_secrets.json"
    token_file = credentials_dir / "token.json"

    if not credentials_dir.exists():
        credentials_dir.mkdir(parents=True, exist_ok=True)

    if not client_secrets_file.exists():
        print(f"[ERROR] You must place your client_secrets.json file inside {client_secrets_file} first!")
        return

    print(f"=== Authenticating YouTube Channel for {bot_name.upper()} ===")
    print("A web browser will open. Please log into the specific Google Email account you want this bot to post to.")
    
    flow = InstalledAppFlow.from_client_secrets_file(
        client_secrets_file, SCOPES
    )
    
    # This opens the browser on Windows
    creds = flow.run_local_server(port=0)
    
    # Save the credentials
    with open(token_file, 'w') as f:
        f.write(creds.to_json())
        
    print(f"[SUCCESS] Successfully generated token.json for {bot_name}! The bot is now permanently linked to that email account.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate YouTube token.json for a specific bot profile.")
    parser.add_argument("bot_name", help="The name of the bot profile (e.g., bot2, bot3)")
    args = parser.parse_args()
    
    authenticate_profile(args.bot_name)
