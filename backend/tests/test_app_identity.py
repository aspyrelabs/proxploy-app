"""The monogram identity a logo-less app wears.

The drift test at the bottom is the point of this file: the ramp exists twice,
once in Python (the server picks from it at adopt) and once in TypeScript (the
picker draws swatches from it). Eight colour pairs did not justify an endpoint
and a loading state, so the duplication is deliberate and this is what keeps it
honest.
"""
import re
from pathlib import Path

import pytest

from proxploy.services.app_identity import RAMP, monogram, pick_colors, valid_colors

TS = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib"
      / "app-identity.ts")


@pytest.mark.parametrize("name,want", [
    ("blank-debian", "BLA"),
    ("vaultwarden", "VAU"),
    # Three or more segments give up their initials: D2C is far more
    # recognisable than DRI, which is the whole reason for the branch.
    ("driver-2fauth-custom", "D2C"),
    ("my_cool_thing", "MCT"),
    ("a.b.c.d", "ABC"),
    # Fewer than three segments falls back to the first three characters with
    # separators removed, so a two-word name never yields a two-letter tile.
    ("actual-budget", "ACT"),
    ("x-y", "XY"),
    ("a", "A"),
])
def test_monogram(name, want):
    assert monogram(name) == want


def test_monogram_never_empty():
    """A name of nothing but separators still has to produce a tile."""
    assert monogram("---") == "APP"
    assert monogram("") == "APP"


def test_monogram_is_at_most_three():
    for name in ("supercalifragilistic", "a-b-c-d-e-f", "one two three four"):
        assert len(monogram(name)) <= 3


def test_pick_colors_is_from_the_ramp():
    for _ in range(50):
        c = pick_colors()
        assert (c["dark"], c["light"]) in RAMP


def test_ramp_excludes_the_status_colours():
    """Green, red and amber mean running, stopped and paused/pending in
    StatusPill. A monogram wearing one of them reads as a status."""
    forbidden = {"#3fcf8e", "#f26d6d", "#f5b544", "#1f9d63", "#d9463f", "#c77e14"}
    for dark, light in RAMP:
        assert dark.lower() not in forbidden
        assert light.lower() not in forbidden


def test_valid_colors_accepts_the_stored_shape():
    assert valid_colors({"dark": "#5B9DF9", "light": "#2F6FE0"})


@pytest.mark.parametrize("bad", [
    # The pair is interpolated into a style attribute by IconTile, so anything
    # that is not exactly a hex triplet is a CSS injection.
    {"dark": "red;background-image:url(//evil/x)", "light": "#2F6FE0"},
    {"dark": "#5B9DF9", "light": "javascript:alert(1)"},
    {"dark": "#5B9DF9"},                      # missing half the pair
    {"c1": "#5B9DF9", "c2": "#2F6FE0"},       # the pre-redesign shape
    {"dark": "#5B9DF9", "light": "#2F6FE0", "extra": "#000000"},
    {"dark": "#GGGGGG", "light": "#2F6FE0"},
    {"dark": "#5B9DF", "light": "#2F6FE0"},   # five digits
    "not-a-dict", None, 7, [],
])
def test_valid_colors_rejects(bad):
    assert not valid_colors(bad)


def test_ramp_matches_the_frontend():
    """The TS ramp and the Python ramp must be the same list, in the same
    order: the server assigns from one and the picker draws the other, so a
    colour offered in the dialog that the server would never pick (or the
    reverse) is a silent inconsistency nobody would notice by looking."""
    pairs = re.findall(r"\{\s*dark:\s*'(#[0-9A-Fa-f]{6})'\s*,\s*"
                       r"light:\s*'(#[0-9A-Fa-f]{6})'\s*\}", TS.read_text())
    assert pairs, f"no ramp entries parsed out of {TS}"
    assert [(d.upper(), l.upper()) for d, l in pairs] == \
           [(d.upper(), l.upper()) for d, l in RAMP]
