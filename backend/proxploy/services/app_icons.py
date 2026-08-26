"""Operator-uploaded icons for apps the catalog has no logo for.

The catalog's own icons (services/catalog_icons.py) are mirrored upstream bytes
at whatever size they arrived in, which is mostly but not reliably 512x512 (a
census of the cache found 512x513, 513x512, 256x256, 96x96 and two SVGs). An
upload is the one image in the product we actually control, so it is normalised
once, here, and every consumer can then assume a square WebP.

Deliberately CONTAIN and not COVER: cropping to fill would cut the edges off a
wide wordmark, and someone uploading their own logo is the last person whose
image should be silently trimmed. The remainder is transparent, so a logo with
its own background still looks like itself and one without does not gain a box.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

# Matches the dominant catalog size, so an uploaded icon and a store icon carry
# the same weight in the same grid.
SIZE = 512

# The re-encode makes the stored size independent of the upload, so this cap
# only has to stop someone spooling a huge file through memory.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

# Pillow's own default is ~178 Mpx and raises DecompressionBombError above it.
# Said explicitly rather than inherited: a 12000x12000 PNG is ~140 Mpx, decodes
# to about 576 MB as RGBA and would sail under the default while the 8 MB cap
# above sees only its compressed size. A decompression bomb is the one attack
# an image endpoint is actually exposed to.
MAX_PIXELS = 40_000_000


class BadImage(Exception):
    """The upload is not an image this can turn into an icon."""


def icon_dir(data_dir: Path) -> Path:
    return data_dir / "app-icons"


def icon_path(data_dir: Path, app_id: int) -> Path:
    """Where app `app_id`'s custom icon lives.

    `app_id` is an int straight off the route, so there is no traversal to
    guard here the way catalog_icons has to guard a slug from a feed.
    """
    return icon_dir(data_dir) / f"{app_id}.webp"


def normalise(raw: bytes) -> bytes:
    """`raw` as a 512x512 WebP, or raise BadImage.

    Decoding IS the validation. A filename ending in .png and a
    `Content-Type: image/png` are both attacker-controlled and neither is
    checked anywhere in this function; if Pillow cannot open the bytes as an
    image, it is not an image.
    """
    if not raw:
        raise BadImage("the uploaded file is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BadImage(f"the image is larger than "
                       f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        try:
            # verify() then reopen: verify() consumes the file object and
            # leaves the image unusable, which is exactly why Pillow documents
            # it as a cheap header check to run BEFORE the real decode rather
            # than as something you can load from afterwards.
            Image.open(io.BytesIO(raw)).verify()
            img = Image.open(io.BytesIO(raw))
            img = img.convert("RGBA")
        except UnidentifiedImageError:
            raise BadImage("that file is not an image Proxploy can read. PNG, "
                           "JPEG, WebP, GIF and BMP work; SVG does not.")
        except Image.DecompressionBombError:
            raise BadImage("that image has too many pixels to process safely")
        except OSError as e:
            raise BadImage(f"that image could not be read: {e}")

        # contain, then centre on a square transparent canvas.
        img = ImageOps.contain(img, (SIZE, SIZE), Image.LANCZOS)
        canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        canvas.paste(img, ((SIZE - img.width) // 2, (SIZE - img.height) // 2))

        out = io.BytesIO()
        canvas.save(out, format="WEBP", quality=90, method=6)
        return out.getvalue()
    finally:
        Image.MAX_IMAGE_PIXELS = previous


def store(data_dir: Path, app_id: int, raw: bytes) -> Path:
    """Normalise and write, replacing any icon already there.

    Written to a temp name in the same directory and renamed, so a reader (the
    GET route below, or a browser mid-request) never sees a half-written file:
    the same atomic-write shape catalog_icons.py uses for the same reason.
    """
    path = icon_path(data_dir, app_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = normalise(raw)
    tmp = path.with_suffix(".webp.tmp")
    tmp.write_bytes(blob)
    tmp.replace(path)
    return path


def remove(data_dir: Path, app_id: int) -> bool:
    """Delete the custom icon. True if there was one."""
    path = icon_path(data_dir, app_id)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def custom_icon_url(data_dir: Path, app_id: int) -> str | None:
    """The URL for this app's uploaded icon, or None.

    The mtime rides along as `v`: the path never changes when an operator
    replaces an icon, so without it a browser that cached the old one would go
    on showing it until the max-age expired, and the upload would look like it
    had silently failed.
    """
    path = icon_path(data_dir, app_id)
    try:
        stamp = int(path.stat().st_mtime)
    except FileNotFoundError:
        return None
    return f"/api/v1/apps/{app_id}/icon?v={stamp}"
