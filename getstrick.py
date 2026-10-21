import time
from datetime import datetime
from login import get_authenticated_client
from config import get_config

def get_strangle_symbols():
    """
    Finds and returns the two Nifty option strikes (CE and PE) 
    based on the premium filter, without placing any orders.
    """
    try:
        client = get_authenticated_client()
        if not client:
            print("[Strategy] Authentication failed.")
            return {"status": "error", "message": "Authentication failed"}

        config = get_config()
        max_premium = float(config.get("premium_filter", 25))

        print(f"\n[Strategy] Searching Nifty F&O option contracts (Max Premium: {max_premium})...")
        
        scrip_results = client.search_scrip(
            exchange_segment="nse_fo", 
            symbol="NIFTY", 
            expiry="",          
            option_type="",     
            strike_price=""     
        )

        if not scrip_results:
            print("[Strategy] No option contracts found.")
            return {"status": "error", "message": "No option contracts found"}

        nifty_scrips = [s for s in scrip_results if s.get("pSymbolName") == "NIFTY"]
        raw_expiries = set(s.get("pExpiryDate") for s in nifty_scrips if s.get("pExpiryDate"))
        
        sorted_expiries = sorted(
            raw_expiries, 
            key=lambda x: datetime.strptime(x, "%d%b%Y")
        )

        if len(sorted_expiries) < 2:
            print("[Strategy] Less than two expiries available.")
            return {"status": "error", "message": "Less than two expiries available"}

        second_expiry = sorted_expiries[1]
        print(f"[Strategy] Selected Second Expiry Date: {second_expiry}")

        instrument_tokens = []
        contract_map = {}

        for scrip in nifty_scrips:
            token = str(scrip.get("pSymbol"))
            opt_type = scrip.get("pOptionType")
            expiry = scrip.get("pExpiryDate")
            
            if expiry != second_expiry:
                continue

            strike_val = scrip.get("dStrikePrice;") or 0
            try:
                strike = float(strike_val)
                if strike > 100000:
                    strike = strike / 100.0
            except (ValueError, TypeError):
                strike = 0

            if token and opt_type in ["CE", "PE"] and strike > 0:
                instrument_tokens.append({
                    "instrument_token": token,
                    "exchange_segment": "nse_fo"
                })
                contract_map[token] = scrip

        print(f"[Strategy] Fetching live quotes for {len(instrument_tokens)} contracts...")

        batch_size = 30
        all_quotes = []

        for i in range(0, len(instrument_tokens), batch_size):
            batch = instrument_tokens[i:i+batch_size]
            if not batch:
                continue
                
            quotes_res = client.quotes(instrument_tokens=batch, quote_type="ltp")
            
            items = []
            if isinstance(quotes_res, list):
                items = quotes_res
            elif isinstance(quotes_res, dict):
                items = quotes_res.get("data") or quotes_res.get("result") or []
                if not items and ("ltp" in quotes_res or "lastTradedPrice" in quotes_res):
                    items = [quotes_res]

            for q in items:
                token = str(q.get("instrument_token") or q.get("exchange_token") or q.get("pSymbol") or "")
                ltp = float(q.get("lastTradedPrice") or q.get("ltp") or q.get("pLastTradedPrice") or 0)
                
                scrip_info = contract_map.get(token, {})
                all_quotes.append({
                    "Token": token,
                    "Type": scrip_info.get("pOptionType"),
                    "Symbol": scrip_info.get("pTrdSymbol"),
                    "LTP": ltp
                })
            
            time.sleep(0.3)

        ce_candidates = [item for item in all_quotes if item["Type"] == "CE" and 0 < item["LTP"] <= max_premium]
        pe_candidates = [item for item in all_quotes if item["Type"] == "PE" and 0 < item["LTP"] <= max_premium]

        target_ce = max(ce_candidates, key=lambda x: x["LTP"]) if ce_candidates else None
        target_pe = max(pe_candidates, key=lambda x: x["LTP"]) if pe_candidates else None

        if not target_ce or not target_pe:
            print("[Strategy Error] Could not find valid CE and PE options within the premium filter limit.")
            return {"status": "error", "message": "No matching option contracts found within premium limit"}

        print(f"[Strategy] Selected CE -> Symbol: {target_ce['Symbol']} | LTP: {target_ce['LTP']}")
        print(f"[Strategy] Selected PE -> Symbol: {target_pe['Symbol']} | LTP: {target_pe['LTP']}")

        # Return just the selected symbol data to app.py
        return {
            "status": "success",
            "expiry": second_expiry,
            "ce": target_ce,
            "pe": target_pe
        }

    except Exception as e:
        print(f"[Strategy Exception]: {e}")
        return {"status": "error", "message": str(e)}