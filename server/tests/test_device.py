import asyncio

import pytest

from hidagent.device import Device, DeviceError


def test_timeout_grows_with_move_distance_and_text_length():
    assert Device._timeout("click") == 5
    assert Device._timeout("move 1000 -20") > Device._timeout("move 10 10") >= 5
    assert Device._timeout("type " + "x" * 40) > Device._timeout("type hi")


def test_send_without_board_fails_fast():
    with pytest.raises(DeviceError, match="not connected"):
        asyncio.run(Device().send("ping"))


def test_round_trip_with_a_fake_board():
    async def scenario():
        device = Device()
        server = await device.serve("127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        async def board():  # answers every command like the firmware does
            while line := await reader.readline():
                writer.write(b"ok\n" if line.strip() != b"bad" else b"err unknown command\n")
                await writer.drain()

        task = asyncio.create_task(board())
        assert await device.wait_connected(2)
        await device.send("ping")
        with pytest.raises(DeviceError, match="unknown command"):
            await device.send("bad")
        assert device.links == 1
        task.cancel()
        writer.close()
        server.close()

    asyncio.run(scenario())


def test_old_request_failure_does_not_close_replacement_connection():
    class Writer:
        def __init__(self):
            self.closed = False
        def is_closing(self): return self.closed
        def close(self): self.closed = True
        def write(self, data): pass
        async def drain(self): pass
        def get_extra_info(self, key): return ("fake-board", 7300)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class OldReader:
            async def readline(self):
                entered.set()
                await release.wait()
                raise OSError("old connection lost")

        class NewReader:
            def __init__(self): self.first = True
            async def readline(self):
                if self.first:
                    self.first = False
                    return b"hello power-on 123\n"
                return b"ok\n"

        device = Device()
        old, replacement = Writer(), Writer()
        device._reader, device._writer = OldReader(), old
        pending = asyncio.create_task(device.send("ping"))
        await entered.wait()
        await device._accept(NewReader(), replacement)
        release.set()
        with pytest.raises(DeviceError, match="old connection lost"):
            await pending
        assert old.closed
        assert device.connected and not replacement.closed
        await device.send("ping")

    asyncio.run(scenario())


def test_cancelled_command_closes_link_before_the_next_command():
    class Writer:
        closed = False
        def is_closing(self): return self.closed
        def close(self): self.closed = True
        def write(self, data): pass
        async def drain(self): pass

    async def scenario():
        entered = asyncio.Event()

        class Reader:
            async def readline(self):
                entered.set()
                await asyncio.Event().wait()

        device = Device()
        device._reader, device._writer = Reader(), Writer()
        job = asyncio.create_task(device.send("press"))
        await entered.wait()
        queued = asyncio.create_task(device.send("click"))
        await asyncio.sleep(0)  # the next command is already waiting for the lock
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        assert not device.connected
        with pytest.raises(DeviceError, match="not connected"):
            await asyncio.wait_for(queued, .5)

    asyncio.run(scenario())
