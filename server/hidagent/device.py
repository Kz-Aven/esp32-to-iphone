"""TCP link to the HID bridge board (see firmware/hid_bridge)."""

import asyncio
import logging
import time

log = logging.getLogger(__name__)


class DeviceError(RuntimeError):
    pass


class Device:
    """Accepts one board connection and sends it commands, one at a time."""

    def __init__(self):
        self._reader = self._writer = None
        self._lock = asyncio.Lock()
        self._last = self._beat = 0.0
        self.links = 0  # bumped on every (re)connect, so gestures know to release and re-home

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def serve(self, host: str, port: int):
        return await asyncio.start_server(self._accept, host, port)

    async def _accept(self, reader, writer):
        # newer firmware greets with "hello <last reset reason> <uptime ms>": read it before any command
        try:
            hello = (await asyncio.wait_for(reader.readline(), 1)).decode().strip()
        except (OSError, asyncio.TimeoutError):
            hello = ""
        if self.connected:
            self._writer.close()
        self._reader, self._writer = reader, writer
        self.links += 1
        self._last = self._beat = time.time()  # fresh link: nothing to keep awake yet
        log.info("board connected from %s %s", writer.get_extra_info("peername"), hello)

    async def wait_connected(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while not self.connected and time.time() < deadline:
            await asyncio.sleep(0.2)
        return self.connected

    @staticmethod
    def _timeout(command: str) -> float:
        """Seconds the board may take: Wi-Fi replies need up to ~2 s at p99, moves are paced
        (10 units per 8 ms), typing is per character."""
        name, _, arg = command.partition(" ")
        if name == "move":
            return 5 + max(abs(int(n)) for n in arg.split()) / 10 * 0.012
        if name == "type":
            return 5 + 0.1 * len(arg)
        if name == "ping":
            return 8  # an idle check: tolerate a Wi-Fi hiccup rather than drop a healthy board
        return 5

    async def send(self, command: str) -> None:
        if not self.connected:
            raise DeviceError("board not connected")
        timeout = self._timeout(command)
        async with self._lock:
            if not self.connected:  # a preceding command may have closed the link while this one waited
                raise DeviceError("board not connected")
            reader, writer = self._reader, self._writer
            started = time.time()
            try:
                writer.write(command.encode() + b"\n")
                await writer.drain()
                reply = (await asyncio.wait_for(reader.readline(), timeout)).decode().strip()
            except asyncio.CancelledError:
                writer.close()  # discard the pending reply before another command can consume it
                raise
            except (OSError, asyncio.TimeoutError) as e:
                writer.close()  # close this command's connection, not a replacement accepted while waiting
                raise DeviceError(f"board link lost during '{command[:30]}': {e!r}") from e
        self._beat = time.time()  # last reply of any kind
        if command != "ping":
            self._last = self._beat  # last real command: the phone's idle time
            log.debug("%s -> %s (%.0f ms)", command, reply, (time.time() - started) * 1000)
        if reply != "ok":
            raise DeviceError(reply or "board disconnected")

    async def keep_awake(self, idle: float = 25, heartbeat: float = 2, screen=None) -> None:
        """While idle: ping every few seconds, so a board that was unplugged or hung shows as gone within
        seconds (not at the next command), and nudge the pointer now and then so the phone does not auto-lock."""
        while True:
            await asyncio.sleep(heartbeat)
            if not self.connected or time.time() - self._beat < heartbeat:
                continue
            try:
                # nudge only a phone that is awake and mirroring: moving a sleeping phone's pointer can stall the
                # board on its USB link, and there is nothing to keep awake anyway
                if time.time() - self._last > idle and (screen is None or screen.live):
                    await self.send("move 1 0")
                    await self.send("move -1 0")
                else:
                    await self.send("ping")
            except DeviceError as e:
                log.info("board gone: %s", e)
