"""Isolated casual boxing relay/signaling. No webcam video is accepted.

python scripts/serve_boxing.py --host 127.0.0.1 --port 8790
Public deployment must put HTTPS/WSS proxy in front and set --origin.
"""
import argparse
import asyncio
import json
import re
import time
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

rooms = {}

async def handler(ws):
    room = None
    slot = None
    try:
        first = json.loads(await asyncio.wait_for(ws.recv(), 10))
        name = first.get('room', '')
        if first.get('type') != 'join' or not isinstance(name, str) or not re.fullmatch(r'[A-Z0-9_-]{3,24}', name):
            await ws.send(json.dumps({'type': 'error', 'message': 'Código de sala inválido'}))
            return
        room = rooms.setdefault(name, {})
        if len(room) >= 2:
            await ws.send(json.dumps({'type': 'error', 'message': 'Sala cheia • dois jogadores por ringue'}))
            return
        slot = 0 if 0 not in room else 1
        room[slot] = ws
        await ws.send(json.dumps({'type': 'joined', 'room': name, 'slot': slot}))
        if len(room) == 2:
            for client in list(room.values()):
                await client.send(json.dumps({'type': 'ready'}))
        window = time.monotonic()
        count = 0
        last_seq = -1
        async for payload in ws:
            now = time.monotonic()
            if now-window > 1:
                window, count = now, 0
            count += 1
            if count > 90:
                await ws.close(1008, 'rate limit')
                break
            if not isinstance(payload, str):
                await ws.close(1003, 'JSON only')
                break
            msg = json.loads(payload)
            if not isinstance(msg, dict):
                continue
            if msg.get('type') == 'packet':
                seq = msg.get('seq')
                if not isinstance(seq, int) or seq <= last_seq:
                    continue
                data = msg.get('data', {})
                if not isinstance(data, dict) or data.get('type') not in ({'state'} if slot == 0 else {'input'}):
                    continue
                last_seq = seq
            elif msg.get('type') != 'signal':
                continue
            peer = room.get(1-slot)
            if peer:
                await peer.send(payload)
    except (ConnectionClosed, asyncio.TimeoutError, ValueError, TypeError, AttributeError):
        pass
    finally:
        if room is not None and slot is not None and room.get(slot) is ws:
            del room[slot]
            peer = room.get(1-slot)
            if peer:
                try:
                    await peer.send(json.dumps({'type': 'peer-left'}))
                except ConnectionClosed:
                    pass
            else:
                rooms.pop(name, None)

async def main(args):
    async with serve(handler, args.host, args.port, origins=args.origin or None,
                     max_size=32768, max_queue=4, compression=None,
                     ping_interval=15, ping_timeout=15):
        print(f'CORNER relay ws://{args.host}:{args.port}', flush=True)
        await asyncio.Future()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--origin', action='append')
    asyncio.run(main(parser.parse_args()))
