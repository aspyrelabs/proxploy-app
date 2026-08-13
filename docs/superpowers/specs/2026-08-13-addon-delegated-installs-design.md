# Addon-delegated installs: running the payload script Proxploy's own way

Date: 2026-08-13
Status: proposed, not approved, nothing implemented

## Problem

Five apps in the Store cannot be installed, and the reason is not ours.
Upstream moved them to an install flow that upstream's own `ct/*.sh` script no
longer performs, and the failure is silent: **upstream's script builds a
container, installs nothing into it, and reports success.**

The five, with their reported install counts from
`telemetry.community-scripts.org` at `days=0`:

| slug | terminal install events | `install/<slug>-install.sh` at `main` |
|---|---|---|
| `dockge` | 11,990 | 404 |
| `runtipi` | 5,278 | 404 |
| `komodo` | 4,203 | 404 |
| `coolify` | 2,721 | 404 |
| `dokploy` | 1,513 | 404 |
| `plex` (control) | 39,475 | 200 |

### The mechanism, measured

Every `ct/*.sh` sources `misc/build.func` and ends in `start`,
`build_container`, `description`. `build_container` installs the application
by fetching an install script and running it inside the new container
(`misc/build.func:5174`):

```bash
    local _install_script
    _install_script="$(curl -fsSL "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/install/${var_install}.sh")"
    lxc-attach -n "$CTID" -- bash -c "$_install_script"
```

Three lines above it sits the comment `# Error handling already disabled above
(before customization phase)`, so `set -Eeuo pipefail` is **off** at this
point. For these five apps the URL 404s. Verified end to end:

- `curl -fsSL` exits **56** and writes nothing to stdout.
- The failure is swallowed: no `set -e` abort, no `pipefail`, no trap.
- `_install_script` is therefore the **empty string**.
- `lxc-attach -n "$CTID" -- bash -c ""` runs nothing and **exits 0**.

The container was already created by that point, so the operator is left with
a bare Debian 13 LXC, and every downstream signal says the install succeeded.

**This affects anyone running these scripts, not only Proxploy.** A user
running `bash -c "$(curl -fsSL .../ct/dockge.sh)"` by hand on their node gets
the same empty container and the same success message. Nothing in this
document is a workaround for a Proxploy-specific bug.

### Why the addon script does not save it

Each of the five ships `tools/addon/<slug>.sh`, a complete installer for the
app. It is tempting to conclude the ct script delegates to it. It does not, on
the install path. In `ct/dockge.sh` and `ct/komodo.sh` at pinned SHA
`a222d32a318e3463bcde935bf52fdf5f883fa804`, `ADDON_SCRIPT` is assigned once at
line 23 and referenced **only inside `function update_script()`**, which
`build.func` calls when the script runs inside an existing container. The
install path never reads it.

So the payload exists, is fetchable, and is never executed by an install.

### What we already did about it

Nothing in this document is required for correctness today. Two changes have
already landed:

- `classifier.addon_delegation_slug` recognises the shape from script content
  (exactly one `build_container`, exactly one distinct `tools/addon/<slug>.sh`
  reference), so the addon script is fetched, pinned into `raw["addon_script"]`
  and the ct script's resource defaults are parsed.
- `ensure_classified` marks every such row **not installable, unconditionally**,
  with `UNSUPPORTED_ADDON_DELEGATED`: `"no install script upstream; it installs
  via an addon script run inside the container"`. The verdict is deliberately
  not derived from `classify_install_feasibility`, because the addon script is
  not what an install runs, and a verdict about the wrong file is not a verdict.

The Store therefore shows five honest cards that decline to install. This
document is about whether to go further.

## The proposed mechanism

Proxploy runs the addon script itself, inside the container, as a **second
execution step** after `build_container` returns.

### Where it goes

`services/appstore.py::run_install` today executes exactly one command over
root SSH to the node:

```python
command = (
    f"bash -c \"$(curl -fsSL {raw_url(entry.upstream_sha, entry.script_path)})\""
)
status = await executor.run_for_host(..., command, ...)
```

then re-reads `_lxc_ids()` and refuses to file an `App` row if the CT is
absent. The second step lands between the existing `_lxc_ids()` check and the
`App` row insert, and only for rows whose `raw` carries an `addon_script`.

Note that **LXC creates go over root SSH via `pct`, not the PVE API.** That is
not an implementation detail to be abstracted away: it is the causal link the
existing post-install check depends on, and the test harness models it
deliberately (`tests/e2e_server.py::_mirror_ssh_installs`, whose docstring
explains why routing it through the fake's API guest-create path "would make
the test pass by simulating something the product does not do"). Any second
step must run over the same channel or it is testing a different product.

### How the script gets in, and what it runs as

The update path already solves this exact problem and its solution should be
reused rather than reinvented. `run_update` runs:

```python
inner = (f"curl -fsSL {raw_url(entry['sha'], entry['script_path'])} "
         f"-o /tmp/proxploy-update.sh && "
         f"TERM=xterm PHS_SILENT=1 bash /tmp/proxploy-update.sh; "
         f"rc=$?; rm -f /tmp/proxploy-update.sh; exit $rc")
command = f"pct exec {int(a['ctid'])} -- bash -c {shlex.quote(inner)}"
```

The addon step is the same shape: `pct exec <ctid> -- bash -c ...`, fetching
`raw_url(entry.upstream_sha, "tools/addon/<slug>.sh")`. That keeps three
properties that already hold:

- **Pinned.** The addon script is fetched at the row's `upstream_sha`, the
  same commit that was classified, snapshotted into `raw` and diffed.
- **Inside the container, not on the host.** `run_update`'s comment records
  why this matters and what it cost to learn: running an in-container script
  over plain host SSH took `build.func`'s host branch and built a *second*
  container. Verified on PVE 9.2.6, 2026-08-10.
- **raw.githubusercontent.com only.** No `api.github.com` call is added, so
  the flat 2-call discovery ceiling is untouched.

## The unpinned-prompt problem

This is the part that decides whether the mechanism above is safe, and it is
the reason this document exists rather than a patch.

### The prompts, enumerated

On a fresh container, `tools/addon/dockge.sh` reaches exactly one prompt of
its own and `tools/addon/komodo.sh` two. The uninstall and update prompts sit
behind an "already installed" guard that a new container never trips.

| # | prompt | source | pinned? |
|---|---|---|---|
| 1 | `Install ${APP}? (y/N): ` | the addon script | yes |
| 2 | `Install Docker now? (y/N): ` | `misc/tools.func:4653`, via `ensure_docker` | **no** |
| 3 | `Enter your choice (default: 1): ` (komodo only, MongoDB vs FerretDB) | the addon script | yes |

All three are bare `read -r` on stdin. None reads from `/dev/tty`, so stdin
redirection would in principle reach them.

### Why a fixed answer sequence is unsafe

Prompt 2 does not appear in anything we pin. Both addon scripts begin with:

```bash
source <(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/misc/core.func)
source <(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/misc/tools.func)
```

`main` is hardcoded in upstream's own source. We cannot pin it without
rewriting the script, and rewriting an upstream script is a different and much
worse proposal. `tools.func` is 10,227 lines today and is fetched fresh at
execution time.

The consequence is decisive. A scheme that pipes a fixed sequence of answers,
say `printf 'y\ny\n\n'`, is asserting a prompt count and order that live in a
file we do not control and cannot observe at classification time. If upstream
adds one prompt to `ensure_docker`, every subsequent answer shifts by one and
gets consumed by the wrong question. The komodo case makes the failure
concrete: the shifted answer would land on the database selection, and `y` is
not `1` or `2`, so the script warns "Invalid choice" and silently picks
MongoDB. A future prompt with a destructive default would not be so kind.

`yes |` is worse and was ruled out at the outset: it commits us in advance to
agreeing with every question the script ever grows, including questions nobody
has read.

### Proposed handling: answer only what we recognise, abort otherwise

The only property that holds against an unpinned source is **never send an
answer to a question you have not read.** That means driving the script
interactively rather than pre-loading stdin:

1. Allocate a PTY for the `pct exec` and read output incrementally.
2. Maintain an allowlist of `(pattern, answer)` pairs, each with a written
   justification. Initially three, all from the table above:
   - `Install <APP>? (y/N):` answer `y`. This is the consent the operator
     already gave by pressing Install.
   - `Install Docker now? (y/N):` answer `y`. Docker is a stated dependency of
     both apps; declining exits 254 and installs nothing.
   - `Enter your choice (default: 1):` answer an empty line, which upstream
     itself defaults to MongoDB and labels "(recommended)".
3. On any prompt-shaped output that matches no pattern: send nothing, abort
   the step, and fail the install with the unmatched text quoted in the job
   log. Silence is the safe answer; a guess is not.
4. Idle timeout as a backstop, since a prompt we fail to recognise as
   prompt-shaped would otherwise hang.

Prompt-shaped detection is a heuristic, and it is the weakest link: it is the
same `read`/`whiptail` question `classify_install_feasibility` already answers
statically, applied to a live stream. It does not need to be perfect, because
the idle timeout catches what it misses and both outcomes are an abort.

**A cheaper reduction, worth doing regardless.** Installing Docker into the
container before running the addon script makes `ensure_docker` return early
and removes prompt 2 entirely, which is today's whole unpinned surface. It
does not solve the general problem, since tomorrow's `tools.func` could add a
prompt elsewhere, so it is a narrowing rather than a fix. It also means
Proxploy takes on responsibility for how Docker gets installed. Recommended as
a complement to the allowlist, never as a substitute.

## Verification, by artefact and never by exit status

Exit status cannot be trusted here, and the reason is the same failure this
document opens with. The cancel branch of both addon scripts is:

```bash
else
  msg_warn "Installation cancelled. Exiting."
  exit 0
fi
```

`exit 0`, after the container exists. `run_install`'s existing guard ("exit
status 0 is NOT proof the container was built") cannot fire, because the CT
genuinely does exist. Every layer would report success.

So the second step must confirm the application's own artefacts:

| app | required evidence |
|---|---|
| `dockge` | `/opt/dockge/compose.yaml` exists **and** `docker compose ls` reports a running project in `/opt/dockge` |
| `komodo` | a `*.compose.yaml` in `/opt/komodo` **and** `/opt/komodo/compose.env` **and** a running project |

**Per-app, not a general rule.** A general rule would have to be something
like "at least one running container", which is exactly the kind of proxy that
passes when Docker is running something unrelated. The paths above are already
written into the addon scripts as `INSTALL_PATH` and `COMPOSE_FILE`; the
evidence is specific because the claim is specific. Adding a sixth app means
writing down what proves that app installed, which is the correct amount of
work.

### What happens when verification fails

**Position: leave the container, file no `App` row, fail the job loudly with
the CTID in the message. Do not destroy.**

The argument for destroying is real: a half-built container is litter, and the
operator did not ask for a bare Debian box. The container is seconds old and
provably contains nothing they would miss, so the usual data-loss objection to
`pct destroy` is at its weakest here.

It is still the wrong call, for three reasons.

1. **The probe can be wrong; the destroy cannot be undone.** Verification is
   our inference about someone else's script. A false negative (upstream moves
   `INSTALL_PATH`, a compose project is named differently) would destroy a
   *working* installation. Leaving a container that turns out to be fine costs
   one click. Destroying one that was fine costs the install.
2. **The failure is diagnostic evidence.** Whatever went wrong is inside that
   container: the addon script's output, a partial `/opt` tree, apt logs. The
   first thing anyone debugging this will want is to look, and destroy-on-fail
   guarantees they cannot.
3. **It matches the existing posture.** `run_install`'s current guard raises
   `JobFailed` and files nothing; it does not clean up the node. A second
   guard that cleans up would make two failures on the same code path behave
   differently for no reason the operator can predict.

The mitigation for litter is the error message, not the destroy: name the
CTID, name what was missing, and say the container was left in place
deliberately. An offer to remove it is a reasonable later addition, as an
explicit operator action with its own confirmation, never as an automatic
consequence of a failed probe.

## Consent and visibility

**Position: yes, this needs its own disclosure, and it should be a distinct
field rather than a longer sentence in the existing one.**

The existing consent is specific: the operator ticks that they understand this
runs a community-scripts.org script as root on the node
(`api/catalog.py::install_catalog_entry` requires `consent: true`, mirroring
`hosts.py`'s `CONSENT_NOTE`). An addon-delegated install does two things that
consent does not describe:

- it runs a **second** script, from a different path in the repo, inside the
  new container rather than on the node, and
- Proxploy **answers prompts** on the operator's behalf, from a fixed
  allowlist.

The second is the one that matters. Answering "yes" to "Install Docker now?"
on someone's behalf is a decision, and burying it in a consent checkbox about
running scripts as root would be the kind of disclosure that is technically
present and practically invisible.

Concretely: a boolean on the catalog row, `addon_delegated` (the data is
already there implicitly as `raw["addon_script"]`, but implicit is not
serialisable), plus the allowlist's answers exposed on the detail response so
the install dialog can render "Proxploy will answer: Install Dockge? yes;
Install Docker now? yes". The frontend renders `unsupported_reason` verbatim
today and would render this the same way. **Naming the field is in scope for
this document; designing the dialog is not.**

## Scope

**Recommended: `dockge` and `komodo` only.**

`coolify`, `runtipi` and `dokploy` are excluded, and the reason is a property
of their scripts rather than a preference. Each prompts before fetching and
executing a third-party installer that upstream explicitly disclaims:

```
msg_warn "The following code is NOT maintained or audited by our repository."
echo -n "${TAB}Do you want to continue? (y/N): "
```

with, for coolify, `Review: https://cdn.coollabs.io/coolify/install.sh`. An
allowlist entry answering `y` there would have Proxploy accepting an unaudited
third-party installer on the operator's behalf. That is a different kind of
decision from "yes, install the app I clicked install on", and the user has
already ruled it out.

`dockge` and `komodo` do not have that prompt and do not run a third-party
installer. They fetch a compose file from the application's own upstream repo
(`louislam/dockge`, `moghtech/komodo`) and run `docker compose up -d`; komodo
additionally generates its own secrets with `openssl rand`. The one adjacent
case is `ensure_docker`, which prompts before installing Docker from an apt
repository (Docker's official one by default, the distro's with
`USE_DOCKER_REPO=false`). That is third-party *software* from a package
repository, not an unaudited script piped to a shell, and it is a stated
dependency of both apps. It is a weaker case than coolify's by a wide margin,
but it is the one judgement call in this scope and it should be made
knowingly.

## Recommendation

**Build it, narrowly, or prefer an upstream fix if one is available.**

The mechanism is specifiable and its failure modes are safe: an unrecognised
prompt aborts, a failed artefact check aborts and leaves evidence, and neither
can produce the silent empty container that motivated the work. Two apps
benefit, one of them the 4th most installed script in the corpus we track.

Two caveats belong in the decision.

- **The cheapest fix is not ours.** Upstream regressed this: these apps used
  to have `install/<slug>-install.sh`. Restoring those files, or adding a
  documented non-interactive entrypoint to the addon scripts (a `type=install`
  value alongside the existing `type=update` would be enough), fixes it for
  every consumer including the hand-rolled `curl | bash` user, with none of
  the machinery here. Filing that upstream is strictly better value than
  building this, and is not mutually exclusive with it.
- **Kill criterion.** If the prompt allowlist needs a fourth entry before this
  ships, or needs its first amendment within a release of shipping, that is
  evidence the unpinned surface moves faster than we can track it, and the
  right response is to stop and leave these five not-installable with an
  honest reason. That outcome is not a failure; it is the status quo, which is
  already correct and already truthful.

## Unchanged

- The flat 2-`api.github.com`-call discovery ceiling. Every fetch here is
  `raw.githubusercontent.com`.
- SHA-pinning: the ct script and the addon script are both fetched at the
  row's `upstream_sha`, the commit that was classified and snapshotted.
- Upstream metadata stays presentation-only. `WRITABLE_FIELDS` does not gain
  `installable`, `entry_type` or anything else discovery or the classifier
  owns, and nothing in this document changes that.
- The Store stays LXC-only; these five stay `entry_type='ct'` and stay on the
  grid whatever the verdict.
- `classify_install_feasibility` is not softened. The interactive-input
  finding is true and stays exactly as it is.
- The residual limitation both `run_install` and `run_update` already document
  stands and is not made worse: a pinned script's own
  `source <(curl ... /main/misc/build.func)` line is frozen text that still
  fetches live. Full transitive vendoring of the community-scripts framework
  is a separate, larger piece of work.

## Non-goals

- Vendoring or forking upstream scripts. Rewriting `source .../main/...` to a
  pinned ref would make the unpinned-prompt problem disappear and would make
  us the maintainer of a fork of someone else's installer.
- Generalising to every app. This is a two-app mechanism with a per-app
  verification table, on purpose.
- Interactive installs. Nothing here gives the operator a terminal into the
  install; the allowlist exists so that no human is required, not so that one
  can intervene.
- Automatic cleanup of a failed install's container. Argued above; a manual,
  explicitly confirmed removal action is a reasonable separate feature.
- Changing what `run_install` executes for normal apps. The second step is
  gated on `raw["addon_script"]` and is invisible to the other ~550 ct rows.

## Testing

If built, at minimum:

- **The empty-container regression, by name.** An addon script that exits 0
  without installing anything is reported as a FAILURE, no `App` row is filed,
  and the CT is left in place. This is the test the whole document exists for.
- An unrecognised prompt aborts the step, sends no answer, and quotes the
  unmatched text in the job log.
- Each allowlist entry is exercised against the real prompt text captured from
  the pinned addon scripts, so an upstream rewording fails a test rather than
  a production install.
- Artefact verification fails when the compose file is absent and passes when
  it is present, per app.
- The addon fetch is pinned to `upstream_sha` and no `api.github.com` call is
  made, mirroring the assertions already in `tests/test_catalog_ingest.py`.
- `plex` and the other ~550 normal ct rows take the existing single-step path
  unchanged.
- `coolify`, `runtipi` and `dokploy` remain not-installable, and no allowlist
  entry matches their third-party-installer prompt.
