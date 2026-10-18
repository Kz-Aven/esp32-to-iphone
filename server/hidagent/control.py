"""Observed, single-use device actions for external agents. No model calls."""

import base64
import io
import time
import uuid

from PIL import Image
from pypinyin import lazy_pinyin

from . import vision


class Controls:
    def __init__(self, phone, screen):
        self.phone, self.screen = phone, screen
        self.ticket = None
        self.job = None

    def invalidate(self):
        self.ticket = None

    def capture(self):
        if not self.screen.live or not self.screen.frame:
            raise ValueError("no live screen; reconnect iPhone Screen Mirroring")
        frame = self.screen.frame
        with Image.open(io.BytesIO(frame)) as image:
            width, height = image.size
        return frame, width, height

    def observation(self):
        frame, width, height = self.capture()
        token = uuid.uuid4().hex
        self.ticket = (token, time.monotonic(), frame, width, height)
        return {"screen_id": token, "width": width, "height": height,
                "frame_received_at": self.screen.updated, "expires_in_seconds": 30,
                "coordinate_spaces": {"normalized": "0..1", "pixels": "0..width-1, 0..height-1"},
                "image_base64": base64.b64encode(frame).decode()}

    def consume(self, screen_id):
        ticket = self.ticket
        self.invalidate()
        if ticket is None or ticket[0] != screen_id:
            raise ValueError("invalid or consumed screen_id; observe again before acting")
        if time.monotonic() - ticket[1] > 30:
            raise ValueError("screen_id expired; observe again")
        frame, width, height = self.capture()
        if (width, height) != ticket[3:] or vision.changed(ticket[2], frame):
            raise ValueError("screen changed since observation; observe again")
        return ticket[2], width, height

    async def perform(self, request):
        began = time.perf_counter()
        before, width, height = self.consume(request.screen_id)

        def point(x, y):
            if request.coordinate_space == "pixels":
                if x > width - 1 or y > height - 1:
                    raise ValueError("pixel coordinate outside observed image")
                return x / (width - 1), y / (height - 1)
            if x > 1 or y > 1:
                raise ValueError("normalized coordinates must be 0..1, not 0..1000")
            return x, y

        data = request.model_dump()
        name = request.action
        extra = {}
        if request.repeat != 1 and (name != "key" or request.text.lower() not in ("backspace", "left", "right")):
            raise ValueError("repeat>1 only supports editing keys backspace/left/right; never repeat Enter")
        # Validate and prepare everything before issuing any HID events.
        if name in ("tap", "point", "scroll"):
            if request.x is None or request.y is None:
                raise ValueError("x and y required")
            x, y = point(request.x, request.y)
        if name == "swipe":
            if any(data[k] is None for k in ("x1", "y1", "x2", "y2")):
                raise ValueError("both swipe points required")
            x1, y1 = point(request.x1, request.y1)
            x2, y2 = point(request.x2, request.y2)
        if name == "type":
            if (not request.text or not request.text.isascii()
                    or any(ord(c) < 32 or ord(c) == 127 for c in request.text)):
                raise ValueError("type requires printable ASCII; use compose_chinese for Chinese phrases")
        if name == "compose_chinese":
            if not request.text or not all("\u4e00" <= c <= "\u9fff" for c in request.text) or len(request.text) > 60:
                raise ValueError("compose_chinese needs 1..60 Chinese characters; type punctuation separately")
            if request.input_mode != "pinyin":
                raise ValueError("observe and confirm Chinese Pinyin input mode first; set input_mode=pinyin")
            extra = {"expected_text": request.text, "typed_ascii": "".join(lazy_pinyin(request.text)),
                     "requires_candidate_selection": True, "submitted": False,
                     "next_step": "Select candidates from image; verify final Chinese before a separate send."}
        if name == "key":
            keys = request.text.lower().split("+")
            known = {"enter", "esc", "tab", "backspace", "space", "up", "down", "left", "right",
                     "cmd", "ctrl", "alt", "shift"}
            if not request.text or not request.text.isascii() or any(k not in known and
                    not (len(k) == 1 and 32 <= ord(k) < 127) for k in keys):
                raise ValueError("unsupported keyboard combination")
            extra.update(repeat_requested=request.repeat, repeat_completed=0)

        ready = time.perf_counter()
        started, acknowledged, error = time.time(), False, None
        try:
            if name == "tap": await self.phone.tap_verified(x, y)
            elif name == "point":
                located = await self.phone.point_verified(x, y)
                extra["pointer"] = {"x": located[0], "y": located[1]}
            elif name == "swipe": await self.phone.swipe(x1, y1, x2, y2)
            elif name == "scroll": await self.phone.scroll(x, y, request.lines)
            elif name == "type": await self.phone.type(request.text)
            elif name == "compose_chinese": await self.phone.type(extra["typed_ascii"])
            elif name == "key":
                for _ in range(request.repeat):
                    await self.phone.key(request.text.lower())
                    extra["repeat_completed"] += 1
            elif name == "home": await self.phone.go_home()
            elif name == "back": await self.phone.go_back()
            acknowledged = True
        except (RuntimeError, OSError) as exc:
            error = str(exc)

        device_done = time.perf_counter()
        fresh = await self.screen.fresh(started, 1.5)
        fresh_done = time.perf_counter()
        await self.screen.settled(least=0.3, most=2)
        settled_done = time.perf_counter()
        try:
            shot = self.observation()
        except ValueError:
            self.invalidate()
            shot = {"screen_id": None, "image_base64": None}
        captured = time.perf_counter()
        timings = {"validation": ready - began, "device_and_pointer": device_done - ready,
                   "wait_fresh": fresh_done - device_done, "wait_settled": settled_done - fresh_done,
                   "capture": captured - settled_done, "total": captured - began}
        return {**shot, "command_acknowledged": acknowledged, "fresh": bool(fresh),
                "changed": vision.changed(before, self.screen.frame) if fresh else None,
                "effect_verified": False, "error": error, "action_may_have_executed": True,
                "verification_required": "Inspect the returned image. Never retry a send automatically.",
                "timing_ms": {key: round(value * 1000, 1) for key, value in timings.items()}, **extra}
