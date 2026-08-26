"""Normalising an operator-uploaded app icon.

Decoding is the validation here, so most of what matters is what gets refused:
a filename and a Content-Type are both attacker-controlled and neither is
consulted anywhere in services/app_icons.py.
"""
import io

import pytest
from PIL import Image

from proxploy.services import app_icons


def _png(w, h, mode="RGB", colour=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new(mode, (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def _open(blob):
    return Image.open(io.BytesIO(blob))


def test_square_source_becomes_512_webp():
    out = _open(app_icons.normalise(_png(1024, 1024)))
    assert out.format == "WEBP"
    assert out.size == (app_icons.SIZE, app_icons.SIZE)


def test_small_source_is_scaled_up_not_left_tiny():
    """A 40px favicon has to end up the same weight in the grid as a 512px
    store logo, or the tile it produces looks broken next to them."""
    assert _open(app_icons.normalise(_png(40, 40))).size == (512, 512)


@pytest.mark.parametrize("w,h", [(1200, 300), (300, 1200), (900, 512)])
def test_wide_and_tall_are_contained_never_cropped(w, h):
    """CONTAIN, not COVER. The whole source has to survive: cropping a wide
    wordmark to fill a square cuts the ends off someone's own logo."""
    out = _open(app_icons.normalise(_png(w, h)))
    assert out.size == (512, 512)
    # The source's aspect ratio must be preserved inside the canvas, which
    # means the padding runs along exactly one axis.
    px = out.convert("RGBA").load()
    if w > h:                      # letterboxed: top and bottom transparent
        assert px[256, 2][3] == 0
        assert px[2, 256][3] != 0
    elif h > w:                    # pillarboxed: left and right transparent
        assert px[2, 256][3] == 0
        assert px[256, 2][3] != 0


def test_result_keeps_alpha():
    out = _open(app_icons.normalise(_png(600, 200)))
    assert out.mode in ("RGBA", "RGB")
    assert out.convert("RGBA").load()[2, 2][3] == 0


@pytest.mark.parametrize("raw,because", [
    (b"", "empty"),
    (b"not an image at all", "garbage"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>", "svg"),
    # A PNG header on non-PNG bytes: the thing a Content-Type check would wave
    # through and a decode will not.
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "png header, no png"),
])
def test_rejects(raw, because):
    with pytest.raises(app_icons.BadImage):
        app_icons.normalise(raw)


def test_rejects_oversized_upload():
    with pytest.raises(app_icons.BadImage, match="larger than"):
        app_icons.normalise(b"\x00" * (app_icons.MAX_UPLOAD_BYTES + 1))


def test_store_then_remove_round_trip(tmp_path):
    assert app_icons.custom_icon_url(tmp_path, 7) is None
    assert app_icons.remove(tmp_path, 7) is False

    path = app_icons.store(tmp_path, 7, _png(300, 300))
    assert path.is_file()
    url = app_icons.custom_icon_url(tmp_path, 7)
    assert url.startswith("/api/v1/apps/7/icon?v=")

    assert app_icons.remove(tmp_path, 7) is True
    assert app_icons.custom_icon_url(tmp_path, 7) is None


def test_replacing_an_icon_changes_its_url(tmp_path, monkeypatch):
    """The path never changes, so without the mtime stamp a browser would go
    on serving the old icon out of cache and the upload would look ignored."""
    app_icons.store(tmp_path, 3, _png(100, 100))
    first = app_icons.custom_icon_url(tmp_path, 3)

    import os
    p = app_icons.icon_path(tmp_path, 3)
    os.utime(p, (0, os.stat(p).st_mtime + 60))

    assert app_icons.custom_icon_url(tmp_path, 3) != first


def test_store_leaves_no_temp_file_behind(tmp_path):
    app_icons.store(tmp_path, 9, _png(128, 128))
    assert [p.name for p in app_icons.icon_dir(tmp_path).iterdir()] == ["9.webp"]


def test_a_failed_store_does_not_clobber_the_existing_icon(tmp_path):
    app_icons.store(tmp_path, 5, _png(256, 256))
    good = app_icons.icon_path(tmp_path, 5).read_bytes()
    with pytest.raises(app_icons.BadImage):
        app_icons.store(tmp_path, 5, b"garbage")
    assert app_icons.icon_path(tmp_path, 5).read_bytes() == good
