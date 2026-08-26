"""The identity an app wears when it has no logo of its own.

Every app adopted by hand lands here: `icon_url` is served from the CATALOG
entry, so an app with no catalog slug can never have one. Before this module
that case fell through to the Store's own amber gradient with two letters of
the name, which meant every logo-less app in the grid was identical to every
other one AND was wearing the badge of the Store it never came from.

Two rules, both deliberate:

- The palette is one cool-to-magenta ramp and deliberately excludes green,
  red and amber. Those three are spoken for by StatusPill (green = running,
  red = stopped, amber = paused/pending) and by the Store gradient, so a red
  monogram sitting next to a green RUNNING pill would read as an error state.
  Staying on one ramp also means a grid of these reads as one system rather
  than as confetti.
- Each hue ships a dark-theme and a light-theme value, the same way
  tokens.css redefines every colour per theme. Storing both at adopt time is
  what lets the tile stay correct when the operator flips themes without the
  server being asked again.
"""
from __future__ import annotations

import re
import secrets

# (dark, light). Light values are darkened so the near-white glyph the tile
# draws on top keeps its contrast; dark values are the token hues, which
# already carry a dark glyph well.
RAMP: tuple[tuple[str, str], ...] = (
    ("#5B9DF9", "#2F6FE0"),   # blue    (--blue)
    ("#38BDF8", "#0C7FC4"),   # sky
    ("#34D3C6", "#0FA8A0"),   # cyan    (--cyan)
    ("#7C8CF8", "#4C5DD8"),   # indigo
    ("#A78BFA", "#7C5CFB"),   # violet  (--violet)
    ("#C084FC", "#9333EA"),   # plum
    ("#E879F9", "#C026D3"),   # orchid
    ("#F472B6", "#DB2777"),   # pink
)

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

_SEP_RE = re.compile(r"[-_. ]+")


def monogram(name: str) -> str:
    """Three characters standing in for `name`.

    Always three, never two: a fixed-width monogram is why the tile can be
    set in a monospace face and keep the same optical weight whether the
    letters are `III` or `WWW`.

    A name of three or more segments gives up its segment initials, because
    that is the part a person actually reads: `driver-2fauth-custom` is far
    more recognisable as `D2C` than as `DRI`. Anything shorter falls back to
    the first three characters of the name with separators removed.
    """
    parts = [p for p in _SEP_RE.split(name) if p]
    if len(parts) >= 3:
        return "".join(p[0] for p in parts[:3]).upper()
    return _SEP_RE.sub("", name)[:3].upper() or "APP"


def pick_colors() -> dict[str, str]:
    """A random hue from the ramp, as `{"dark": ..., "light": ...}`.

    Random and then stored, not derived from the name: renaming an app must
    not change the colour the operator has learned to find it by. `secrets`
    rather than `random` for no cryptographic reason at all, only so that
    nothing in this codebase seeds a global PRNG that a test then depends on.
    """
    dark, light = secrets.choice(RAMP)
    return {"dark": dark, "light": light}


def valid_colors(value: object) -> bool:
    """Whether `value` is a colour pair this app is willing to store.

    These two strings are interpolated into a `style` attribute by the
    frontend tile, so an unvalidated write is a CSS injection: a `c1` of
    `red;background-image:url(//evil/x)` would have been rendered as-is. The
    column takes a free-form JSON dict and the PATCH schema types it as
    `dict`, so the shape has to be enforced here or nowhere.
    """
    if not isinstance(value, dict):
        return False
    if set(value) != {"dark", "light"}:
        return False
    return all(isinstance(v, str) and HEX_RE.match(v) for v in value.values())
