from flask import Flask, jsonify
from neo_api_client import NeoAPI
from getstrick import get_strangle_symbols
from login import get_authenticated_client
from config import trades_collection,config_collection
from placeorder import placeorder
from datetime import datetime
import asyncio
import threading
import time

from websocket import live_feed_data

import asyncio

import websocket
import logic

app = Flask(__name__)
client = get_authenticated_client()

@app.route("/")
def home():
    return jsonify({"message": "Kotak Neo Algo Trading Flask App is running!"})

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
                "stop_loss": None  # Example: 20% buffer for stop loss
            },
            "pe": {
                "token": str(pe["Token"]),
                "symbol": pe["Symbol"],
                "entry_price": None,
                "exit_price": None,
                "trade_open": False,
                "stop_loss": None  # Example: 20% buffer for stop loss
            }
        }
        
        # Insert into MongoDB
        insert_result = trades_collection.insert_one(trade_document)
        
        return {
            "message": "Symbols fetched and trade saved successfully",
        }, 200

def execute_order(client, ordertype="MKT", transaction_type="S", quantity="1", product="MIS"):
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

def place_stop_loss_orders(client, quantity="1", product="MIS"):
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
                price="0",                            # 0 for SL-M trigger orders
                order_type="SL-M",                    # Stop Loss Market order type
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
                print(f"✅ Stop Loss order placed successfully for {symbol}! Order No: {order_number}")
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
    
def close_all_positions(client, product="MIS"):
    """
    1. Fetches the active open trade document from MongoDB.
    2. Extracts CE and PE symbols.
    3. Calls placeorder() with transaction_type="B" and order_type="MKT" to square off positions.
    4. Updates MongoDB to set trade_open = False and record exit prices and status.
    """
    try:
        # 1. Fetch the active open trade from MongoDB where trade_open is True
        trade_doc = trades_collection.find_one(
            {"strategy": "strangle", "ce.trade_open": True, "pe.trade_open": True},
            sort=[("created_at", -1)]
        )
        
        if not trade_doc:
            print("❌ No active open trade found in MongoDB to close.")
            return {"status": "error", "message": "No active trade found"}

        trade_id = trade_doc["_id"]
        ce_symbol = trade_doc["ce"]["symbol"]
        pe_symbol = trade_doc["pe"]["symbol"]
        symbols = [ce_symbol, pe_symbol]

        print(f"🔄 Closing positions for CE: {ce_symbol} and PE: {pe_symbol}")

        # 2. Place Market Buy orders to square off the short positions
        # Note: ordertype="MKT" is passed, along with transaction_type="B"
        order_results = placeorder(
            client=client,
            symbols=symbols,
            ordertype="MKT",
            transaction_type="B",
            quantity="1",
            product=product
        )

        # 3. Extract execution results for CE and PE exit prices
        ce_result = order_results.get(ce_symbol, {})
        pe_result = order_results.get(pe_symbol, {})

        ce_exit = ce_result.get("entry_price") # This acts as the exit execution price
        pe_exit = pe_result.get("entry_price")

        if not ce_exit or not pe_exit:
            print("⚠️ Warning: Could not retrieve exact exit execution prices for one or more legs.")

        # 4. Update MongoDB to mark the trade as closed
        update_result = trades_collection.update_one(
            {"_id": trade_id},
            {
                "$set": {
                    "ce.exit_price": ce_exit,
                    "ce.trade_open": False,
                    "pe.exit_price": pe_exit,
                    "pe.trade_open": False,
                    "closed_at": datetime.now()
                }
            }
        )

        if update_result.modified_count > 0:
            print("✅ Positions successfully squared off and MongoDB updated!")
            return {
                "status": "success",
                "message": "All positions closed and database updated successfully",
                "data": {
                    "ce": {"symbol": ce_symbol, "exit_price": ce_exit},
                    "pe": {"symbol": pe_symbol, "exit_price": pe_exit}
                }
            }
        else:
            print("⚠️ Failed to update MongoDB trade document.")
            return {"status": "error", "message": "Database update failed"}

    except Exception as e:
        print(f"❌ Exception in close_all_positions: {e}")
        return {"status": "error", "message": str(e)}    
    
def start_websocket(client):
# 1. Initialize client & complete login
    trade_doc = trades_collection.find_one(
                {"strategy": "strangle", "ce.trade_open": True, "pe.trade_open": True},
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
    logic_thread = threading.Thread(
        target=logic.monitor_strangle_sl,
        args=(client, 0.1),  # high-speed 100ms interval
        daemon=False
    )
    logic_thread.start()
    
def stop_websocket():
    websocket.stop_websocket()
    print("WebSocket stop signal sent.")
    
        
if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)
    