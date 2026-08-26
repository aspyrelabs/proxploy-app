# Publishing a release

A human runs this once, when ready to cut `v1.0.0`. Nothing here happens as
a side effect of implementation (spec D4), every 9a test proves the
signing, install, upgrade and rollback paths against a local file-served
channel signed with a throwaway key (`packaging/tests/DEV_ONLY_release_key.pem`).
This runbook is what turns that into a real, public release.

**Current state, stated plainly:** the release private key does not exist
yet. `backend/proxploy/release_pubkey.pem` currently ships a **placeholder**
public key, it verifies nothing a real release signs. Step 1 replaces it.
Do not skip Step 1 and sign with the dev/test key; nothing installed from a
release built that way would be verifiable by anyone who trusts the shipped
pubkey.

## 1. Generate the release keypair, offline

```bash
openssl genpkey -algorithm ed25519 -out proxploy-release-key.pem
openssl pkey -in proxploy-release-key.pem -pubout -out release_pubkey.pem
```

Run this on a machine that isn't routinely online, or at minimum isn't this
CI runner. The private key goes in a password manager and nowhere else, 
not in the repo, not in CI secrets during 9a (D2 keeps CI signing out of
scope for this phase).

Replace `backend/proxploy/release_pubkey.pem` with the new public key and
commit that. The public key ships inside the install artifact, so **rotating
it later requires publishing a release that carries the new key**, the same
bootstrap property doc 09 records for the entitlement key set (§ "Key
handling rules"). There is no out-of-band update path for it.

## 2. Make the repository public

```bash
git log -p | grep -iE 'BEGIN .*PRIVATE KEY|password|token'
```

Check the full history for anything that shouldn't go public first, 
this is a one-way door in practice: once public, the entire history is
public, including anything since deleted. If that grep finds something real,
stop and deal with it (rotate the secret, and if the exposure is bad enough,
rewrite history) before continuing.

```bash
gh repo edit aspyrelabs/proxploy-app --visibility public
```

## 3. Build the signed release artifact

```bash
bash packaging/build_release.sh --version 1.0.0 --key proxploy-release-key.pem --out dist/
```

Produces `dist/proxploy-1.0.0.tar.gz`, `dist/manifest.json` and
`dist/manifest.json.sig`. Confirm `manifest.json`'s `channel` field reads
`stable` for a real release (`build_release.sh`'s default), `--channel edge`
is for prereleases only, see Step 4.

## 4. Publish the GitHub release

```bash
gh release create v1.0.0 dist/* --notes-file <notes-file>
```

Channel is derived from how the release is marked, not the manifest alone
(spec D1): a GitHub **prerelease** is the **edge** channel, a full release is
**latest** / **stable**. Pass `--prerelease` to `gh release create` for an
edge cut; omit it for stable.

## 5. Verify from a clean box

```bash
curl -fsSL https://raw.githubusercontent.com/aspyrelabs/proxploy-app/main/install.sh | bash
```

Run this against a genuinely clean VM or container, not a box that already
has a proxploy install or the dev-only test key lying around. Confirm the
installed version matches what was just published and that
`proxploy-update` reports up to date. This is the only step in the whole 9a
phase that proves the real signature chain end to end, every automated test
before this point used the throwaway key.
