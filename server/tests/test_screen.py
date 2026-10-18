import asyncio
import io
import time

from PIL import Image

from hidagent.screen import Screen


def frame(color):
    buffer = io.BytesIO()
    Image.new("RGB", (100, 200), color).save(buffer, "JPEG")
    return buffer.getvalue()


def test_repeated_identical_video_frames_do_not_force_maximum_wait():
    async def scenario():
        screen = Screen()
        screen.frame = frame("white")

        async def duplicate_frames():
            while True:
                screen.updated = time.time()
                screen.frame = bytes(bytearray(screen.frame))
                await asyncio.sleep(.01)

        task = asyncio.create_task(duplicate_frames())
        try:
            started = time.monotonic()
            await screen.settled(quiet=.05, least=.01, most=.3)
            assert .04 <= time.monotonic() - started < .2
        finally:
            task.cancel()
    asyncio.run(scenario())


def test_real_content_change_restarts_quiet_window():
    async def scenario():
        screen = Screen()
        screen.frame = frame("white")

        async def change():
            await asyncio.sleep(.03)
            screen.frame = frame("black")
            screen.updated = time.time()

        task = asyncio.create_task(change())
        started = time.monotonic()
        await screen.settled(quiet=.06, least=.01, most=.4)
        assert time.monotonic() - started >= .10
        await task
    asyncio.run(scenario())


def test_animation_still_obeys_maximum_wait():
    async def scenario():
        screen = Screen()
        white, black = frame("white"), frame("black")
        screen.frame = white

        async def animate():
            while True:
                screen.frame = black if screen.frame == white else white
                screen.updated = time.time()
                await asyncio.sleep(.04)

        task = asyncio.create_task(animate())
        try:
            started = time.monotonic()
            await screen.settled(quiet=.15, least=.01, most=.2)
            assert .19 <= time.monotonic() - started < .4
        finally:
            task.cancel()
    asyncio.run(scenario())
