import asyncio
import base64
import io
import time
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from hidagent.app import ControlAction
from hidagent.control import Controls
from hidagent.phone import Phone


def jpeg(color="white"):
    buffer = io.BytesIO()
    Image.new("RGB", (101, 201), color).save(buffer, "JPEG")
    return buffer.getvalue()


class Screen:
    live = True
    updated = time.time()
    frame = jpeg()
    new_frame = True

    async def fresh(self, *args): return self.frame if self.new_frame else None
    async def settled(self, **kwargs): pass


class FakePhone:
    def __init__(self): self.calls = []
    async def point_verified(self, x, y):
        self.calls.append(("point", x, y))
        return x, y
    async def tap_verified(self, x, y): self.calls.append(("tap", x, y))
    async def type(self, text): self.calls.append(("type", text))
    async def key(self, text): self.calls.append(("key", text))


def test_pixel_coordinates_return_evidence_and_single_use_token():
    phone, screen = FakePhone(), Screen()
    control = Controls(phone, screen)
    token = control.observation()["screen_id"]
    request = ControlAction(action="tap", screen_id=token, coordinate_space="pixels", x=50, y=100)
    result = asyncio.run(control.perform(request))
    assert phone.calls == [("tap", .5, .5)]
    assert result["command_acknowledged"] and result["fresh"]
    assert result["effect_verified"] is False
    assert base64.b64decode(result["image_base64"]) == screen.frame
    assert result["screen_id"] != token
    with pytest.raises(ValueError, match="consumed"):
        asyncio.run(control.perform(request))
    assert len(phone.calls) == 1


@pytest.mark.parametrize("reason", ["expired", "changed", "normalized", "pixels"])
def test_bad_observations_and_coordinates_never_reach_hid(reason):
    phone, screen = FakePhone(), Screen()
    control = Controls(phone, screen)
    token = control.observation()["screen_id"]
    space, x = "normalized", .5
    if reason == "expired":
        t = control.ticket
        control.ticket = (t[0], time.monotonic() - 31, *t[2:])
    elif reason == "changed": screen.frame = jpeg("black")
    elif reason == "normalized": x = 500
    elif reason == "pixels": space, x = "pixels", 101
    with pytest.raises(ValueError):
        asyncio.run(control.perform(ControlAction(action="tap", screen_id=token,
                                                 coordinate_space=space, x=x, y=.5)))
    assert not phone.calls


def test_chinese_is_composition_only_and_requires_mode_confirmation():
    phone, screen = FakePhone(), Screen()
    control = Controls(phone, screen)
    token = control.observation()["screen_id"]
    with pytest.raises(ValueError, match="Pinyin"):
        asyncio.run(control.perform(ControlAction(action="compose_chinese", screen_id=token, text="谢谢分享")))
    token = control.observation()["screen_id"]
    result = asyncio.run(control.perform(ControlAction(action="compose_chinese", screen_id=token,
                                                       text="谢谢分享", input_mode="pinyin")))
    assert phone.calls == [("type", "xiexiefenxiang")]
    assert result["expected_text"] == "谢谢分享"
    assert result["requires_candidate_selection"] and result["submitted"] is False


@pytest.mark.parametrize("action,text", [("type", "你好"), ("type", "hello\n"),
                                         ("compose_chinese", "你好!"), ("key", "enter\nhome")])
def test_invalid_keyboard_input_cannot_send_protocol_lines(action, text):
    phone, screen = FakePhone(), Screen()
    control = Controls(phone, screen)
    with pytest.raises(ValueError):
        asyncio.run(control.perform(ControlAction(action=action, screen_id=control.observation()["screen_id"],
                                                 text=text, input_mode="pinyin")))
    assert not phone.calls


def test_uncertain_input_is_not_retried_and_unchanged_frame_is_not_verified():
    phone, screen = FakePhone(), Screen()
    screen.new_frame = False

    async def failing(text):
        phone.calls.append(("key", text))
        raise RuntimeError("connection lost after write")

    phone.key = failing
    control = Controls(phone, screen)
    result = asyncio.run(control.perform(ControlAction(action="key", text="enter",
                                                       screen_id=control.observation()["screen_id"])))
    assert phone.calls == [("key", "enter")]
    assert not result["command_acknowledged"] and not result["fresh"]
    assert result["changed"] is None and not result["effect_verified"]
    assert "connection lost" in result["error"] and result["action_may_have_executed"]


def test_repeated_edit_keys_return_one_observation_and_phase_timings():
    phone = FakePhone()
    control = Controls(phone, Screen())
    result = asyncio.run(control.perform(ControlAction(action="key", text="backspace", repeat=4,
                                                       screen_id=control.observation()["screen_id"])))
    assert phone.calls == [("key", "backspace")] * 4
    assert result["repeat_completed"] == result["repeat_requested"] == 4
    assert result["screen_id"] and result["image_base64"]
    assert set(result["timing_ms"]) == {"validation", "device_and_pointer", "wait_fresh",
                                       "wait_settled", "capture", "total"}
    assert all(value >= 0 for value in result["timing_ms"].values())


@pytest.mark.parametrize("key", ["enter", "space", "cmd+backspace"])
def test_repeat_cannot_batch_sends_or_other_actions(key):
    phone = FakePhone()
    control = Controls(phone, Screen())
    with pytest.raises(ValueError, match="never repeat Enter"):
        asyncio.run(control.perform(ControlAction(action="key", text=key, repeat=2,
                                                 screen_id=control.observation()["screen_id"])))
    assert not phone.calls


def test_partial_repeat_failure_stops_without_replaying():
    phone = FakePhone()

    async def fail_second(key):
        phone.calls.append(("key", key))
        if len(phone.calls) == 2:
            raise RuntimeError("lost ACK; key may have executed")

    phone.key = fail_second
    control = Controls(phone, Screen())
    result = asyncio.run(control.perform(ControlAction(action="key", text="backspace", repeat=5,
                                                       screen_id=control.observation()["screen_id"])))
    assert len(phone.calls) == 2
    assert result["repeat_completed"] == 1 and not result["command_acknowledged"]
    assert result["error"] and result["action_may_have_executed"]


def test_verified_tap_corrects_drift_and_never_clicks_when_pointer_unseen(tmp_path):
    commands = []

    async def send(command): commands.append(command)

    async def scenario(found):
        phone = Phone(SimpleNamespace(send=send), tmp_path / "calibration", Screen())
        phone.span, phone._pos = {"w": 400, "h": 800}, (200, 400)
        async def point(x, y): pass
        phone.point = point
        positions = iter(found)
        async def locate(near, **kwargs): return next(positions)
        phone._find_pointer = locate
        await phone.tap_verified(.5, .5)

    asyncio.run(scenario([(.55, .45), (.5, .5)]))
    assert commands == ["move -20 40", "click"]
    commands.clear()
    with pytest.raises(RuntimeError, match="no click"):
        asyncio.run(scenario([None, None, None]))
    assert not commands


def test_verified_tap_uses_conservative_last_attempt_before_click(tmp_path):
    async def scenario():
        commands, attempts = [], []
        async def send(command): commands.append(command)
        phone = Phone(SimpleNamespace(send=send), tmp_path / "calibration", Screen())
        phone._pos = (200, 400)
        async def point(x, y): pass
        async def locate(near, conservative=False):
            attempts.append(conservative)
            return (.5, .5) if conservative else None
        phone.point, phone._find_pointer = point, locate
        await phone.tap_verified(.5, .5)
        assert attempts == [False, False, True]
        assert commands == ["click"]
    asyncio.run(scenario())


def test_cold_pointer_initialization_preserves_conservative_frame_drain(tmp_path):
    async def scenario():
        attempts = []
        async def send(command): pass
        phone = Phone(SimpleNamespace(send=send), tmp_path / "calibration", Screen())
        async def point(x, y): phone._pos = (200, 400)
        async def locate(near, conservative=False):
            attempts.append(conservative)
            return (.5, .5)
        phone.point, phone._find_pointer = point, locate
        await phone.tap_verified(.5, .5)
        assert attempts == [True]
    asyncio.run(scenario())


def test_pointer_nudge_waits_for_its_visual_effect_not_an_older_pipeline_frame(tmp_path):
    from test_vision import H, W
    from test_vision import screen as pointer_frame

    async def scenario():
        commands, frames = [], []
        before = pointer_frame((250, 500))
        after = pointer_frame((262, 500))

        class DelayedScreen:
            frame = before
            updated = 1
            async def settled(self, **kwargs): pass
            async def fresh(self, since, timeout):
                self.updated += 1
                frames.append(self.updated)
                self.frame = before if len(frames) == 1 else after
                return self.frame

        async def send(command): commands.append((command, len(frames)))
        phone = Phone(SimpleNamespace(send=send), tmp_path / "calibration", DelayedScreen())
        phone.span = {"w": W, "h": H}
        found = await phone._find_pointer((250 / W, 500 / H))
        assert found and found[0] * W == pytest.approx(250, abs=3)
        assert commands == [("move 12 0", 0), ("move -12 0", 2)]
    asyncio.run(scenario())


def test_emergency_stop_cancels_new_action_without_ticket_or_waiting_for_lock(monkeypatch):
    from hidagent import app as module

    async def scenario():
        phone, screen = FakePhone(), Screen()
        control = Controls(phone, screen)
        entered = asyncio.Event()
        async def stuck(x, y):
            entered.set()
            await asyncio.Event().wait()
        phone.tap_verified = stuck
        monkeypatch.setattr(module, "controls", control)
        monkeypatch.setattr(module, "manual_lock", asyncio.Lock())
        monkeypatch.setattr(module, "agent", SimpleNamespace(running=False, stop=lambda: None))
        monkeypatch.setattr(module, "device", SimpleNamespace(connected=False))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app), base_url="http://local") as client:
            observation = (await client.get("/api/control/observe")).json()
            pending = asyncio.create_task(client.post("/api/control/action", json={
                "action": "tap", "x": .5, "y": .5, "screen_id": observation["screen_id"]}))
            await entered.wait()
            assert (await client.get("/api/control/observe")).status_code == 409
            result = await asyncio.wait_for(client.post("/api/agent/stop"), 1)
            assert result.status_code == 200
            assert (await pending).status_code == 409
            assert control.ticket is None
    asyncio.run(scenario())
