# noVNC, vendored

This directory is a copy of the noVNC **application**, not the library.

| | |
|---|---|
| Upstream | https://github.com/novnc/noVNC |
| Tarball | https://github.com/novnc/noVNC/archive/refs/tags/v1.7.0.tar.gz |
| Tag | `v1.7.0` |
| Vendored on | 2026-08-20 |
| Licence | MPL-2.0 (see `LICENSE.txt`, contributors in `AUTHORS`) |

## Why this is here rather than in package.json

The npm package `@novnc/novnc` publishes the library only: `core/`, `vendor/`,
`docs/`, README, AUTHORS, LICENSE. It contains no `vnc.html`, no `app/`, no
`ui.js` and no CSS. The application we actually want, the one with the
settings sidebar that Proxmox also uses, exists only in the GitHub repository.
So it is vendored, and the npm dependency was removed so `core/` cannot be
loaded from two places at two versions.

The tag matches the version the npm dependency was pinned to, so `core/` and
`app/` cannot drift apart.

## What was copied

`vnc.html`, `app/`, `core/`, `vendor/`, `defaults.json`, `mandatory.json`,
`LICENSE.txt`, `AUTHORS`.

## What was omitted

`vnc_lite.html`, `tests/`, `po/` (translation sources; the compiled catalogues
in `app/locale/` are kept), `docs/`, `utils/`, `snap/`, `README.md`,
`package.json`, `karma.conf.cjs`, `eslint.config.mjs`, `.github/`.

## The rule

This is a verbatim copy. To take a newer noVNC, re-vendor the whole tree from
the tarball and re-apply the one modification below. Do not patch files here
in place, and do not lint, format or otherwise "improve" them; the repo's own
style rules stop at this directory.

## The one modification

MPL-2.0 requires a modification to be identifiable, so: **`vnc.html` is
modified.** Every other file is byte-identical to the tag. The change sits in
the block upstream already provides for embedders, is fenced by

```
// ===== BEGIN PROXPLOY MODIFICATION (not upstream noVNC) =====
// ===== END PROXPLOY MODIFICATION =====
```

and does two things:

1. **Promotes `host`, `port`, `encrypt` and `path` from query defaults to
   mandatory settings** when they appear in the query string, which makes
   noVNC apply them and then disable those controls in the settings sidebar.
   `mandatory.json` could not do this: it is a static file that ships with the
   build, and `path` carries a single-use console ticket minted seconds
   earlier. Locking these is what stops an operator editing the websocket path
   in the sidebar, pointing the console at nothing, and reading the failure as
   a Proxploy bug. Nothing else is locked; quality, compression, resize,
   view-only, clipboard and keyboard stay adjustable, which is the entire
   reason for using noVNC's own UI.

2. **Sets the `resize`, `quality` and `compression` defaults.** These are
   defaults, not mandatory, so `UI.initSetting` still prefers a value the user
   has already chosen in the sidebar. They live in `vnc.html` rather than in
   `defaults.json` because JSON cannot hold a comment and both choices need
   one. `defaults.json` and `mandatory.json` are therefore left verbatim at
   `{}`.

## How it is used

`frontend/src/routes/console-window.tsx` renders `/novnc/vnc.html` in a
full-bleed iframe for VM consoles, passing the connection settings in the
query string. Vite serves `public/` at the site root in dev and copies it into
`dist/` for the build, so there is no bundler configuration for this tree.
