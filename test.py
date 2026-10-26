# from neo_api_client import NeoAPI
# from login import get_authenticated_client

# client = get_authenticated_client()
# try:
#     # Place a Order
#     res = client.place_order(
#         exchange_segment="nse_cm",
#         product="MIS",
#         price="290",
#         order_type="MKT",
#         quantity="1",
#         validity="DAY",
#         trading_symbol="BPCL-EQ",
#         transaction_type="B",
#         # amo="NO",
#         # disclosed_quantity="0",
#         # market_protection="0",
#         # pf="N",
#         # trigger_price="0",
#         # tag=None,
#         # scrip_token=None,
#         # square_off_type=None,
#         # stop_loss_type=None,
#         # stop_loss_value=None,
#         # square_off_value=None,
#         # last_traded_price=None,
#         # trailing_stop_loss=None,
#         # trailing_sl_value=None,
#     )
#     print("Order placed successfully!")
#     print(res)
# except Exception as e:
#     print("Exception when calling OrderApi->place_order: %s\n" % e)
# order_number = res.get("nOrdNo")

# if order_number:
#     print(f"\nFetching history for Order ID: {order_number}...")
    
#     # 3. Fetch order history using the order ID
#     history_response = client.order_history(order_id=order_number)
    
#     print("\n--- Detailed Order History & Entry Price ---")
#     # pprint.pprint(history_response)
    
#     # Optional: Extract and print the specific executed/average price if available
#     try:
#         orders_list = history_response.get("data", {}).get("data", [])
#         for ord_detail in orders_list:
#             if ord_detail.get("ordSt") == "complete":
#                 print(f"\n✅ Order Complete! Executed Entry Price: {ord_detail.get('avgPrc')}")
#                 break
#     except Exception as parse_err:
#         print(f"Could not parse average price: {parse_err}")
        
# else:
#     print("\nCould not retrieve order number from response.")

import time
from neo_api_client import NeoAPI
from login import get_authenticated_client

def execute_straddle_short_with_sl(client, symbols, quantity="65", product="MIS"):
    """
    Sells two option symbols, retrieves their executed entry prices, 
    and places a corresponding Stop Loss order at entry_price + 10.
    """
    results = {}

    for symbol in symbols:
        print(f"\n--- Processing Order for: {symbol} ---")
        try:
            # 1. Place Sell Order (Market Order for quick execution)
            res = client.place_order(
                exchange_segment="nse_fo",      # Options trade on nse_fo
                product=product,                # MIS or NRML
                price="0",                      # 0 for Market orders
                order_type="MKT",               # Market Type
                quantity=str(quantity),         # Lot size / Quantity as string
                validity="DAY",
                trading_symbol=symbol,
                transaction_type="S",           # 'S' for Sell (shorting premium)
                amo="NO"
            )
            
            print(f"Sell order response for {symbol}: {res}")
            order_number = res.get("nOrdNo")

            if not order_number:
                print(f"❌ Could not retrieve order number for {symbol}.")
                continue

            # 2. Wait briefly for the order to execute and update history
            print(f"Waiting for order {order_number} execution...")
            time.sleep(2) 

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
            
            if not entry_price:
                print(f"⚠️ Could not find execution price for {symbol} from history yet.")
                continue

            # 4. Calculate Stop Loss Price (Entry + 10)
            sl_price = round(entry_price + 10, 2)
            print(f"Placing Stop-Loss Market (SL-M) order at trigger price: {sl_price}")

            # 5. Place Stop Loss Order (Buy back to cover short position)
            sl_res = client.place_order(
                exchange_segment="nse_fo",
                product=product,
                price=str(sl_price),            # Limit/Trigger price reference
                order_type="SL-M",              # Stop Loss Market order type
                quantity=str(quantity),
                validity="DAY",
                trading_symbol=symbol,
                transaction_type="B",           # 'B' to buy back the short position
                trigger_price=str(sl_price),    # Trigger price where SL activates
                amo="NO"
            )
            
            print(f"✅ Stop-Loss order placed successfully for {symbol}: {sl_res}")
            results[symbol] = {
                "entry_price": entry_price,
                "sl_price": sl_price,
                "sell_order_id": order_number,
                "sl_response": sl_res
            }

        except Exception as e:
            print(f"❌ Exception occurred while processing {symbol}: {e}")

    return results