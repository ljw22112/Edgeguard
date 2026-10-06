"""TCP proxy that adds one-way delay (and jitter) to emulate a WAN link.

    python tools/wan_proxy.py --listen 17579 --target 127.0.0.1:7579 --delay-ms 25 --jitter-ms 5

Every chunk is held for delay(+jitter) in each direction, preserving order,
so an HTTP request/response pair pays roughly one round trip.
Stop the process to emulate a WAN outage.
"""
import argparse
import asyncio
import random
import time


async def pump(reader, writer, delay, jitter):
    q: asyncio.Queue = asyncio.Queue()

    async def sender():
        while True:
            due, data = await q.get()
            if data is None:
                break
            wait = due - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            writer.write(data)
            await writer.drain()
        writer.close()

    task = asyncio.create_task(sender())
    last_due = 0.0
    try:
        while data := await reader.read(65536):
            d = max(0.0, delay + random.uniform(-jitter, jitter))
            due = max(time.monotonic() + d, last_due)      # never reorder bytes
            last_due = due
            await q.put((due, data))
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    await q.put((0, None))
    await task


async def main(a):
    host, port = a.target.split(":")
    delay, jitter = a.delay_ms / 1000, a.jitter_ms / 1000

    async def handle(cr, cw):
        try:
            sr, sw = await asyncio.open_connection(host, int(port))
        except OSError:
            cw.close()
            return
        await asyncio.gather(pump(cr, sw, delay, jitter), pump(sr, cw, delay, jitter),
                             return_exceptions=True)

    srv = await asyncio.start_server(handle, "0.0.0.0", a.listen)
    print(f"WAN proxy :{a.listen} -> {a.target}  one-way {a.delay_ms}+-{a.jitter_ms} ms", flush=True)
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--delay-ms", type=float, default=25)
    ap.add_argument("--jitter-ms", type=float, default=5)
    asyncio.run(main(ap.parse_args()))
