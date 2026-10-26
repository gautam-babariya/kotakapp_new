import time
from neo_api_client import NeoAPI

def placeorder(client,symbols,ordertype,transaction_type, quantity="65", product="MIS"):
    """
    Sells two option symbols, retrieves their executed entry prices, 
    and places a corresponding Stop Loss order at entry_price + 10.
    """
    results = {}
    for symbol in symbols:
        try:
            # 1. Place Sell Order (Market Order for quick execution)
            res = client.place_order(
                exchange_segment="nse_fo",      # Options trade on nse_fo
                product=product,                # MIS or NRML
                price="0",                      # 0 for Market orders
                order_type=ordertype,               # Market Type
                quantity=str(quantity),         # Lot size / Quantity as string
                validity="DAY",
                trading_symbol=symbol,
                transaction_type=transaction_type,
                amo="NO"
            )
            
            # print(f"Sell order response for {symbol}: {res}")
            status_code = res.get("stCode")
            order_number = res.get("nOrdNo")

            if status_code!=200:
                print(f"❌ Failed to place order for {symbol}. Response: {res}")
                continue

            # 3. Fetch order history to get the exact executed average price (avgPrc)
            history_response = client.order_history(order_id=order_number)
            orders_list = history_response.get("data", {}).get("data", [])
            
            entry_price = None
            for ord_detail in orders_list:
                # Check if the order is completed/executed
                if ord_detail.get("ordSt", "").lower() in ["complete", "traded"]:
                    entry_price = float(ord_detail.get("avgPrc", 0))
                    print(f"✅ Order Complete for {symbol}! Executed Entry Price: {entry_price}")
                    break
            
            results[symbol] = {
                "entry_price": entry_price,
                "status": status_code,
            }

        except Exception as e:
            print(f"❌ Exception occurred while processing {symbol}: {e}")

    return results
