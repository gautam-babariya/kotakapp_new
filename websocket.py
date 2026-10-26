import asyncio
from neo_api_client import NeoAPI
from neo_api_client.websocket.feed import WsToken, SFeedScrip

# Global shared state storing only LTP per token
live_feed_data = {}
_ws_task = None
_stop_event = asyncio.Event()

async def _start_websocket_async(client: NeoAPI, token1: str, segment1: str, token2: str, segment2: str):
    global live_feed_data, _stop_event
    _stop_event.clear()
    
    try:
        async with client.create_websocket() as ws:
            await ws.subscribe_scrips([
                WsToken(segment1, str(token1)),
                WsToken(segment2, str(token2))
            ])
            print(f"Successfully connected and subscribed to: {token1} ({segment1}), {token2} ({segment2})")

            ws_iter = ws.__aiter__()

            while not _stop_event.is_set():
                try:
                    message = await asyncio.wait_for(ws_iter.__anext__(), timeout=1.0)
                    
                    if isinstance(message, SFeedScrip):
                        tk = str(message.instrument_token)
                        ltp = message.last_traded_price  # Extracting LTP directly
                        
                        # Store only LTP (or expand with other clean attributes if needed)
                        live_feed_data[tk] = {
                            "tk": tk,
                            "ltp": ltp
                        }
                        # print(f"[Live Tick] Token: {tk} | LTP: {ltp}")
                        
                except asyncio.TimeoutError:
                    continue
                except StopAsyncIteration:
                    break
                    
    except asyncio.CancelledError:
        print("WebSocket task was cancelled.")
    except Exception as e:
        print(f"Exception in SFeed WebSocket connection: {e}")
    finally:
        print("WebSocket connection closed.")

def run_websocket_loop(client, token1, segment1, token2, segment2):
    """Runs the asyncio event loop for the WebSocket."""
    global _ws_task
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    _ws_task = loop.create_task(_start_websocket_async(client, token1, segment1, token2, segment2))
    try:
        loop.run_until_complete(_ws_task)
    finally:
        loop.close()

def stop_websocket():
    """Signals the WebSocket async loop to terminate cleanly."""
    global _stop_event
    print("Stopping WebSocket...")
    _stop_event.set()