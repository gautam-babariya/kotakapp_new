import os
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("MONGODB_DB_NAME", "nifty_options_db")

try:
    client = MongoClient(MONGO_URI)
    client.admin.command('ping')
    db = client[DB_NAME]
    print("[DB Success] Connected to MongoDB.")
except Exception as e:
    print(f"[DB Error] Connection failed: {e}")
    db = None

# Collections
trades_collection = db["trades"] if db is not None else None
config_collection = db["bot_config"] if db is not None else None

def get_config():
    """Fetches bot configuration from DB or creates default if missing."""
    default_config = {
        "entry_time": "09:20:50",
        "exit_time": "15:05:00",
        "lot_size": 25,
        "premium_filter": 25.0,
        "sl_points": 10.0
    }
    if config_collection is None:
        return default_config
    
    cfg = config_collection.find_one({"_id": "settings"})
    if not cfg:
        config_collection.insert_one({"_id": "settings", **default_config})
        return default_config
    return cfg

def update_config(new_values):
    """Updates bot configuration settings in DB."""
    if config_collection is not None:
        config_collection.update_one(
            {"_id": "settings"},
            {"$set": new_values},
            upsert=True
        )

def log_trade(ce_data, pe_data, lot_size, expiry):
    """
    Logs a new strangle trade incorporating all required fields:
    - Symbols (CE & PE)
    - Entry Price & Exit Price
    - Trade Open status
    - Lot Size
    - Entry Time & Exit Time
    """
    if trades_collection is not None:
        now = datetime.now(timezone.utc)
        trade_doc = {
            "status": "OPEN",
            "trade_open": True,
            "expiry": expiry,
            "ce": {
                "symbol": ce_data.get("Symbol"),
                "token": ce_data.get("Token"),
                "entry_price": ce_data.get("LTP"),
                "exit_price": None,
                "lot_size": lot_size,
                "entry_time": now,
                "exit_time": None,
                "status": "ACTIVE"
            },
            "pe": {
                "symbol": pe_data.get("Symbol"),
                "token": pe_data.get("Token"),
                "entry_price": pe_data.get("LTP"),
                "exit_price": None,
                "lot_size": lot_size,
                "entry_time": now,
                "exit_time": None,
                "status": "ACTIVE"
            },
            "timestamp": now
        }
        result = trades_collection.insert_one(trade_doc)
        return result.inserted_id
    return None

def get_latest_trade():
    """Fetches the most recent trade document from DB."""
    if trades_collection is not None:
        return trades_collection.find_one(sort=[("_id", -1)])
    return None