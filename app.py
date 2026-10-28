from flask import Flask, jsonify,render_template
from neo_api_client import NeoAPI
from getstrick import get_strangle_symbols
from login import get_authenticated_client
from config import trades_collection,config_collection
from placeorder import placeorder
import asyncio
import threading
import time
import pytz
import pandas_market_calendars as mcal
from datetime import datetime, time as dtime
from websocket import live_feed_data

import asyncio

import websocket
import logic

app = Flask(__name__)
client = get_authenticated_client()
hard_quantity = "65"  # Hardcoded quantity for all orders
# Global flag to track if positions were already closed manually
MANUAL_CLOSE_DONE = False
# Create a global or application-scoped stop event
stop_monitoring_event = threading.Event()

@app.route("/")
def home():
    return render_template("index.html")

@app.route('/api/manual-close', methods=['POST'])
def api_manual_close():
    """
    API endpoint triggered by the frontend 'Manual Close' button.
    Calls your manual_close_trade function and returns JSON status.
    """
    global client, hard_quantity
    
    try:
        # Call the manual close method we created earlier
        result = manual_close_trade()
        
        if result.get("status") == "success":
            return jsonify({"status": "success", "message": "All positions closed and services stopped successfully."}), 200
        else:
            return jsonify({"status": "error", "message": result.get("message", "Unknown error occurred.")}), 400
            
    except Exception as e:
        print(f"❌ [API] Error handling manual close request: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    
# @app.route("/login", methods=["GET"])
def login():
    client = get_authenticated_client()
    return client

# @app.route('/get-symbols', methods=['GET'])
def fetch_symbols_route():
    result = get_strangle_symbols()
    
    if result["status"] == "error":
        return {"error": result["message"]}, 400
        
    if result.get("status") == "success":
        ce = result["ce"]
        pe = result["pe"]
        expiry = result["expiry"]
        
        # Construct the trade document
        trade_document = {
            "expiry": expiry,
            "created_at": datetime.now(),
            "strategy": "strangle",
            "ce": {
                "token": str(ce["Token"]),
                "symbol": ce["Symbol"],
                "entry_price": None,
                "exit_price": None,
                "trade_open": False,
                "stop_loss": None,  # Example: 20% buffer for stop loss
                "sl_orderno": None  # To store the stop loss order number if needed
            },
            "pe": {
                "token": str(pe["Token"]),
                "symbol": pe["Symbol"],
                "entry_price": None,
                "exit_price": None,
                "trade_open": False,
                "stop_loss": None,  # Example: 20% buffer for stop loss
                "sl_orderno": None  # To store the stop loss order number if needed
            }
        }
        
        # Insert into MongoDB
        insert_result = trades_collection.insert_one(trade_document)
        
        return {
            "message": "Symbols fetched and trade saved successfully",
        }, 200

def execute_order(client, ordertype="MKT", transaction_type="S", quantity="65", product="MIS"):
    """
    1. Fetches the latest strangle trade document from MongoDB.
    2. Extracts the CE and PE symbols.
    3. Calls placeorder() to execute the short positions and get entry prices.
    4. Updates MongoDB with entry_price, stop_loss (entry_price + 15), and trade_open = True.
    """
    try:
        # 1. Fetch the latest trade document where trade is not yet open
        trade_doc = trades_collection.find_one(
            {"strategy": "strangle", "ce.trade_open": False},
            sort=[("created_at", -1)]
        )
        
        if not trade_doc:
            print("❌ No pending strangle trade found in MongoDB.")
            return {"status": "error", "message": "No pending trade found"}

        trade_id = trade_doc["_id"]
        ce_symbol = trade_doc["ce"]["symbol"]
        pe_symbol = trade_doc["pe"]["symbol"]
        symbols = [ce_symbol, pe_symbol]

        print(f"{symbols} - Placing orders for CE and PE symbols.")

        # 2. Place orders using your existing placeorder function
        order_results = placeorder(client, symbols, ordertype=ordertype, transaction_type=transaction_type, quantity=quantity, product=product)

        # 3. Extract execution results for CE and PE
        ce_result = order_results.get(ce_symbol, {})
        pe_result = order_results.get(pe_symbol, {})

        ce_entry = ce_result.get("entry_price")
        pe_entry = pe_result.get("entry_price")

        # Validation: Ensure both orders were successfully executed
        if not ce_entry or not pe_entry:
            print("❌ Failed to retrieve execution prices for one or both legs.")
            return {"status": "error", "message": "Order execution incomplete or failed"}

        # 4. Calculate Stop Loss (entry_price + 15)
        ce_stop_loss = round(ce_entry + 15, 2)
        pe_stop_loss = round(pe_entry + 15, 2)

        # 5. Update MongoDB with entry prices, stop losses, and trade status
        update_result = trades_collection.update_one(
            {"_id": trade_id},
            {
                "$set": {
                    "ce.entry_price": ce_entry,
                    "ce.stop_loss": ce_stop_loss,
                    "ce.trade_open": True,
                    "pe.entry_price": pe_entry,
                    "pe.stop_loss": pe_stop_loss,
                    "pe.trade_open": True,
                    "executed_at": datetime.now()
                }
            }
        )

        if update_result.modified_count > 0:
            print("✅ Trade successfully updated in MongoDB with entry prices and stop losses!")
            return {
                "status": "success",
                "message": "Orders executed and database updated successfully",
                "data": {
                    "ce": {"symbol": ce_symbol, "entry_price": ce_entry, "stop_loss": ce_stop_loss},
                    "pe": {"symbol": pe_symbol, "entry_price": pe_entry, "stop_loss": pe_stop_loss}
                }
            }
        else:
            print("⚠️ Database update failed or no changes were made.")
            return {"status": "error", "message": "Database update failed"}

    except Exception as e:
        print(f"❌ Exception in execute_order: {e}")
        return {"status": "error", "message": str(e)}

def place_stop_loss_orders(client, quantity="65", product="MIS"):
    """
    1. Fetches the active open trade from MongoDB.
    2. Places a Stop Loss Market (SL-M) Buy order for both CE and PE symbols
       using the stop-loss prices stored in MongoDB.
    """
    try:
        # 1. Fetch the active open trade document from MongoDB
        trade_doc = trades_collection.find_one(
            {"strategy": "strangle", "ce.trade_open": True, "pe.trade_open": True},
            sort=[("created_at", -1)]
        )
        
        if not trade_doc:
            print("❌ No active open trade found in MongoDB to place stop loss.")
            return {"status": "error", "message": "No active trade found"}
        
        trade_id = trade_doc["_id"]
        
        legs = [
            ("CE", trade_doc["ce"]),
            ("PE", trade_doc["pe"])
        ]
        
        sl_results = {}

        for leg_name, leg_data in legs:
            symbol = leg_data["symbol"]
            stop_loss_price = leg_data["stop_loss"]

            if not stop_loss_price:
                print(f"⚠️ Stop loss price not found for {leg_name} ({symbol}). Skipping.")
                continue

            print(f"🛡️ Placing Stop Loss order for {leg_name}: {symbol} at Trigger Price: {stop_loss_price}")

            # 2. Place Stop Loss Market (SL-M) order (Buy transaction to exit short position)
            res = client.place_order(
                exchange_segment="nse_fo",            # Options trade on nse_fo
                product=product,                      # MIS or NRML
                price=str(stop_loss_price),                            # 0 for SL-M trigger orders
                order_type="SL",                    # Stop Loss Market order type
                quantity=str(quantity),               # Lot size / Quantity as string
                validity="DAY",
                trading_symbol=symbol,
                transaction_type="B",                 # 'B' for Buy (to cover/exit short)
                amo="NO",
                trigger_price=str(stop_loss_price)    # The calculated trigger price
            )

            status_code = res.get("stCode")
            order_number = res.get("nOrdNo")

            if status_code == 200:
                if leg_name == "CE":
                    update_result = trades_collection.update_one(
                                {"_id": trade_id},
                                {
                                    "$set": {
                                        "ce.sl_orderno": order_number
                                    }
                                }
                            )
                elif leg_name == "PE":
                    update_result = trades_collection.update_one(
                                {"_id": trade_id},
                                {
                                    "$set": {
                                        "pe.sl_orderno": order_number
                                    }
                                }
                            )    
                sl_results[leg_name] = {
                    "symbol": symbol,
                    "order_no": order_number,
                    "trigger_price": stop_loss_price,
                    "status": "success"
                }
            else:
                print(f"❌ Failed to place Stop Loss order for {symbol}. Response: {res}")
                sl_results[leg_name] = {
                    "symbol": symbol,
                    "status": "failed",
                    "response": res
                }

        return {
            "status": "success",
            "message": "Stop loss orders processed",
            "data": sl_results
        }

    except Exception as e:
        print(f"❌ Exception in place_stop_loss_orders: {e}")
        return {"status": "error", "message": str(e)}
    
def close_all_positions(client,quantity="65", product="MIS"):
    """
    1. Fetches the active open trade document from MongoDB.
    2. Identifies which legs (CE and/or PE) are currently open.
    3. Places Market Buy orders only for the active open legs to square them off.
    4. Dynamically updates MongoDB to set trade_open = False and record exit prices only for closed legs.
    """
    try:
        # 1. Fetch the active open trade from MongoDB where at least one leg is open
        trade_doc = trades_collection.find_one(
            {
                "strategy": "strangle", 
                "$or": [
                    {"ce.trade_open": True}, 
                    {"pe.trade_open": True}
                ]
            },
            sort=[("created_at", -1)]
        )
        
        if not trade_doc:
            print("❌ No active open trade found in MongoDB to close.")
            return {"status": "error", "message": "No active trade found"}

        trade_id = trade_doc["_id"]
        
        # Track which legs are open
        ce_is_open = trade_doc.get("ce", {}).get("trade_open", False)
        pe_is_open = trade_doc.get("pe", {}).get("trade_open", False)
        
        ce_symbol = trade_doc["ce"].get("symbol") if ce_is_open else None
        pe_symbol = trade_doc["pe"].get("symbol") if pe_is_open else None
        
        ceslorder_no = str(trade_doc["ce"].get("sl_orderno"))
        peslorder_no = str(trade_doc["pe"].get("sl_orderno"))
        client.cancel_order(order_id = ceslorder_no, isVerify=True)
        client.cancel_order(order_id = peslorder_no, isVerify=True)
        symbols = []
        if ce_is_open and ce_symbol:
            symbols.append(ce_symbol)
        if pe_is_open and pe_symbol:
            symbols.append(pe_symbol)

        if not symbols:
            print("❌ No open symbols found to square off.")
            return {"status": "error", "message": "No open symbols found"}

        # 2. Place Market Buy orders only for open legs
        order_results = placeorder(
            client=client,
            symbols=symbols,
            ordertype="MKT",
            transaction_type="B",
            quantity=quantity,
            product=product
        )

        # 3. Build dyn"amic update dictionary for MongoDB and result data
        update_fields = {"closed_at": datetime.now()}
        response_data = {}

        if ce_is_open and ce_symbol:
            ce_result = order_results.get(ce_symbol, {})
            ce_exit = ce_result.get("entry_price")  # Execution price for the buy order
            
            update_fields["ce.trade_open"] = False
            update_fields["ce.exit_price"] = ce_exit
            response_data["ce"] = {"symbol": ce_symbol, "exit_price": ce_exit}

        if pe_is_open and pe_symbol:
            pe_result = order_results.get(pe_symbol, {})
            pe_exit = pe_result.get("entry_price")  # Execution price for the buy order
            
            update_fields["pe.trade_open"] = False
            update_fields["pe.exit_price"] = pe_exit
            response_data["pe"] = {"symbol": pe_symbol, "exit_price": pe_exit}

        # 4. Update MongoDB selectively for only the active legs that were squared off
        update_result = trades_collection.update_one(
            {"_id": trade_id},
            {"$set": update_fields}
        )

        if update_result.modified_count > 0:
            print("✅ Active positions successfully squared off and MongoDB updated selectively!")
            return {
                "status": "success",
                "message": "Open positions closed and database updated successfully",
                "data": response_data
            }
        else:
            print("⚠️ Failed to update MongoDB trade document.")
            return {"status": "error", "message": "Database update failed"}

    except Exception as e:
        print(f"❌ Exception in close_all_positions: {e}")
        return {"status": "error", "message": str(e)}    
    
def start_websocket(client, quantity="65"):
# 1. Initialize client & complete login
    trade_doc = trades_collection.find_one(
    {
        "strategy": "strangle", 
        "$or": [
            {"ce.trade_open": True}, 
            {"pe.trade_open": True}
        ]
    },
    sort=[("created_at", -1)]
)
            
    if not trade_doc:
        print("❌ No active open trade found in MongoDB to close.")
        return {"status": "error", "message": "No active trade found"}

    # 2. Define your tokens
    tokence, segment1 = trade_doc["ce"]["token"], "nse_fo"
    tokenpe, segment2 = trade_doc["pe"]["token"], "nse_fo"

    # 3. Start WebSocket in a background thread
    ws_thread = threading.Thread(
        target=websocket.run_websocket_loop,
        args=(client, tokence, segment1, tokenpe, segment2),
        daemon=False
    )
    ws_thread.start()
    print("WebSocket background thread launched.")
    # Clear any prior states if restarting
    stop_monitoring_event.clear()

    logic_thread = threading.Thread(
        target=logic.monitor_strangle_sl,
        args=(client, quantity, 0.1, stop_monitoring_event),  # 👈 Pass event here
        daemon=False
    )
    logic_thread.start()
    
def stop_websocket():
    websocket.stop_websocket()
    print("WebSocket stop signal sent.")
    
def stop_logic_monitoring():
    stop_monitoring_event.set()
    print("Logic monitoring stop signal sent.")
    
# Define IST timezone
IST = pytz.timezone('Asia/Kolkata')

def is_market_open_today():
    """
    Checks if NSE is open today (excluding weekends and official trading holidays).
    """
    try:
        today = datetime.now(IST).date()
        
        # Correct function name is get_calendar instead of get_market_calendar
        nse = mcal.get_calendar('NSE')
        
        schedule = nse.schedule(start_date=today, end_date=today)
        return not schedule.empty
    except Exception as e:
        print(f"⚠️ Error checking market calendar: {e}. Defaulting to True.")
        return True # Fallback if calendar lookup fails
    
def run_scheduled_jobs():
    """
    Background worker that checks current IST time and triggers:
    - 9:00 AM: Auto login
    - 9:20:50 AM: Execute orders, place SL, start websocket
    - 3:05 PM: Close positions and stop websocket (unless done manually)
    """
    global client, MANUAL_CLOSE_DONE
    
    last_run_date = None
    ran_900 = False
    ran_921 = False
    ran_1505 = False

    print("🕒 IST Background Scheduler started successfully.")

    while True:
        try:
            now_ist = datetime.now(IST)
            current_date = now_ist.date()
            current_time = now_ist.time()

            # Reset flags on a new day
            if last_run_date != current_date:
                last_run_date = current_date
                ran_900 = False
                ran_921 = False
                ran_1505 = False
                MANUAL_CLOSE_DONE = False  # Reset manual flag for the new trading day

            # Skip execution if today is a weekend or market holiday
            if not is_market_open_today():
                time.sleep(3600)  # Sleep for an hour on holidays/weekends
                continue

            # 1. Auto Login at 9:00 AM
            if not ran_900 and current_time >= dtime(9, 0, 0) and current_time < dtime(9, 1, 0):
                print("🔐 [Scheduler] Running 9:00 AM Auto Login...")
                try:
                    client = get_authenticated_client()
                    print("✅ [Scheduler] Re-authenticated client successfully.")
                except Exception as e:
                    print(f"❌ [Scheduler] Auto login failed: {e}")
                ran_900 = True

            # 2. Execute Orders & Start Websocket at 9:20:50 AM
            elif not ran_921 and current_time >= dtime(9, 20, 50) and current_time < dtime(9, 22, 0):
                print("🚀 [Scheduler] Running 9:20:50 AM Order Execution & Websocket Start...")
                try:
                    fetch_symbols_route()
                    time.sleep(1) 
                    exec_res = execute_order(client, ordertype="MKT", transaction_type="S", quantity=hard_quantity, product="NRML")
                    if exec_res.get("status") == "success":
                        place_stop_loss_orders(client, quantity=hard_quantity, product="NRML")
                        start_websocket(client, quantity=hard_quantity)
                        print("✅ [Scheduler] Orders executed, SL placed, and websocket started.")
                    else:
                        print("⚠️ [Scheduler] Order execution skipped or failed.")
                except Exception as e:
                    print(f"❌ [Scheduler] 9:20:50 AM execution routine failed: {e}")
                ran_921 = True

            # 3. Close Positions & Stop Websocket at 3:05 PM (Skipped if MANUAL_CLOSE_DONE is True)
            elif not ran_1505 and not MANUAL_CLOSE_DONE and current_time >= dtime(15, 5, 0) and current_time < dtime(15, 6, 0):
                print("🛑 [Scheduler] Running 3:05 PM Close Positions & Stop Websocket...")
                try:
                    close_all_positions(client, quantity=hard_quantity, product="MIS")
                    stop_websocket()
                    stop_logic_monitoring()
                    print("✅ [Scheduler] Positions closed and websocket stopped.")
                except Exception as e:
                    print(f"❌ [Scheduler] 3:05 PM closing routine failed: {e}")
                ran_1505 = True

            # If manual close already happened, mark ran_1505 as True so it doesn't evaluate this block again
            elif MANUAL_CLOSE_DONE:
                ran_1505 = True

        except Exception as e:
            print(f"❌ Error in scheduler loop: {e}")

        # Check time every 1 second
        time.sleep(1)

def start_scheduler_thread():
    scheduler_thread = threading.Thread(target=run_scheduled_jobs, daemon=True)
    scheduler_thread.start()
         
def manual_close_trade():
    """
    Manually close all positions, stop the websocket and monitoring thread,
    and prevent the 3:05 PM scheduler from running again today.
    """
    global client, hard_quantity
    global MANUAL_CLOSE_DONE
    print("🛑 [Manual Trigger] Forcibly closing all positions and stopping services...")
    
    try:
        close_all_positions(client, quantity=hard_quantity,  product="MIS")
        stop_websocket()
        stop_logic_monitoring()  # Ensures your stop_event is triggered
        
        MANUAL_CLOSE_DONE = True
        return {"status": "success", "message": "Positions closed manually."}
    
    except Exception as e:
        print(f"❌ [Manual Trigger] Error during manual close: {e}")
        return {"status": "error", "message": str(e)}
                
if __name__ == "__main__":
    
    start_scheduler_thread()
    app.run(debug=True, port=8000, use_reloader=False)
    
        
