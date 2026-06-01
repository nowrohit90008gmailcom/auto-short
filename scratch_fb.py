import urllib.request
import json
import os
from pathlib import Path

token = "EAAXxR6hn4E4BRgsA0HotTZCDaSnWnw334K3uvHVEqQcvKrDa8cwZB8NH8KEdmABzmjl1ZCmHV5yNpLbLokje7ROTsY4ZA2FXEg2n3YqgJbF1Bq9dDCOemoR4NPCYcsnN1JRSnnqTcstR7iqkMY1SwiIIU1iAQSZBlJyZAlL6xtbIRaZCxo4ndfoInEBYoWB0mcV"

url = f'https://graph.facebook.com/v19.0/me/accounts?access_token={token}'
try:
    req = urllib.request.urlopen(url)
    res = json.loads(req.read().decode())
    pages = res.get('data', [])
    
    for page in pages:
        if "Bollywood" in page['name']:
            env_path = Path("workspace/profiles/bot2/.env")
            with open(env_path, "w") as f:
                f.write(f"FB_PAGE_ID={page['id']}\n")
                f.write(f"FB_PAGE_TOKEN={page['access_token']}\n")
            print("Successfully created bot2/.env for Bollywood Clips!")
            
        elif "South Movie" in page['name']:
            env_path = Path("workspace/profiles/bot3/.env")
            with open(env_path, "w") as f:
                f.write(f"FB_PAGE_ID={page['id']}\n")
                f.write(f"FB_PAGE_TOKEN={page['access_token']}\n")
            print("Successfully created bot3/.env for South Movie!")
except Exception as e:
    print(f"Failed: {e}")
