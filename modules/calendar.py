import json
import datetime
from pathlib import Path
import pytz

IST = pytz.timezone('Asia/Kolkata')

def get_next_available_slot(bot_dir: Path, videos_per_day: int = 2) -> datetime.datetime:
    """
    Reads the calendar state for the bot.
    If no state exists, starts scheduling from Tomorrow at 8:00 AM.
    If state exists, increments by (24 / videos_per_day) hours.
    Returns the exact datetime.datetime (IST).
    """
    state_file = bot_dir / "calendar_state.json"
    
    interval_hours = 24 / videos_per_day
    
    if not state_file.exists():
        # Start tomorrow at 8:00 AM IST
        now = datetime.datetime.now(IST)
        tomorrow = now + datetime.timedelta(days=1)
        next_slot = tomorrow.replace(hour=8, minute=0, second=0, microsecond=0)
    else:
        with open(state_file, "r") as f:
            data = json.load(f)
            last_dt_iso = data.get("last_scheduled_time")
            last_dt = datetime.datetime.fromisoformat(last_dt_iso)
            
        next_slot = last_dt + datetime.timedelta(hours=interval_hours)
        
    # Prevent scheduling backwards in time (if bot was offline for a long time)
    if next_slot < datetime.datetime.now(IST) + datetime.timedelta(hours=1):
        now = datetime.datetime.now(IST)
        tomorrow = now + datetime.timedelta(days=1)
        next_slot = tomorrow.replace(hour=8, minute=0, second=0, microsecond=0)
        
    return next_slot

def update_calendar_slot(bot_dir: Path, booked_dt: datetime.datetime):
    """
    Saves the newly booked slot to the state file.
    """
    state_file = bot_dir / "calendar_state.json"
    data = {
        "last_scheduled_time": booked_dt.isoformat()
    }
    with open(state_file, "w") as f:
        json.dump(data, f, indent=4)
