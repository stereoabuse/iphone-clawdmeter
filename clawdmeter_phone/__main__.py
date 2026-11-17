"""Run the iPhone Clawdmeter: uv run python -m clawdmeter_phone"""

import asyncio
import logging
import msvcrt
import sys
import time

from . import keys
from .activity import Activity, LogTail
from .hook import DATA_DIR, LOG
from .phone import Phone, PhoneNotReady
from .usage import UsagePoller

log = logging.getLogger("clawdmeter")
HEARTBEAT = 20


def local_utc_offset() -> int:
    return -(time.altzone if time.localtime().tm_isdst > 0 else time.timezone)


def single_instance():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = open(DATA_DIR / "daemon.lock", "w")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        sys.exit("iphone-clawdmeter is already running")
    return f


def handle(msg: dict, activity: Activity):
    if msg.get("reply"):
        # Typing the answer and pressing Enter sends the same reply as clicking it.
        # (The app's Ctrl+Enter shortcut ignored synthesized keys when tested.)
        if not (keys.type_text(str(msg["reply"])) and keys.press("enter")):
            log.warning("phone reply not typed (is the PC locked?): %s", msg["reply"])
            return
        log.info("phone reply: %s", msg["reply"])
        activity.dismiss(msg.get("id"))
    k = msg.get("key")
    if k in keys.ACTIONS:
        if not keys.press(keys.ACTIONS[k]):
            log.warning("phone key not sent (is the PC locked?): %s", k)
            return
        log.info("phone key: %s", k)
        if k == "reject":
            activity.interrupt()
        if msg.get("id"):
            activity.dismiss(msg["id"])


async def poll_usage(usage: UsagePoller, now: float):
    try:
        u = await asyncio.to_thread(usage.poll, now)
        log.info("usage: %s", {k: u.get(k) for k in ("ok", "s", "w", "err", "stale")})
    except Exception as e:
        log.warning("usage poll failed: %r", e)


async def run():
    activity, tail, usage, phone = Activity(), LogTail(LOG), UsagePoller(), Phone()
    last_sent, last_sent_at, last_problem, polling = None, 0.0, None, None
    while True:
        now = time.time()
        try:
            lines = tail.read()
        except OSError:  # a hook has the log open; read it next time round
            lines = []
        for line in lines:
            try:
                activity.ingest(line)
            except Exception as e:
                log.warning("skipped a bad event line: %r", e)
        if usage.due(now) and (polling is None or polling.done()):
            polling = asyncio.create_task(poll_usage(usage, now))  # in the background, so a slow poll can't stall the phone
        try:
            await phone.ensure()
            for msg in await phone.drain():
                handle(msg, activity)
            state = {"connected": True, **usage.last, **activity.snapshot(now)}
            if state != last_sent or now - last_sent_at > HEARTBEAT:
                await phone.push({**state, "t": time.time(), "tz": local_utc_offset()})
                last_sent, last_sent_at = state, now
            if last_problem:
                log.info("phone connected")
                last_problem = None
            await asyncio.sleep(0.25)
        except PhoneNotReady as e:
            if str(e) != last_problem:
                log.warning("%s", e)
                last_problem = str(e)
            last_sent = None
            await phone.close()
            await asyncio.sleep(5)
        except Exception as e:
            if repr(e) != last_problem:
                log.warning("phone link dropped: %r", e)
                last_problem = repr(e)
            last_sent = None
            await phone.close()
            await asyncio.sleep(3)


def main():
    lock = single_instance()  # noqa: F841 (held for the process lifetime)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(DATA_DIR / "daemon.log", encoding="utf-8")],
    )
    for noisy in ("pymobiledevice3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    log.info("iphone-clawdmeter starting; data in %s", DATA_DIR)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
