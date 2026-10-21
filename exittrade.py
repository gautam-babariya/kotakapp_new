from datetime import datetime, timezone
from login import get_authenticated_client
from config import get_config, get_latest_trade, trades_collection

def exit_strangle_positions():
    """
    Checks active legs using live quotes. If one leg is open, exits that one.
    If both are open, exits both via BUY market orders and updates MongoDB.
    """
    try:
        client = get_authenticated_client()
        if not client:
            print("[Strategy] Authentication failed.")
            return {"status": "error", "message": "Authentication failed"}

        print("[Strategy] Fetching latest active trade from database...")
        active_trade = get_latest_trade()

        if not active_trade or active_trade.get("status") != "OPEN":
            print("[Strategy] No active open positions found to exit.")
            return {"status": "success", "message": "No open positions to exit"}

        trade_id = active_trade.get("_id")
        lot_size = str(get_config().get("lot_size", 25))

        ce_leg = active_trade.get("ce", {})
        pe_leg = active_trade.get("pe", {})

        # Prepare tokens for quote fetching
        instrument_tokens = []
        if ce_leg.get("status") == "ACTIVE" and ce_leg.get("symbol"):
            instrument_tokens.append({
                "instrument_token": ce_leg.get("token") or ce_leg.get("symbol"),
                "exchange_segment": "nse_fo"
            })
        if pe_leg.get("status") == "ACTIVE" and pe_leg.get("symbol"):
            instrument_tokens.append({
                "instrument_token": pe_leg.get("token") or pe_leg.get("symbol"),
                "exchange_segment": "nse_fo"
            })

        if not instrument_tokens:
            print("[Strategy] No active legs found in the trade record.")
            return {"status": "success", "message": "No active legs to exit"}

        # Fetch live quotes using the quotes API structure provided
        print(f"[Strategy] Checking live status/quotes for active legs...")
        quotes_res = client.quotes(instrument_tokens=instrument_tokens, quote_type="ltp")

        # Parse quotes response safely
        items = []
        if isinstance(quotes_res, list):
            items = quotes_res
        elif isinstance(quotes_res, dict):
            items = quotes_res.get("data") or quotes_res.get("result") or []
            if not items and ("ltp" in quotes_res or "lastTradedPrice" in quotes_res):
                items = [quotes_res]

        quote_map = {}
        for q in items:
            token = str(q.get("instrument_token") or q.get("exchange_token") or q.get("pSymbol") or "")
            ltp = float(q.get("lastTradedPrice") or q.get("ltp") or q.get("pLastTradedPrice") or 0)
            quote_map[token] = ltp

        results = []
        now = datetime.now(timezone.utc)
        update_fields = {}

        # Check and Exit CE Leg if active
        if ce_leg.get("status") == "ACTIVE":
            ce_symbol = ce_leg.get("symbol")
            ce_token = str(ce_leg.get("token") or ce_symbol)
            current_ce_ltp = quote_map.get(ce_token, ce_leg.get("entry_price"))

            print(f"[Strategy] Squaring off CE leg ({ce_symbol}) at LTP: {current_ce_ltp}...")
            close_ce_order = client.place_order(
                exchange_segment="nse_fo",
                product="MIS",
                price="0",
                order_type="MKT",
                quantity=lot_size,
                validity="DAY",
                trading_symbol=ce_symbol,
                transaction_type="B"  # Closing a SELL requires a BUY
            )
            results.append({"ce_order": close_ce_order})
            update_fields["ce.status"] = "CLOSED"
            update_fields["ce.exit_price"] = current_ce_ltp
            update_fields["ce.exit_time"] = now

        # Check and Exit PE Leg if active
        if pe_leg.get("status") == "ACTIVE":
            pe_symbol = pe_leg.get("symbol")
            pe_token = str(pe_leg.get("token") or pe_symbol)
            current_pe_ltp = quote_map.get(pe_token, pe_leg.get("entry_price"))

            print(f"[Strategy] Squaring off PE leg ({pe_symbol}) at LTP: {current_pe_ltp}...")
            close_pe_order = client.place_order(
                exchange_segment="nse_fo",
                product="MIS",
                price="0",
                order_type="MKT",
                quantity=lot_size,
                validity="DAY",
                trading_symbol=pe_symbol,
                transaction_type="B"  # Closing a SELL requires a BUY
            )
            results.append({"pe_order": close_pe_order})
            update_fields["pe.status"] = "CLOSED"
            update_fields["pe.exit_price"] = current_pe_ltp
            update_fields["pe.exit_time"] = now

        # Update MongoDB trade document status
        if update_fields and trades_collection is not None:
            # Check if all legs are now closed to update main status
            ce_closed = update_fields.get("ce.status") == "CLOSED" or ce_leg.get("status") == "CLOSED"
            pe_closed = update_fields.get("pe.status") == "CLOSED" or pe_leg.get("status") == "CLOSED"
            
            if ce_closed and pe_closed:
                update_fields["status"] = "CLOSED"
                update_fields["trade_open"] = False
                update_fields["closed_at"] = now

            trades_collection.update_one(
                {"_id": trade_id},
                {"$set": update_fields}
            )

        print("[Strategy] Exit execution completed successfully.")
        return {
            "status": "success",
            "message": "Processed exit for open legs successfully",
            "data": results
        }

    except Exception as e:
        print(f"[Strategy Exception during exit]: {e}")
        return {"status": "error", "message": str(e)}