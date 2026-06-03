import os
import json
import time
from pathlib import Path
from flask import Flask, render_template, jsonify, request

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

def get_all_bots_info():
    bots = []
    profiles_dir = Path("workspace") / "profiles"
    if profiles_dir.exists():
        # Sort folders to display bot1, bot2, bot3 in order
        for bot_dir in sorted(profiles_dir.iterdir()):
            if bot_dir.is_dir():
                count = 0
                hist_file = bot_dir / "processed_history.json"
                if hist_file.exists():
                    try:
                        with open(hist_file, "r") as f:
                            count = len(json.load(f))
                    except:
                        pass
                        
                run_times = []
                config_file = bot_dir / "config.json"
                if config_file.exists():
                    try:
                        with open(config_file, "r") as f:
                            run_times = json.load(f).get("run_times", [])
                    except:
                        pass
                        
                bots.append({
                    "name": bot_dir.name.upper(),
                    "processed": count,
                    "schedule": ", ".join(run_times) if run_times else "Unscheduled"
                })
    return bots

def get_bot_status(last_logs: str) -> str:
    if not last_logs.strip():
        return "Offline"
    last_line = last_logs.strip().split("\n")[-1]
    
    if "Factory sleeping" in last_line or "Queue is full" in last_line:
        return "Sleeping (Queue Full)"
    elif "Sleeping this bot" in last_line:
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
    current_status = get_bot_status(logs)
    bots = get_all_bots_info()
    
    # Calculate global totals
    total_processed = sum(b["processed"] for b in bots)
    
    # Extract errors separately
    error_logs = []
    for line in logs.split('\n'):
        line_lower = line.lower()
        if 'error' in line_lower or 'traceback' in line_lower or 'failed' in line_lower or 'exception' in line_lower:
            # Skip false positives if needed
            if 'http error' in line_lower or 'modulenotfound' in line_lower or 'traceback' in line_lower or 'error' in line_lower:
                 error_logs.append(line.strip())
    
    # Keep only the last 20 errors to prevent flooding the UI
    error_logs = error_logs[-20:]
    
    return jsonify({
        "status": current_status,
        "total_processed": total_processed,
        "bots": bots,
        "logs": logs,
        "errors": error_logs
    })

@app.route("/api/cookies", methods=["POST"])
def update_cookies():
    data = request.json
    cookies_content = data.get("cookies", "")
    if not cookies_content.strip():
        return jsonify({"success": False, "error": "Empty cookies content provided."})
    
    try:
        # Sanitize text area formatting to strictly match Netscape HTTP format
        clean_cookies = cookies_content.replace('\r\n', '\n').strip()
        if not clean_cookies.startswith("# Netscape HTTP Cookie File"):
            clean_cookies = "# Netscape HTTP Cookie File\n" + clean_cookies
            
        cookies_file = WORKSPACE / "cookies.txt"
        with open(cookies_file, "w", encoding="utf-8", newline='\n') as f:
            f.write(clean_cookies + "\n")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == "__main__":
    # Bind to 0.0.0.0 to allow external access from phone
    app.run(host="0.0.0.0", port=5000, debug=False)
