import json
import datetime
from pathlib import Path
import pytz

IST = pytz.timezone('Asia/Kolkata')

def get_next_available_slot(bot_dir: Path, run_times: list) -> datetime.datetime:
    """
    Reads the calendar state for the bot.
    If no state exists, starts scheduling on Tomorrow using the first run_time.
    If state exists, picks the next chronological run_time, rolling over to the next day if necessary.
    Returns the exact datetime.datetime (IST).
    """
    state_file = bot_dir / "calendar_state.json"
    now_ist = datetime.datetime.now(IST)
    
    # Sort run_times chronologically
    parsed_times = []
    for t_str in run_times:
        h, m = map(int, t_str.split(":"))
        parsed_times.append((h, m))
    parsed_times.sort()
    
    if not state_file.exists():
        for h, m in parsed_times:
            candidate = now_ist.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate > now_ist + datetime.timedelta(hours=1):
                return candidate
        # If all of today's slots have passed, start tomorrow
        tomorrow = now_ist + datetime.timedelta(days=1)
        return tomorrow.replace(hour=parsed_times[0][0], minute=parsed_times[0][1], second=0, microsecond=0)
        
    with open(state_file, "r") as f:
        data = json.load(f)
        last_dt_iso = data.get("last_scheduled_time")
        last_dt = datetime.datetime.fromisoformat(last_dt_iso)
        
    # Find the next slot after last_dt
    next_slot = None
    for h, m in parsed_times:
        if h > last_dt.hour or (h == last_dt.hour and m > last_dt.minute):
            next_slot = last_dt.replace(hour=h, minute=m, second=0, microsecond=0)
            break
            
    if not next_slot:
        # Roll over to next day
        tomorrow = last_dt + datetime.timedelta(days=1)
        next_slot = tomorrow.replace(hour=parsed_times[0][0], minute=parsed_times[0][1], second=0, microsecond=0)
        
    # Prevent scheduling backwards in time (or too close to current time)
    if next_slot < now_ist + datetime.timedelta(minutes=30):
        # Look for the very next slot from RIGHT NOW
        for _ in range(7):
            for h, m in parsed_times:
                candidate = now_ist.replace(hour=h, minute=m, second=0, microsecond=0)
                if candidate > now_ist + datetime.timedelta(hours=1):
                    return candidate
            now_ist = now_ist + datetime.timedelta(days=1)
            now_ist = now_ist.replace(hour=0, minute=0, second=0)
            
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
