"""Cycle the phone through demo states (idle, working, alert, done) without the daemon.

uv run python -m tools.demo [steps]     default 8 steps, 6 s each; Ctrl+C to stop
Stop the daemon first: both drive the same page. Taps on the phone are printed, not acted on.
"""

import asyncio
import sys
import time

from clawdmeter_phone.__main__ import local_utc_offset, single_instance
from clawdmeter_phone.phone import Phone


def states(t0: float) -> list[dict]:
    base = {"connected": True, "ok": True, "sr_at": t0 + 7400, "wr_at": t0 + 300000}
    return [
        {**base, "s": 35, "w": 22, "n": 1, "working": False, "e": "s", "es": 1, "alert": None},
        {**base, "s": 36, "w": 22, "n": 1, "working": True, "e": "p", "es": 2, "alert": None},
        {**base, "s": 61, "w": 30, "n": 2, "working": True, "e": "p", "es": 3,
         "alert": {"id": "demo", "title": "Permission needed", "m": "Claude needs your permission to use Bash",
                   "dir": "demo-project", "opts": [], "primary": False}},
        {**base, "s": 62, "w": 30, "n": 2, "working": False, "e": "s", "es": 4, "alert": None},
    ]


async def main(steps: int):
    phone = Phone()
    demo = states(time.time())
    try:
        for i in range(steps):
            await phone.ensure()
            st = demo[i % len(demo)]
            # The phone's own clock is wrong, so the page needs the PC's time and timezone.
            await phone.push({**st, "t": time.time(), "tz": local_utc_offset()})
            print("->", "alert" if st["alert"] else ("working" if st["working"] else "idle"))
            await asyncio.sleep(6)
            for msg in await phone.drain():
                print("   tap:", msg)
    finally:
        await phone.close()


if __name__ == "__main__":
    lock = single_instance()  # exits if the daemon is running; also keeps it from starting meanwhile
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 8))
