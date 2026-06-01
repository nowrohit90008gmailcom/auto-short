import os
import json
import time
from pathlib import Path
from flask import Flask, render_template, jsonify

app = Flask(__name__)

WORKSPACE = Path("workspace")
HISTORY_FILE = WORKSPACE / "processed_history.json"
LOG_FILE = Path("daemon_output.log")

def get_last_n_lines(file_path: Path, n: int = 50) -> str:
    if not file_path.exists():
        return "Log file not found. Is the daemon running?"
    try:
        # Simple read for smallish log files; for huge logs, seek from end is better
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return "".join(lines[-n:])
    except Exception as e:
        return f"Error reading logs: {e}"

def get_processed_count() -> int:
    profiles_dir = Path("workspace") / "profiles"
    if not profiles_dir.exists():
        return 0
    total = 0
    for bot_dir in profiles_dir.iterdir():
        if bot_dir.is_dir():
            hist_file = bot_dir / "processed_history.json"
            if hist_file.exists():
                try:
                    with open(hist_file, "r") as f:
                        data = json.load(f)
                        total += len(data)
                except Exception:
                    pass
    return total

def get_bot_status(last_logs: str) -> str:
    if not last_logs.strip():
        return "Offline"
    last_line = last_logs.strip().split("\n")[-1]
    
    if "Sleeping for" in last_line:
        return "Sleeping (Idle)"
    elif "Fatal error" in last_line or "Traceback" in last_line:
        return "Error / Offline"
    else:
        # Check if log was modified recently
        if LOG_FILE.exists():
            mod_time = os.path.getmtime(LOG_FILE)
            if time.time() - mod_time < 1800: # 30 minutes
                return "Active (Processing)"
        return "Offline / Unknown"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def status():
    logs = get_last_n_lines(LOG_FILE, 100)
    count = get_processed_count()
    current_status = get_bot_status(logs)
    
    return jsonify({
        "status": current_status,
        "processed_count": count,
        "logs": logs
    })

if __name__ == "__main__":
    # Bind to 0.0.0.0 to allow external access from phone
    app.run(host="0.0.0.0", port=5000, debug=False)
