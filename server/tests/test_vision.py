import io

import pytest
from PIL import Image, ImageDraw

from hidagent.vision import changed, pointer

W, H = 498, 1080  # a mirrored iPhone frame


def screen(pointer_at=None, button=False) -> bytes:
    """A synthetic home screen: gradient background, optional button and pointer dot."""
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        draw.line([(0, y), (W, y)], fill=(40, 60 + y // 10, 120))
    if button:
        draw.rectangle([150, 400, 350, 600], fill=(250, 250, 250))
    if pointer_at:
        x, y = pointer_at
        draw.ellipse([x - 12, y - 12, x + 12, y + 12], fill=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=75)
    return buf.getvalue()


def test_pointer_move_is_not_a_screen_change():
    assert not changed(screen((260, 856)), screen((272, 856)), ignore=((260 / W, 856 / H), (272 / W, 856 / H)))


def test_new_content_is_a_screen_change():
    assert changed(screen((260, 856)), screen((260, 856), button=True))


def test_missing_frame_counts_as_changed():
    assert changed(None, screen())


def test_pointer_is_found_from_a_nudge():
    shift = 12 / W
    found = pointer(screen((262, 856)), screen((274, 856)), near=(0.5, 0.8), shift=shift)
    assert found is not None
    assert found[0] * W == pytest.approx(262, abs=3)
    assert found[1] * H == pytest.approx(856, abs=3)


def test_pointer_not_found_when_nothing_moved():
    frame = screen((262, 856))
    assert pointer(frame, frame, near=(0.5, 0.8), shift=12 / W) is None


def checkmark_screen(checked: bool, pointer_at=(100, 500)) -> bytes:
    img = Image.open(io.BytesIO(screen(pointer_at))).convert("RGB")
    if checked:
        ImageDraw.Draw(img).line([(430, 495), (438, 505), (452, 485)], fill=(255, 149, 0), width=4)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=75)
    return buf.getvalue()


def test_small_checkmark_counts_as_a_change():
    assert changed(checkmark_screen(False), checkmark_screen(True))


def test_masked_pointer_move_is_not_a_change():
    before, after = checkmark_screen(False, (100, 500)), checkmark_screen(False, (300, 500))
    assert not changed(before, after, ignore=((100 / W, 500 / H), (300 / W, 500 / H)))


def test_pointer_far_from_the_target_is_found_with_a_full_screen_search():
    before, after = screen((354, 136)), screen((366, 136))
    assert pointer(before, after, near=(0.9, 0.1), shift=12 / W) is None  # outside the window near the target
    found = pointer(before, after, near=(0.5, 0.5), shift=12 / W, reach=(0.5, 0.5))
    assert found[0] * W == pytest.approx(354, abs=3) and found[1] * H == pytest.approx(136, abs=3)


def test_local_pointer_search_ignores_a_distant_animated_clock():
    before = screen((250, 500))
    img = Image.open(io.BytesIO(screen((262, 500))))
    ImageDraw.Draw(img).rectangle([180, 70, 220, 100], fill="white")
    buffer = io.BytesIO()
    img.save(buffer, "JPEG", quality=75)
    found = pointer(before, buffer.getvalue(), near=(250 / W, 500 / H), shift=12 / W)
    assert found is not None
    assert found[0] * W == pytest.approx(250, abs=3)
    assert found[1] * H == pytest.approx(500, abs=3)
