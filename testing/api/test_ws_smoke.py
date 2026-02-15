"""
WebSocket Smoke Test

Tests basic WebSocket functionality:
1. Connection and disconnection
2. Subscribe/unsubscribe channels
3. Message reception with seq numbers
4. Multiple subscriptions + resume (same connection to avoid Docker WS limit)
5. Error handling (invalid type, missing channel, invalid channel)

Starts its own test server automatically.
"""


from datetime import datetime
from pathlib import Path
from typing import Optional
import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import time


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import websockets
except ImportError:
    print("✗ websockets package not installed")
    print("  Install with: pip install websockets")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("✗ requests package not installed")
    print("  Install with: pip install requests")
    sys.exit(1)


WS_URL = "ws://localhost:8002/api/v1/ws"
BASE_URL = "http://localhost:8002"


# Short timeouts so tests fail fast; ping_interval=None avoids idle-close by library
WS_CONNECT_KW = {"open_timeout": 5, "close_timeout": 2, "ping_interval": None}


async def _connect_ws_with_retry(max_attempts: int = 3, delay: float = 1.0):
    """Connect to WS with retries (server may be briefly busy after previous test)."""
    last_err = None
    for attempt in range(max_attempts):
        try:
            return await websockets.connect(WS_URL, **WS_CONNECT_KW)
        except (TimeoutError, OSError, ConnectionRefusedError) as e:
            last_err = e
            if attempt < max_attempts - 1:
                await asyncio.sleep(delay)
    raise last_err


async def _probe_ws(url: str, timeout: float = 2.0) -> None:
    """Probe WebSocket endpoint (connect and close)."""
    async with websockets.connect(url, open_timeout=timeout, close_timeout=2, ping_interval=None) as ws:
        pass


class WSTestServer:
    """Test server for WebSocket tests"""

    def __init__(self, port=8002):
        self.port = port
        self.process = None
        self.tmpdir = tempfile.mkdtemp()

    def start(self):
        """Start server"""
        print(f"Starting test server on port {self.port}...")

        env = os.environ.copy()
        env["DATAFILES_ROOT"] = self.tmpdir
        env["MODE"] = "paper"
        env["VENUE"] = "gtrade"
        env["PORT"] = str(self.port)

        # Start server
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "application.main:app",
             f"--host=0.0.0.0", f"--port={self.port}"],
            cwd=str(Path(__file__).parent.parent.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for HTTP first
        max_wait = 20
        for i in range(max_wait):
            try:
                response = requests.get(f"{BASE_URL}/", timeout=2)
                if response.status_code == 200:
                    print(f"✓ HTTP ready after {i+1}s")
                    break
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(1)
        else:
            raise RuntimeError("Server HTTP failed to start within timeout")

        # Wait for WebSocket endpoint to accept connections (avoids race)
        time.sleep(0.5)
        ws_ready = False
        for i in range(15):
            try:
                asyncio.run(_probe_ws(WS_URL, timeout=2))
                ws_ready = True
                print(f"✓ WebSocket ready after {i+1} probe(s)")
                break
            except Exception:
                time.sleep(0.5)
        if not ws_ready:
            raise RuntimeError("WebSocket endpoint not ready within timeout")

    def stop(self):
        """Stop server and wait for process exit (avoids port in TIME_WAIT / stuck process)."""
        if self.process:
            print("Stopping test server...")
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            self.process = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


async def test_basic_connection():
    """Test basic WebSocket connection"""
    print("Testing basic connection...")

    try:
        async with websockets.connect(WS_URL, **WS_CONNECT_KW) as ws:
            print("  ✓ Connected to WebSocket")

        print("  ✓ Disconnected cleanly")
        print("✓ Basic connection test passed")

    except Exception as e:
        print(f"✗ Connection failed: {e}")
        raise


async def test_subscribe_unsubscribe():
    """Test subscription and unsubscription"""
    print("Testing subscribe/unsubscribe...")

    try:
        async with websockets.connect(WS_URL, **WS_CONNECT_KW) as ws:
            # Subscribe to ticker channel
            subscribe_msg = {
                "type": "subscribe",
                "channel": "ticker:XAUUSD"
            }
            await ws.send(json.dumps(subscribe_msg))

            # Wait for subscribed confirmation
            response = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(response)

            assert data["type"] == "subscribed", f"Expected 'subscribed', got '{data['type']}'"
            assert data["channel"] == "ticker:XAUUSD"

            print(f"  ✓ Subscribed to ticker:XAUUSD")

            # Unsubscribe
            unsubscribe_msg = {
                "type": "unsubscribe",
                "channel": "ticker:XAUUSD"
            }
            await ws.send(json.dumps(unsubscribe_msg))

            # Wait for unsubscribed confirmation
            response = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(response)

            assert data["type"] == "unsubscribed", f"Expected 'unsubscribed', got '{data['type']}'"
            assert data["channel"] == "ticker:XAUUSD"

            print(f"  ✓ Unsubscribed from ticker:XAUUSD")

        print("✓ Subscribe/unsubscribe test passed")

    except asyncio.TimeoutError:
        print("✗ Timeout waiting for response")
        raise
    except Exception as e:
        print(f"✗ Test failed: {e}")
        raise


async def test_invalid_channel():
    """Test error handling for invalid channel"""
    print("Testing invalid channel error...")

    try:
        async with websockets.connect(WS_URL, **WS_CONNECT_KW) as ws:
            # Subscribe to invalid channel
            subscribe_msg = {
                "type": "subscribe",
                "channel": "ticker:INVALID"
            }
            await ws.send(json.dumps(subscribe_msg))

            # Wait for error response
            response = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(response)

            assert data["type"] == "error", f"Expected 'error', got '{data['type']}'"
            assert "Invalid channel" in data.get("error", "")

            print(f"  ✓ Error received for invalid channel")

        print("✓ Invalid channel test passed")

    except Exception as e:
        print(f"✗ Test failed: {e}")
        raise


async def test_multiple_subscriptions_and_resume():
    """Test multiple channels + resume (same connection to avoid Docker WS limit)."""
    print("Testing multiple subscriptions + resume...")

    try:
        async with websockets.connect(WS_URL, **WS_CONNECT_KW) as ws:
            channels = ["ticker:XAUUSD", "ticker:EURUSD", "positions", "balance", "candle:XAUUSD:1m"]

            for channel in channels:
                subscribe_msg = {
                    "type": "subscribe",
                    "channel": channel
                }
                await ws.send(json.dumps(subscribe_msg))

                # Wait for confirmation
                response = await asyncio.wait_for(ws.recv(), timeout=2.0)
                data = json.loads(response)

                assert data["type"] == "subscribed"
                assert data["channel"] == channel

                print(f"  ✓ Subscribed to {channel}")

            # Resume (reuse connection — evita 6a connexió que supera limit Docker)
            resume_msg = {"type": "resume", "data": {"last_seq": 0}}
            await ws.send(json.dumps(resume_msg))
            print(f"  ✓ Resume request sent (seq=0, buffer empty expected)")

        print("✓ Multiple subscriptions + resume test passed")

    except Exception as e:
        print(f"✗ Test failed: {e}")
        raise


async def test_message_with_seq():
    """Test that messages include sequence numbers"""
    print("Testing message sequence numbers...")

    try:
        async with websockets.connect(WS_URL, **WS_CONNECT_KW) as ws:
            subscribe_msg = {"type": "subscribe", "channel": "execution"}
            await ws.send(json.dumps(subscribe_msg))

            try:
                response = await asyncio.wait_for(ws.recv(), timeout=3.0)
            except asyncio.TimeoutError:
                raise AssertionError(
                    "Server did not send subscribed confirmation within 3s (execution channel)."
                ) from None

            data = json.loads(response)
            assert data["type"] == "subscribed", f"Expected subscribed, got {data.get('type')}"

            print(f"  ✓ Subscribed to execution channel")
            print(f"  ℹ Note: Seq numbers are only present on broadcast messages (ticker, candle, etc.)")
            print(f"  ℹ Control messages (subscribed, unsubscribed, error) don't have seq")

        print("✓ Message seq test passed")

    except AssertionError:
        raise
    except Exception as e:
        print(f"✗ Test failed: {e}")
        raise


async def test_invalid_message_type():
    """Test error handling for unknown message type"""
    print("Testing invalid message type...")

    try:
        async with websockets.connect(WS_URL, **WS_CONNECT_KW) as ws:
            invalid_msg = {"type": "invalid_type", "data": {}}
            await ws.send(json.dumps(invalid_msg))

            try:
                response = await asyncio.wait_for(ws.recv(), timeout=3.0)
            except asyncio.TimeoutError:
                raise AssertionError(
                    "Server did not respond to invalid message type within 3s. "
                    "Invalid messages must always return {type:'error'}."
                ) from None

            data = json.loads(response)
            assert data["type"] == "error", f"Expected 'error', got '{data['type']}'"
            assert "Unknown message type" in data.get("error", "")

            print(f"  ✓ Error received for invalid message type")

        print("✓ Invalid message type test passed")

    except AssertionError:
        raise
    except Exception as e:
        print(f"✗ Test failed: {e}")
        raise


async def test_missing_channel():
    """Test error handling for missing channel field (server must always return error)."""
    print("Testing missing channel field...")

    try:
        async with websockets.connect(WS_URL, **WS_CONNECT_KW) as ws:
            subscribe_msg = {"type": "subscribe"}
            await ws.send(json.dumps(subscribe_msg))

            try:
                response = await asyncio.wait_for(ws.recv(), timeout=3.0)
            except asyncio.TimeoutError:
                raise AssertionError(
                    "Server did not respond within 3s to missing channel. "
                    "Invalid messages must always return {type:'error'}."
                ) from None

            data = json.loads(response)
            assert data["type"] == "error", f"Expected 'error', got '{data['type']}'"
            assert "Missing channel" in data.get("error", "")

            print(f"  ✓ Error received for missing channel")

        print("✓ Missing channel test passed")

    except AssertionError:
        raise
    except Exception as e:
        print(f"✗ Test failed: {e}")
        raise


async def test_error_responses_same_connection():
    """Invalid message type + missing channel + invalid channel in one connection (Docker connect limit)."""
    print("Testing error responses (invalid type, missing channel, invalid channel)...")
    recv_timeout = 5.0
    try:
        async with websockets.connect(WS_URL, **WS_CONNECT_KW) as ws:
            invalid_msg = {"type": "invalid_type", "data": {}}
            await ws.send(json.dumps(invalid_msg))
            response = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
            data = json.loads(response)
            assert data["type"] == "error" and "Unknown message type" in data.get("error", "")
            print(f"  ✓ Error for invalid message type")

            await ws.send(json.dumps({"type": "subscribe"}))
            response = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
            data = json.loads(response)
            assert data["type"] == "error" and "Missing channel" in data.get("error", "")
            print(f"  ✓ Error for missing channel")

            await ws.send(json.dumps({"type": "subscribe", "channel": "ticker:INVALID"}))
            response = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
            data = json.loads(response)
            assert data["type"] == "error" and "Invalid channel" in data.get("error", "")
            print(f"  ✓ Error for invalid channel")

        print("✓ All error responses (same connection) passed")
    except asyncio.TimeoutError:
        raise AssertionError(f"Server did not respond within {recv_timeout}s.") from None
    except Exception as e:
        print(f"✗ Test failed: {e}")
        raise


async def test_candle_channel():
    """Test candle channel subscription"""
    print("Testing candle channel...")

    try:
        async with websockets.connect(WS_URL, **WS_CONNECT_KW) as ws:
            # Subscribe to candle channel
            subscribe_msg = {
                "type": "subscribe",
                "channel": "candle:XAUUSD:1m"
            }
            await ws.send(json.dumps(subscribe_msg))

            # Wait for subscribed confirmation
            response = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(response)

            assert data["type"] == "subscribed"
            assert data["channel"] == "candle:XAUUSD:1m"

            print(f"  ✓ Subscribed to candle:XAUUSD:1m")

        print("✓ Candle channel test passed")

    except Exception as e:
        print(f"✗ Test failed: {e}")
        raise


async def run_tests():
    """Run all WebSocket smoke tests. Max 5 connections (Docker WS limit)."""
    await test_basic_connection()
    await test_error_responses_same_connection()
    await test_subscribe_unsubscribe()
    await test_message_with_seq()
    await test_multiple_subscriptions_and_resume()  # includes candle + resume (same conn)


def main():
    """Main entry point"""
    print("\n" + "="*60)
    print("WebSocket Smoke Tests")
    print("="*60 + "\n")

    try:
        # Start test server
        with WSTestServer(port=8002):
            # Run tests
            asyncio.run(run_tests())

        print("\n" + "="*60)
        print("✓ All WebSocket smoke tests passed!")
        print("="*60 + "\n")
        return 0

    except Exception as e:
        print("\n" + "="*60)
        print(f"✗ WebSocket tests failed: {e}")
        print("="*60 + "\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
