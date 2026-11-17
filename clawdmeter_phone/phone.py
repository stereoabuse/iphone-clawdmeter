"""Talk to the Safari page on the iPhone over USB (Web Inspector via usbmux)."""

import asyncio
import json
import logging

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.webinspector import SAFARI, WebinspectorService

from . import apple_service
from .page import build_page, inject_js

log = logging.getLogger(__name__)
CHUNK = 8000
TIMEOUT = 5


class PhoneNotReady(Exception):
    pass


class Phone:
    def __init__(self):
        self.inspector: WebinspectorService | None = None
        self.session = None
        self.opened = []  # sessions on this connection; the library polls for each until cancelled
        self.html, self.version = build_page()

    async def close(self):
        for s in self.opened:
            s._receive_task.cancel()
        self.opened = []
        if self.inspector is not None:
            for part in (self.inspector, self.inspector.lockdown):
                try:
                    await part.close()
                except Exception:
                    pass
        self.inspector = self.session = None

    async def _drop(self, s):
        """Stop a session's polling and free its page, so a later probe can attach to it again."""
        s._receive_task.cancel()
        self.opened.remove(s)
        p = s.protocol
        await asyncio.wait_for(self.inspector.teardown_inspector_socket(p.id_, p.app.id_, p.page.id_), TIMEOUT)

    async def _connect(self):
        try:
            lockdown = await create_using_usbmux()
        except Exception as e:
            if "Usbmuxd" in type(e).__name__:  # Apple's USB service isn't running
                note = await asyncio.to_thread(apple_service.ensure_running)
                if note:
                    log.info("%s", note)
            raise PhoneNotReady(f"no phone over USB ({type(e).__name__}); is it plugged in and unlocked?") from e
        self.inspector = WebinspectorService(lockdown=lockdown)
        await self.inspector.connect()

    async def _find_visible_page(self):
        pages = await asyncio.wait_for(self.inspector.get_open_application_pages(timeout=2), 10)
        for ap in pages:
            if ap.application.bundle != SAFARI:
                continue
            s = await asyncio.wait_for(self.inspector.inspector_session(ap.application, ap.page), TIMEOUT)
            self.opened.append(s)
            await asyncio.wait_for(s.runtime_enable(), TIMEOUT)
            vis = await asyncio.wait_for(s.runtime_evaluate("document.visibilityState", return_by_value=True), TIMEOUT)
            if vis == "visible":
                return ap, s
            await self._drop(s)
        raise PhoneNotReady("no visible Safari tab (unlock the phone and open Safari)")

    async def eval(self, js: str):
        # A navigation (even a manual refresh) can orphan the session without an error; never wait forever.
        return await asyncio.wait_for(self.session.runtime_evaluate(js, return_by_value=True), TIMEOUT)

    async def ensure(self):
        """Connect, find the on-screen Safari tab, and make sure our page is loaded in it."""
        if self.inspector is None:
            await self._connect()
        if self.session is not None:
            ping = await self.eval("window.__cm ? window.__cm.ping() : 'none|' + document.visibilityState")
            if ping and ping.endswith("|visible"):
                if ping.split("|")[0] != self.version:
                    await self._inject()
                return
            await self._drop(self.session)
            self.session = None
        _, self.session = await self._find_visible_page()
        if await self.eval("window.__cm ? window.__cm.v : ''") != self.version:
            await self._inject()

    async def _reconnect(self):
        await self.close()
        await self._connect()
        _, self.session = await self._find_visible_page()

    async def _inject(self):
        # Web Inspector drops messages much over ~16 KB, so send the page in pieces.
        log.info("loading page onto phone (version %s)", self.version)
        # A real navigation first, so no older copy of the page keeps running timers.
        # Navigating can swap Safari's page target, so reconnect afterwards.
        try:
            await self.eval("location.replace('about:blank');0")
        except (asyncio.TimeoutError, Exception):
            pass
        await asyncio.sleep(1.5)
        await self._reconnect()
        await self.eval("window.__cmBuf=[];0")
        for i in range(0, len(self.html), CHUNK):
            await self.eval(f"window.__cmBuf.push({json.dumps(self.html[i:i + CHUNK])});0")
        await self.eval(inject_js())

    async def push(self, state: dict):
        return await self.eval(f"window.__cm.update({json.dumps(state)})")

    async def drain(self) -> list[dict]:
        raw = await self.eval("window.__cm ? window.__cm.drain() : '[]'")
        try:
            return json.loads(raw or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
