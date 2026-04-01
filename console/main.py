"""
Operator console — streams audio to the Gibberly backend.

Usage:
  python -m console.main --mode file --file audio/test.wav
  python -m console.main --mode mic [--device 0]
  python -m console.main --list-devices
"""

import argparse
import asyncio
import json
import sys
import time

import websockets
from websockets.exceptions import ConnectionClosedError

from console.audio import FileAudioSource, MicAudioSource, list_devices
from console.ui import qr_lines, format_status


def parse_args():
    p = argparse.ArgumentParser(description="Gibberly operator console")
    p.add_argument("--backend", default="ws://localhost:8000", help="Backend WebSocket base URL")
    p.add_argument("--mode", choices=["mic", "file"], default="mic")
    p.add_argument("--file", help="Path to WAV file (--mode file)")
    p.add_argument("--device", type=int, default=None, help="Audio input device index")
    p.add_argument("--list-devices", action="store_true")
    return p.parse_args()


async def run(args):
    if args.list_devices:
        for d in list_devices():
            print(f"  [{d['index']}] {d['name']} ({d['channels']} ch)")
        return

    uri = f"{args.backend}/ws/stream"
    print(f"Connecting to {uri} …")

    async with websockets.connect(uri) as ws:
        # Receive session info
        raw = await ws.recv()
        session = json.loads(raw)
        print(f"\nSession: {session['session_id']}")

        listener_url = session["listener_url"]
        print(f"Listener URL: {listener_url}\n")
        for line in qr_lines(listener_url):
            print(line)

        print("\nStreaming audio. Press Ctrl+C to stop.\n")

        start_time = time.time()
        last_phrase = ""

        # Audio source
        if args.mode == "file":
            if not args.file:
                print("--file is required for --mode file")
                sys.exit(1)
            source = FileAudioSource(args.file)
        else:
            source = MicAudioSource(device=args.device)

        sleep_s = getattr(source, "sleep_s", 0)

        async def stream_chunks():
            for chunk in source.chunks():
                await ws.send(chunk)
                elapsed = int(time.time() - start_time)
                status = format_status(
                    connected=True,
                    listener_count=0,
                    elapsed_s=elapsed,
                    last_phrase=last_phrase,
                )
                print(f"\r{status}", end="", flush=True)
                if sleep_s:
                    await asyncio.sleep(sleep_s)

        try:
            await stream_chunks()
        except (KeyboardInterrupt, ConnectionClosedError):
            pass
        finally:
            print("\nStopping session…")


def main():
    args = parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
