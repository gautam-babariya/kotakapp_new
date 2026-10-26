import time
from datetime import datetime
import websocket  # Imports your websocket.py module
from config import trades_collection,config_collection
from placeorder import placeorder


def monitor_strangle_sl(client, check_interval=0.1):
    """
    Optimized monitoring worker that:
    1. Fetches the active trade document ONCE outside the loop for fast execution.
    2. Continuously checks LTP ticks in-memory.
    3. If CE or PE stop loss hits, updates MongoDB for that specific leg only (`trade_open: False`).
    4. Automatically shuts down the WebSocket and exits when both legs are closed.
    """
    print("🚀 Optimized Logic/SL monitoring thread started.")
    
    try:
        # 1. Fetch active trade ONCE before entering the high-speed loop
        trade_doc = trades_collection.find_one(
            {"strategy": "strangle", "$or": [{"ce.trade_open": True}, {"pe.trade_open": True}]},
            sort=[("created_at", -1)]
        )
        
        if not trade_doc:
            print("🛑 No active open strangle trade found in MongoDB.")
            websocket.stop_websocket()
            return

        trade_id = trade_doc["_id"]
        
        ce_data = trade_doc["ce"]
        pe_data = trade_doc["pe"]
        
        ce_token = str(ce_data.get("token"))
        pe_token = str(pe_data.get("token"))
        
        ce_symbol = ce_data.get("symbol")
        pe_symbol = pe_data.get("symbol")
        
        ce_sl = float(ce_data.get("stop_loss", 0.0))
        pe_sl = float(pe_data.get("stop_loss", 0.0))
        
        ce_open = ce_data.get("trade_open", True)
        pe_open = pe_data.get("trade_open", True)
        
        print(f"Tracking CE Token: {ce_token} (SL: {ce_sl}) | PE Token: {pe_token} (SL: {pe_sl})")

        while ce_open or pe_open:
            # 2. Get latest live LTP ticks from shared in-memory dictionary (ultra-fast)
            ce_tick = websocket.live_feed_data.get(ce_token) if ce_open else None
            pe_tick = websocket.live_feed_data.get(pe_token) if pe_open else None
            
            # Wait until live ticks are available for open legs
            if (ce_open and not ce_tick) or (pe_open and not pe_tick):
                time.sleep(check_interval)
                continue
                
            ce_ltp = float(ce_tick.get("ltp", 0.0)) if ce_tick else 0.0
            pe_ltp = float(pe_tick.get("ltp", 0.0)) if pe_tick else 0.0
            
            # 3. Check CE Stop-Loss (Short position: triggered if LTP >= stop_loss)
            if ce_open and ce_ltp >= ce_sl:
                print(f"⚠️ CE STOP LOSS HIT! Token {ce_token} | LTP: {ce_ltp} >= SL: {ce_sl}")
                try:
                    order_results = placeorder(client, ce_symbol, ordertype="MKT", transaction_type="B", quantity="1", product="MIS")
                    
                    # Update MongoDB for CE leg only
                    trades_collection.update_one(
                        {"_id": trade_id},
                        {
                            "$set": {
                                "ce.trade_open": False,
                                "ce.exit_price": ce_ltp
                            }
                        }
                    )
                    ce_open = False
                    print("✅ CE leg closed and updated in MongoDB.")
                except Exception as e:
                    print(f"❌ Error squaring off CE leg: {e}")

            # 4. Check PE Stop-Loss (Short position: triggered if LTP >= stop_loss)
            if pe_open and pe_ltp >= pe_sl:
                print(f"⚠️ PE STOP LOSS HIT! Token {pe_token} | LTP: {pe_ltp} >= SL: {pe_sl}")
                try:
                    order_results = placeorder(client, pe_symbol, ordertype="MKT", transaction_type="B", quantity="1", product="MIS")
                    
                    # Update MongoDB for PE leg only
                    trades_collection.update_one(
                        {"_id": trade_id},
                        {
                            "$set": {
                                "pe.trade_open": False,
                                "pe.exit_price": pe_ltp
                            }
                        }
                    )
                    pe_open = False
                    print("✅ PE leg closed and updated in MongoDB.")
                except Exception as e:
                    print(f"❌ Error squaring off PE leg: {e}")

            # High-speed polling interval
            time.sleep(check_interval)

        # 5. When both legs are closed, cleanup WebSocket
        print("🏁 Both CE and PE legs are now closed. Stopping WebSocket.")
        websocket.stop_websocket()

    except Exception as e:
        print(f"❌ Exception in monitoring thread: {e}")
    finally:
        print("🛑 Logic/SL monitoring thread terminated.")