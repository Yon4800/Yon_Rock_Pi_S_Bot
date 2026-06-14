import os
import json
import tempfile
import requests
from datetime import datetime, timedelta
import random

ECONOMY_STATE_PATH = os.getenv("ECONOMY_STATE_PATH")

def get_http_headers():
    header_key = os.getenv("ECONOMY_HTTP_HEADER_KEY")
    header_val = os.getenv("ECONOMY_HTTP_HEADER_VALUE")
    headers = {"Content-Type": "application/json"}
    if header_key and header_val:
        headers[header_key] = header_val
    return headers

def get_economy_filepath():
    path = ECONOMY_STATE_PATH
    if path:
        if path.startswith(("http://", "https://")):
            return path
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(os.path.dirname(__file__), path))
    
    # Default: parent dir (c:\kaihatsu\Misskey\shared_economy.json)
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.abspath(os.path.join(parent_dir, "shared_economy.json"))

def update_exchange_rates(data, now):
    for coin in ["CBC", "OGC"]:
        if "rates" not in data:
            data["rates"] = {}
        if coin not in data["rates"]:
            data["rates"][coin] = {"current": 100.0, "previous": 100.0}
        
        current = data["rates"][coin]["current"]
        if random.random() < 0.20:
            change = random.uniform(0.5, 4.0)
        else:
            change = random.uniform(0.1, 0.5)
            
        if random.random() < 0.5:
            change = -change
            
        new_rate = current + change
        new_rate = max(10.0, min(500.0, round(new_rate, 2)))
        
        data["rates"][coin]["previous"] = current
        data["rates"][coin]["current"] = new_rate
        
    data["last_rate_update"] = now.isoformat()

def check_and_update_rates_on_load(data):
    now = datetime.now()
    try:
        last_update = datetime.fromisoformat(data["last_rate_update"])
    except Exception:
        last_update = now - timedelta(days=1)
        
    interval = data.get("rate_update_interval_seconds", 60)
    if (now - last_update).total_seconds() >= interval:
        update_exchange_rates(data, now)
        return True
    return False

def load_economy():
    filepath = get_economy_filepath()
    now_str = datetime.now().isoformat()
    
    default_state = {
        "salary_cooldown_seconds": 86400,
        "rate_update_interval_seconds": 60,
        "rates": {
            "CBC": {"current": 100.0, "previous": 100.0},
            "OGC": {"current": 100.0, "previous": 100.0}
        },
        "last_rate_update": now_str,
        "bots": {},
        "users": {}
    }
    
    data = default_state
    is_new = False
    
    if filepath.startswith(("http://", "https://")):
        try:
            res = requests.get(filepath, headers=get_http_headers(), timeout=5)
            if res.status_code == 200:
                loaded = res.json()
                if isinstance(loaded, dict):
                    if "record" in loaded:
                        data = loaded["record"]
                    else:
                        data = loaded
            else:
                is_new = True
        except Exception as e:
            print(f"Error loading remote economy state: {e}")
            is_new = True
    else:
        is_new = not os.path.exists(filepath)
        if not is_new:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data = loaded
            except Exception as e:
                print(f"Error loading economy state: {e}")
                is_new = True
            
    if "salary_cooldown_seconds" not in data:
        data["salary_cooldown_seconds"] = default_state["salary_cooldown_seconds"]
    if "rate_update_interval_seconds" not in data:
        data["rate_update_interval_seconds"] = default_state["rate_update_interval_seconds"]
        
    if "rates" not in data:
        data["rates"] = default_state["rates"]
    for coin in ["CBC", "OGC"]:
        if coin not in data["rates"]:
            data["rates"][coin] = {"current": 100.0, "previous": 100.0}
        elif not isinstance(data["rates"][coin], dict):
            data["rates"][coin] = {"current": float(data["rates"][coin]), "previous": float(data["rates"][coin])}
            
    if "last_rate_update" not in data:
        data["last_rate_update"] = now_str
    if "bots" not in data:
        data["bots"] = {}
    if "users" not in data:
        data["users"] = {}
        
    updated = check_and_update_rates_on_load(data)
    if updated or is_new:
        save_economy(data)
        
    return data

def save_economy(data):
    filepath = get_economy_filepath()
    if filepath.startswith(("http://", "https://")):
        try:
            res = requests.put(filepath, json=data, headers=get_http_headers(), timeout=5)
            if res.status_code not in (200, 201, 204):
                print(f"Failed to save remote economy state: {res.status_code}")
        except Exception as e:
            print(f"Error saving remote economy state: {e}")
    else:
        dir_name = os.path.dirname(filepath)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        try:
            with tempfile.NamedTemporaryFile('w', dir=dir_name or ".", delete=False, encoding='utf-8') as tf:
                json.dump(data, tf, indent=2, ensure_ascii=False)
                temp_name = tf.name
            os.replace(temp_name, filepath)
        except Exception as e:
            print(f"Error saving economy state: {e}")

def get_user_state(data, user_id, username=None, display_name=None):
    if "users" not in data:
        data["users"] = {}
    if user_id not in data["users"]:
        data["users"][user_id] = {
            "balance_sbc": 100.0,  # Default 100 $SBC
            "balance_cbc": 0.0,
            "balance_ogc": 0.0,
            "inventory": []
        }
    user_data = data["users"][user_id]
    if "balance_sbc" not in user_data:
        user_data["balance_sbc"] = 100.0
    if "balance_cbc" not in user_data:
        user_data["balance_cbc"] = 0.0
    if "balance_ogc" not in user_data:
        user_data["balance_ogc"] = 0.0
    if "inventory" not in user_data:
        user_data["inventory"] = []
    
    if username:
        user_data["username"] = username
    if display_name:
        user_data["display_name"] = display_name
    return user_data
