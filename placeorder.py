from datetime import datetime
from login import get_authenticated_client
from config import get_config, log_trade

def place_strangle_orders(ce_symbol, ce_ltp, pe_symbol, pe_ltp, expiry):
    """
    Takes the provided CE and PE symbols and LTPs from app.py,
    places MARKET SELL orders, places SL-M orders (Entry + 10 Rs),
    and logs the trade details into MongoDB.
    """
    try:
        client = get_authenticated_client()
        if not client:
            print("[Strategy] Authentication failed.")
            return {"status": "error", "message": "Authentication failed"}

        config = get_config()
        lot_size = str(config.get("lot_size", 1))
        sl_points = float(config.get("sl_points", 10.0))

        print(f"\n[Strategy] Placing orders for CE: {ce_symbol} ({ce_ltp}) & PE: {pe_symbol} ({pe_ltp})")

        # 1. Place Market Sell Order for CE
        print("[Strategy] Placing MARKET SELL order for CE leg...")
        ce_order = client.place_order(
            exchange_segment="nse_fo",
            product="MIS",
            price="0",
            order_type="MKT",
            quantity=lot_size,
            validity="DAY",
            trading_symbol=ce_symbol,
            transaction_type="S"
        )

        # 2. Place Market Sell Order for PE
        print("[Strategy] Placing MARKET SELL order for PE leg...")
        pe_order = client.place_order(
            exchange_segment="nse_fo",
            product="MIS",
            price="0",
            order_type="MKT",
            quantity=lot_size,
            validity="DAY",
            trading_symbol=pe_symbol,
            transaction_type="S"
        )

        # Calculate Stoploss Trigger Price (Entry + 10 Rs)
        ce_sl_trigger = round(float(ce_ltp) + sl_points, 2)
        pe_sl_trigger = round(float(pe_ltp) + sl_points, 2)

        # 3. Place Broker SL-M Order for CE
        print(f"[Strategy] Placing SL-M order for CE leg at trigger price: {ce_sl_trigger}...")
        ce_sl_order = client.place_order(
            exchange_segment="nse_fo",
            product="MIS",
            price="0",
            order_type="SL-M",
            quantity=lot_size,
            validity="DAY",
            trading_symbol=ce_symbol,
            transaction_type="B",
            trigger_price=str(ce_sl_trigger)
        )

        # 4. Place Broker SL-M Order for PE
        print(f"[Strategy] Placing SL-M order for PE leg at trigger price: {pe_sl_trigger}...")
        pe_sl_order = client.place_order(
            exchange_segment="nse_fo",
            product="MIS",
            price="0",
            order_type="SL-M",
            quantity=lot_size,
            validity="DAY",
            trading_symbol=pe_symbol,
            transaction_type="B",
            trigger_price=str(pe_sl_trigger)
        )

        # Format data structure expected by database.py `log_trade`
        ce_data = {"Symbol": ce_symbol, "Token": None, "LTP": float(ce_ltp)}
        pe_data = {"Symbol": pe_symbol, "Token": None, "LTP": float(pe_ltp)}

        # 5. Log Trade in MongoDB
        trade_id = log_trade(
            ce_data=ce_data,
            pe_data=pe_data,
            lot_size=int(lot_size),
            expiry=expiry
        )

        print(f"[Strategy] Orders placed successfully and logged to MongoDB with ID: {trade_id}")

        return {
            "status": "success",
            "trade_id": str(trade_id),
            "ce_order": ce_order,
            "pe_order": pe_order,
            "ce_sl_order": ce_sl_order,
            "pe_sl_order": pe_sl_order
        }

    except Exception as e:
        print(f"[Strategy Exception] {e}")
        return {"status": "error", "message": str(e)}