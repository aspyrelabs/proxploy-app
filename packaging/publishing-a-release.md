# Publishing a release

A human runs this once per release, in order. Nothing here happens as a side
effect of implementation (spec D4): every automated test proves the signing,
install, upgrade and rollback paths against a local file-served channel signed
with a throwaway key (`packaging/tests/DEV_ONLY_release_key.pem`). This runbook
is what turns that into a real, public release.

**Environments.** `PROXPLOY_ENV` picks the domain pair and nothing else does.
There is no search-and-replace between them anywhere; adding a third
environment is one more line in `install.sh`'s `WEB_BASE_URL` case and
one more entry in `config.py`'s `API_BASE_URL_BY_ENV`.

| `PROXPLOY_ENV` | install URL | release channel | licence API |
|---|---|---|---|
| `dev` (default today) | `web.proxploy.dev/install.sh` | `web.proxploy.dev/releases/latest` | `api.proxploy.dev` |
| `prod` | `proxploy.com/install.sh` | `proxploy.com/releases/latest` | `api.proxploy.com` |

All three come off the same two-row table, written down in exactly two places:
`install.sh`'s `WEB_BASE_URL` case and `config.py`'s `API_BASE_URL_BY_ENV` /
`WEB_BASE_URL_BY_ENV`.

`dev` is the installer's default and stays that way until the prod licence
server answers. Everything below is written for a **dev** release; the prod
cutover is Step 10.

**Before you do anything below, ask the channel, not this file.** Whether a
key is real and whether the channel is signed by it are facts with a command
attached, and any answer written here goes stale the first time someone signs
something:

```bash
d=$(mktemp -d)
curl -fsSL -o "$d/manifest.json"     https://proxploy.com/releases/latest/manifest.json
curl -fsSL -o "$d/manifest.json.sig" https://proxploy.com/releases/latest/manifest.json.sig
openssl pkeyutl -verify -pubin -inkey backend/proxploy/release_pubkey.pem \
  -rawin -in "$d/manifest.json" -sigfile "$d/manifest.json.sig"
```

"Signature Verified Successfully" means the shipped public key verifies what
the channel is serving, so Step 1 is a ROTATION and rotating breaks every
installed copy until it updates through a release signed by the old key. Any
other output means the shipped key does not match the channel, and Step 1 is
what fixes it.

## 1. Generate the release keypair, offline

```bash
openssl genpkey -algorithm ed25519 -out proxploy-release-key.pem
openssl pkey -in proxploy-release-key.pem -pubout -out release_pubkey.pem
```

Run this on a machine that isn't routinely online, or at minimum isn't a CI
runner, and from OUTSIDE the repo: run it in `~` and the key lands at
`~/proxploy-release-key.pem`, which is where Step 5 expects it.

The private key goes in a password manager as well, and nowhere else: not in
the repo, not in CI secrets (D2 keeps CI signing out of scope for this phase).
**Back it up before signing anything.** It is unrecoverable, and losing it
strands every install permanently: the public key is baked into every release,
so rotating it means publishing a release signed with the key you no longer
have.

The canonical backup of both halves lives on OneDrive, in:

```
/Users/aasim/Library/CloudStorage/OneDrive-24Seven/Business/Aspyre Labs/02 - Products/08 - proxploy/InformationTechnology/app
```

That holds the private key and its public key together, out of the repo and
out of CI. Treat that path as the record of record when someone asks "where is
the release key" — but it is a backup, not a working copy: the private key is
still generated and used at `~/proxploy-release-key.pem` per Step 1.

Lost track of where you ran it? Find the private half of the key the repo
actually carries:

```bash
find ~ -maxdepth 4 -name '*.pem' -not -path '*/Library/*' 2>/dev/null \
  | while read -r k; do
      openssl pkey -in "$k" -pubout 2>/dev/null \
        | diff -q - backend/proxploy/release_pubkey.pem >/dev/null \
        && echo "match: $k"
    done
```

## 2. Commit both copies of the public key

There are two, and they are not interchangeable:

- **`backend/proxploy/release_pubkey.pem`** — what an *installed* release uses
  to verify the NEXT release's manifest. `build_release.sh` re-derives this
  from `--key` when it stages, so committing it is belt-and-braces.
- **`RELEASE_PUBKEY_PEM` near the top of `install.sh`** — what a *first*
  install verifies against. Nothing is unpacked yet at that point for the
  installer to read a key out of, so the key has to arrive with the script.

```bash
cp release_pubkey.pem backend/proxploy/release_pubkey.pem
# then paste the same PEM into install.sh's RELEASE_PUBKEY_PEM block
git diff -- backend/proxploy/release_pubkey.pem install.sh
```

Miss the second one and every fresh one-liner install dies on "manifest
signature is not valid" while upgrades on existing boxes keep working, which
is a miserable way to find out.

Rotating the key later requires publishing a release that carries the new one,
the same bootstrap property doc 09 records for the entitlement key set
(§ "Key handling rules"). There is no out-of-band update path.

## 3. Prove the install path locally, on Linux with Docker

```bash
bash packaging/tests/test_oneliner.sh          # bundling, piping, URL-by-env
bash packaging/tests/test_pve_half.sh          # pct arguments, both push paths
bash packaging/tests/test_install.sh           # real install, systemd + TLS
bash packaging/tests/test_upgrade_rollback.sh  # update and rollback
```

The first two run anywhere. The last two need Docker and build their own
signed fixture channel with the throwaway key. `test_install.sh` installs from
the **bundled** installer with no `packaging/` beside it, which is the shape a
user actually gets. `build_release.sh` needs GNU coreutils (`sha256sum`,
`stat -c%s`), so it does not run on macOS.

## 4. Nothing. The repository stays private.

Kept as a numbered step because the previous version of this runbook said to
publish the repo here, and that was wrong.

The release channel is three static files at a base URL: `manifest.json`,
`manifest.json.sig`, and the tarball named in the manifest
(`packaging/proxploy-update:99-103`, `services/updater.py:53-54`). There is no
GitHub API call anywhere in the update path, and the `channel` shown in the UI
is a string field inside `manifest.json`, not GitHub release metadata. So the
artifacts are served from `web.proxploy.dev` alongside `install.sh`, and the
source repo has no reason to be public.

## 5. Build the signed release artifacts

```bash
bash packaging/build_release.sh --version 1.0.0 \
  --key ~/proxploy-release-key.pem --out dist/
```

Takes a couple of minutes: it runs `npm ci && npm run build` before it stages
anything. Runs on macOS as well as Linux (`build_release.sh`'s `file_size` and
`file_sha256` fall back to the BSD spellings), unlike the Docker harnesses in
Step 3.

Produces four files:

| file | what it is |
|---|---|
| `dist/proxploy-1.0.0.tar.gz` | the release: `backend/`, `frontend/`, `packaging/` |
| `dist/manifest.json` | version, channel, artifact name, sha256, size |
| `dist/manifest.json.sig` | Ed25519 signature over the manifest's raw bytes |
| `dist/install.sh` | **the single file served at the install URL** |

`dist/install.sh` is the answer to "where does the published installer come
from": `packaging/bundle_install.sh` splices `packaging/lib/common.sh` into the
repo's `install.sh` between its `BUNDLE:common.sh` markers, because a piped
script has no directory to source from. `build_release.sh` calls it, so the
published installer can never be a version out of step with the release it
installs. To build it on its own:

```bash
bash packaging/bundle_install.sh dist/install.sh
```

Then confirm two things about what you just built.

The key baked into the release is the one the repo carries, i.e. the `--key`
you passed really is the private half of the committed public key:

```bash
tar xzOf dist/proxploy-1.0.0.tar.gz backend/proxploy/release_pubkey.pem \
  | diff - backend/proxploy/release_pubkey.pem
```

Silence is a pass. A difference here means every install from this release
will fail signature verification, and Step 8 on a clean box is the first place
you would otherwise find out.

And that `manifest.json`'s `channel` field reads `stable` for a real release
(`build_release.sh`'s default); `--channel edge` is for prereleases, see
Step 6.

## 6. Publish the channel

The paths below assume this machine (Linux), where both repos live under
`~/workspace/aspyrelabs/proxploy/`. On macOS the equivalent is
`~/AspyreLabs/proxploy-app` and `~/AspyreLabs/proxploy-web` — substitute those
if you run this runbook there.

The site is the **`proxploy-web`** repo (`~/workspace/aspyrelabs/proxploy/proxploy-web`), a Vite
SPA deployed by Coolify on every push to `main`. Its `Dockerfile` ships
`dist/public` to nginx's html root, and Vite copies only `publicDir` there, so
everything below goes under **`public/`**. Files at the repo root are
committed, deployed, and never served.

```bash
cd ~/workspace/aspyrelabs/proxploy/proxploy-web
mkdir -p public/releases/latest public/releases/1.0.0
cp ~/workspace/aspyrelabs/proxploy/proxploy-app/dist/manifest.json \
   ~/workspace/aspyrelabs/proxploy/proxploy-app/dist/manifest.json.sig \
   ~/workspace/aspyrelabs/proxploy/proxploy-app/dist/proxploy-1.0.0.tar.gz \
   public/releases/latest/
cp public/releases/latest/* public/releases/1.0.0/
```

"Latest" is a directory you overwrite, not a symlink and not a redirect: the
installer fetches `$CHANNEL/manifest.json`, reads the tarball's name out of
it, and fetches `$CHANNEL/<that name>`. Both have to be reachable under the
same base URL at the same moment, so copy all three in one commit, manifest
last if your deploy is not atomic.

The pinned `public/releases/1.0.0/` copy is what
`--channel https://web.proxploy.dev/releases/1.0.0` installs, and it is the
only way to reinstall a specific version after `latest` has moved on. Use the
app's own three-component version for the directory name, matching `version`
in the manifest: a `1.0.0.0` typo 404s exactly like a missing file.

Spec D1's edge/stable split is **not implemented**: `manifest.json`'s
`channel` field is written by `build_release.sh --channel` and displayed by
the UI, but nothing routes on it. An edge channel today means a second
directory (`releases/edge/`) and a `--channel` flag, nothing more.

## 7. Serve the installer at the install URL

```bash
cp ~/workspace/aspyrelabs/proxploy/proxploy-app/dist/install.sh \
   ~/workspace/aspyrelabs/proxploy/proxploy-web/public/install.sh
cd ~/workspace/aspyrelabs/proxploy/proxploy-web && git add -A && git commit && git push
```

`public/install.sh`, so `https://web.proxploy.dev/install.sh` returns it
verbatim. Same commit as Step 6, one Coolify deploy for both.

It must be **`dist/install.sh`**, never the repo's own `install.sh`: that one
is the unbundled form and exits 1 the moment it cannot find
`packaging/lib/common.sh` next to itself. Check what you published actually
carries the splice:

```bash
curl -fsSL https://web.proxploy.dev/install.sh | grep -c 'BUNDLE:common.sh'   # 0
curl -fsSL https://web.proxploy.dev/install.sh | grep -c 'log()  {'           # 1
```

A **404 here does not look like a 404.** `nginx.conf`'s
`try_files $uri $uri/index.html $uri/ =404` falls through to the SPA, so a
missing file answers with the marketing page as `text/html` and a 404 status,
which means `curl | bash` pipes HTML into a shell. Check the status and the
content type, not just that something came back:

```bash
curl -sSI https://web.proxploy.dev/install.sh | head -1     # HTTP/2 200
curl -sSI https://web.proxploy.dev/install.sh | grep -i ^content-type
# application/octet-stream, NOT text/html
```

Then verify the whole chain against what is actually on the wire: the
signature over the served manifest, using the key compiled into the served
script.

```bash
w=$(mktemp -d) && cd "$w"
curl -fsSL -O https://web.proxploy.dev/install.sh
for f in manifest.json manifest.json.sig; do
  curl -fsSL -O "https://web.proxploy.dev/releases/latest/$f"; done
sed -n '/BEGIN PUBLIC KEY/,/END PUBLIC KEY/p' install.sh \
  | sed "s/^RELEASE_PUBKEY_PEM=//; s/'//g" > served.pem
openssl pkeyutl -verify -pubin -inkey served.pem -rawin \
  -in manifest.json -sigfile manifest.json.sig
```

## 8. Verify from a clean box

```bash
curl -fsSL https://web.proxploy.dev/install.sh | bash
```

A genuinely clean VM or container, not a box that already has a Proxploy
install or the dev-only test key lying around. On a Proxmox node the same
command creates a CT and installs inside it instead.

Confirm:

- the installed version matches what Step 6 published,
- `proxploy-update --help` and the app's Updates page both read
  `https://web.proxploy.dev/releases/latest`,
- `/etc/proxploy/proxploy.env` has `PROXPLOY_ENV=dev`,
- `proxploy-update` reports up to date,
- the app answers over TLS on the box's own address.

This is the only step in the whole phase that proves the real signature chain
end to end; every automated test before it used the throwaway key.

## 9. Verify an upgrade from that same box

Cut a `1.0.1`, repeat Steps 5 to 7, and run `proxploy-update` on the box from
Step 8. This is what proves the key baked into `1.0.0` verifies `1.0.1`, which
is the one property no local fixture can prove for a real key.

## 10. Cutting over to prod, later

When `api.proxploy.com` answers, in this order:

1. Stand up `proxploy.com/install.sh` and `proxploy.com/releases/latest/`
   with the same artifacts.
2. Flip `: "${PROXPLOY_ENV:=dev}"` to `prod` in `install.sh`, and cut a release
   carrying that change.

Nothing else moves: the domain pair lives only in `install.sh`'s
`WEB_BASE_URL` case and `config.py`'s `API_BASE_URL_BY_ENV` /
`WEB_BASE_URL_BY_ENV`. Existing
installs keep whatever `PROXPLOY_ENV` their env file already records, because
Step 5 of the installer never rewrites an env file that exists. Moving an
existing box to prod is an edit to `/etc/proxploy/proxploy.env` plus a
restart, deliberately: it changes which licence server holds that box's seat.
