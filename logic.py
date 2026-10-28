import time
from datetime import datetime
import websocket 
from config import trades_collection, config_collection
from placeorder import placeorder

# Added stop_event parameter here 👇
def monitor_strangle_sl(client, quantity="65", check_interval=0.1, stop_event=None):
    print("🚀 Optimized Logic/SL monitoring thread started.")
    
    try:
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
            print("🛑 No active open strangle trade found in MongoDB.")
            websocket.stop_websocket()
            return

        trade_id = trade_doc["_id"]
        ce_data = trade_doc["ce"]
        pe_data = trade_doc["pe"]
        
        ce_token = str(ce_data.get("token"))
        pe_token = str(pe_data.get("token"))
        ce_symbol = [str(ce_data.get("symbol"))]
        pe_symbol = [str(pe_data.get("symbol"))] # or pe_data.get("symbol")
        
        ce_open = ce_data.get("trade_open", True)
        pe_open = pe_data.get("trade_open", True)
        
        ceslorder_no = str(ce_data.get("sl_orderno"))
        peslorder_no = str(pe_data.get("sl_orderno"))

        while ce_open or pe_open:
            # 🛑 STEP 2 CHECK: Break out immediately if stop signal is triggered
            if stop_event and stop_event.is_set():
                print("🛑 External stop signal received. Breaking monitoring loop...")
                break

            ce_sl = float(ce_data.get("entry_price", 0.0)) + 10.0   
            pe_sl = float(pe_data.get("entry_price", 0.0)) + 10.0
            
            if ce_open != True:
                pe_sl = float(pe_data.get("entry_price", 0.0)) 
            if pe_open != True:
                ce_sl = float(ce_data.get("entry_price", 0.0)) 
            
            ce_tick = websocket.live_feed_data.get(ce_token) if ce_open else None
            pe_tick = websocket.live_feed_data.get(pe_token) if pe_open else None
            
            if (ce_open and not ce_tick) or (pe_open and not pe_tick):
                time.sleep(check_interval)
                continue
                
            ce_ltp = float(ce_tick.get("ltp", 0.0)) if ce_tick else 0.0
            pe_ltp = float(pe_tick.get("ltp", 0.0)) if pe_tick else 0.0
            
            # CE Stop-Loss Check
            if ce_open and ce_ltp >= ce_sl:
                print(f"⚠️ CE STOP LOSS HIT! Token {ce_token} | LTP: {ce_ltp} >= SL: {ce_sl}")
                try:
                    order_results = placeorder(client, [str(ce_data.get("symbol"))], ordertype="MKT", transaction_type="B", quantity=quantity, product="NRML")
                    trades_collection.update_one(
                        {"_id": trade_id},
                        {"$set": {"ce.trade_open": False, "ce.exit_price": ce_ltp}}
                    )
                    ce_open = False
                    client.cancel_order(order_id=ceslorder_no, isVerify=True)
                    print("✅ CE leg closed and updated in MongoDB.")
                except Exception as e:
                    print(f"❌ Error squaring off CE leg: {e}")

            # PE Stop-Loss Check
            if pe_open and pe_ltp >= pe_sl:
                print(f"⚠️ PE STOP LOSS HIT! Token {pe_token} | LTP: {pe_ltp} >= SL: {pe_sl}")
                try:
                    order_results = placeorder(client, [str(pe_data.get("symbol"))], ordertype="MKT", transaction_type="B", quantity=quantity, product="NRML")
                    trades_collection.update_one(
                        {"_id": trade_id},
                        {"$set": {"pe.trade_open": False, "pe.exit_price": pe_ltp}}
                    )
                    pe_open = False
                    client.cancel_order(order_id=peslorder_no, isVerify=True)
                    print("✅ PE leg closed and updated in MongoDB.")
                except Exception as e:
                    print(f"❌ Error squaring off PE leg: {e}")

            time.sleep(check_interval)

        print("🏁 Monitoring loop finished. Stopping WebSocket.")
        websocket.stop_websocket()

    except Exception as e:
        print(f"❌ Exception in monitoring thread: {e}")
    finally:
        print("🛑 Logic/SL monitoring thread terminated.")