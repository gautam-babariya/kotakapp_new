from flask import Flask, jsonify
from exittrade import exit_strangle_positions
from getstrick import get_strangle_symbols
from login import get_authenticated_client
from config import trades_collection,config_collection
from placeorder import place_strangle_orders

app = Flask(__name__)
client = get_authenticated_client()

@app.route("/")
def home():
    return jsonify({"message": "Kotak Neo Algo Trading Flask App is running!"})

@app.route('/get-symbols', methods=['GET'])
def fetch_symbols_route():
    result = get_strangle_symbols()
    
    if result["status"] == "error":
        return {"error": result["message"]}, 400
        
    # Now you have target_ce and target_pe available to use in app.py
    return {
        "message": "Symbols fetched successfully",
        "expiry": result["expiry"],
        "ce_symbol": result["ce"]["Symbol"],
        "ce_ltp": result["ce"]["LTP"],
        "pe_symbol": result["pe"]["Symbol"],
        "pe_ltp": result["pe"]["LTP"]
    }

@app.route('/place-order', methods=['GET'])
def place_order_route():
    # For demonstration, using hardcoded values. In practice, these should come from the request body.
    result = place_strangle_orders(
        ce_symbol="NIFTY03NOV23900CE", 
        ce_ltp=21.35, 
        pe_symbol="NIFTY03NOV21950PE", 
        pe_ltp=24.35, 
        expiry="03NOV2026"
    )
    
    if result.get("status") == "error":
        return jsonify(result), 400
        
    return jsonify(result), 200


# @app.route('/exit-trade', methods=['POST', 'GET'])
# def exit_trade_route():
#     """
#     API endpoint to square off any active/open option legs and update MongoDB.
#     """
#     result = exit_strangle_positions()
    
#     if result.get("status") == "error":
#         return jsonify(result), 400
        
#     return jsonify(result), 200

if __name__ == "__main__":
    app.run(debug=True, port=5000)
    
    
# testing of place order,exit order testing baki
# websocket and ordermodify aa bey baki