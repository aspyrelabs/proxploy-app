# Phase 4 entry-gate spike: non-root/API-first install investigation

Doc 10 Phase 4 entry gate, doc 11 §1, doc 08 §4. Goal: determine whether
community-scripts/ProxmoxVE can be driven non-interactively / via API, before
any `SSHExecutor` work starts. This is an investigation, not an
implementation, nothing under `executor/` was built.

## Verdict

**Entry gate SATISFIED. Root SSH remains necessary, confirmed by evidence,
not assumed.** Two independent, structural reasons, either one sufficient on
its own:

1. Community-scripts creates every LXC container with `pct create`, a
   Proxmox host-local CLI command, never the Proxmox REST API's own
   container-create endpoint. `root_check()` hard-exits anything that isn't
   root.
2. Even hypothetically bypassing community-scripts' own `pct create` call
   and having Proxploy create the CT itself via the Proxmox API: there is no
   REST API path to execute the pinned install script inside an LXC
   container afterward. The QEMU guest-agent exec endpoint exists only for
   VMs; `pct exec`/`pct push` are host-CLI-only with no LXC equivalent in
   the API (sourced below).

This matches doc 08 §4 / doc 11 §1's stated expected outcome. The executor
design in doc 08 §4 needs no architectural change. What the spike **does**
add: hard data on the in-container install-script layer that the existing
docs didn't have, which sharpens the Phase 4 install-feasibility classifier
(doc 04 `catalog_entries.installable`) from a guess into a real, mechanical
rule, see "Classifier and executor implications" below.

## Method

Shallow-cloned `community-scripts/ProxmoxVE` at commit `09c11fd`
(2026-07-29) into a scratch dir (not committed to this repo). Three passes:

1. Direct grep/read of the shared framework: `misc/build.func` (7166
   lines, host-side CT creation), `misc/core.func` (1864 lines; shared
   helpers incl. `is_unattended()`), `misc/install.func` (552 lines; shared
   in-container framework), `misc/api.func` (1224 lines; telemetry, *not*
   the Proxmox API despite the name), `misc/error_handler.func` (`catch_errors()`).
2. Full-corpus grep across all 572 `ct/*.sh` and 559 `install/*.sh` scripts
   for prompt patterns, `build_container` call counts, and framework usage.
3. A 24-app deep-read sample spanning databases, media, home automation,
   monitoring, dev tools, networking, and backup (full list in "Q4" below),
   via two parallel subagents reading both the `ct/` and `install/` half of
   each pair, plus a hand-verified local repro of the one nuance both
   agents got wrong (below).

## Q1: non-interactive / silent mode support

**Host-side (CT creation): yes, real and universal.** `misc/core.func:1077`,
`is_unattended()`:

```
Modes that are unattended:
  - default (1)      : Use script defaults, no prompts
  - mydefaults (3)   : Use user's default.vars, no prompts
  - appdefaults (4)  : Use app-specific defaults, no prompts
...
  # No TTY available = unattended
  [[ ! -t 0 ]] && return 0
```

Set via `MODE=default|mydefaults|appdefaults|advanced`, or legacy
`PHS_SILENT=1` / `var_unattended=yes` / `UNATTENDED=yes`, and automatically
true with **no env var at all** whenever stdin isn't a TTY, which is exactly
the shape of a non-interactive SSH exec. Every `ct/*.sh` sources this same
`build.func`/`core.func` machinery, so this is infrastructure, not a
per-app opt-in.

**In-container (install scripts): partial, and inconsistently applied.**
Full-corpus count:

| | count | % of 559 |
|---|---|---|
| Zero interactive prompts (fully silent already) | 493 | 88.2% |
| Contains a `read -p`-shaped prompt or `whiptail`/`dialog` | 66 | 11.8% |
| …of which routed through the safe, `is_unattended()`-aware `prompt_confirm`/`prompt_input`/`prompt_select` framework (`core.func`) | 2 | 0.4% |

The other 64 use bare `read -r -p "..."` written for a human at a real
terminal, with no `is_unattended` check at all.

**The critical nuance neither sampling pass caught, verified empirically:**
every install script runs under `catch_errors()` (`misc/error_handler.func:713`):

```
catch_errors() {
  set -Ee -o pipefail
  ...
  trap 'error_handler' ERR
  ...
}
```

`read` returns exit status 1 on EOF (confirmed directly: `echo -n "" | read
-r -p "x: " v` → exit 1). Under `set -Ee` + `trap ERR`, a bare unconditioned
`read` line hitting EOF does **not** fail open to an empty/default answer, 
it fires the ERR trap and aborts the whole install. Reproduced with the
exact real-world shape (mariadb's "Would you like to add PhpMyAdmin? <y/N>"
prompt) against closed stdin:

```
$ bash repro.sh </dev/null
before prompt
ERR TRAP FIRED at line 6, exit code 1
script exit code: 99
```

Both parallel research passes independently assumed plain `y/N` prompts like
this were "default-safe on EOF" (treated as "no" and continue) by analogy
with normal bash semantics for an *empty but present* answer. That
assumption is wrong for this codebase specifically, because of the
universal `set -e` wrapper, it hard-aborts instead. So the honest
classification of all 64 unguarded-prompt scripts is "requires interaction
or a pre-seeded answer," full stop; there is no free lunch among the
"optional-looking" prompts. (4 of the 66 prompt-bearing scripts *do* have an
env-var pre-check ahead of the read that can skip it entirely, see Q3.)

This also means whatever the executor does with stdin matters operationally,
independent of catalog classification: closed/`/dev/null` stdin turns an
unguarded prompt into a **fast, deterministic failure**; a stdin left open
with no data turns it into an **indefinite hang** that would sit on a
`JobBackend` semaphore slot forever. The executor must use the former.

## Q2: CT creation via API without a root shell?

No path exists, at either layer:

- **Community-scripts never does this.** Full-corpus grep for `pvesh` across
  the whole repo: used in 16 `vm/*.sh` (VM, not LXC) scripts and unrelated
  cluster/pool tooling, for `pvesh get /cluster/nextid` and similar reads; 
  never for creating a container. Every `ct/*.sh` path creates its container
  via `pct create "$CTID" ...` (`misc/build.func:6099`, `:6267`), the
  Proxmox host-local CLI. `misc/core.func:292`, `root_check()`: exits
  `"Please run this script as root."` if not root.
- **Proxmox's own API doesn't offer an escape hatch either**, even for a
  from-scratch Proxploy-authored executor that ignores community-scripts'
  `pct create` entirely: the Proxmox REST API exposes a guest-agent
  `exec` endpoint for QEMU VMs, but LXC containers have no REST equivalent; 
  `pct exec` (which wraps `lxc-attach`) and `pct push` are CLI-only, and
  must run on the Proxmox host. Confirmed via web search, not assumed:
  ["pct exec and pct push are CLI only, meaning there is no REST API
  endpoint equivalent for directly executing commands in LXC containers
  through the Proxmox API."](https://github.com/RekklesNA/ProxmoxMCP-Plus/blob/main/docs/container-command-execution.md)
  ["This is a known limitation of the Proxmox VE API for LXC containers,
  unlike QEMU VMs which have the guest agent endpoint
  available."](https://forum.proxmox.com/threads/execute-command-in-node-with-api.112290/)

So root/privileged shell access on the node is structurally unavoidable at
**two** separate points, container creation, and running the install
script inside it, independent of any per-app interactivity question. Doc
08 §4's SSH-key design is the only viable shape.

## Q3: input surface where non-interactive install IS supported

**CT-creation layer** (universal, every app): `ENV var_* > default.vars >
built-ins` precedence (`build.func:1500`). Example from `ct/immich.sh`:

```
var_tags="${var_tags:-photos}"
var_disk="${var_disk:-20}"
var_cpu="${var_cpu:-4}"
var_ram="${var_ram:-6144}"
var_os="${var_os:-debian}"
var_version="${var_version:-13}"
var_arm64="${var_arm64:-yes}"
var_unprivileged="${var_unprivileged:-1}"
var_gpu="${var_gpu:-yes}"
```

This surface covers the whole catalog and needs no per-app work.

**In-container layer** (thin, inconsistent, per-app): only 4 of the 66
prompt-bearing scripts pre-check an env var before reading. The
best-designed example, `jellyfin`/`plex`'s shared `setup_hwaccel` GPU
prompt (`misc/tools.func`), checks `INSTALL_NVIDIA_DRIVERS` first *and*
has a 60-second auto-yes timeout on the read itself, so it's safe even if
reached unattended. `PG_DB_PASS` (honored by `immich`, `paperless-ngx` via
`tools.func`'s `setup_postgresql_db`) presets the generated DB password.
Most prompt-bearing scripts have nothing: `postgresql-install.sh`'s version
picker (`read -r -p "Enter PostgreSQL version (15/16/17/18): " ver`, no
default, invalid/empty → `exit 64`) and `docker-install.sh`'s three prompts
(Portainer UI, Portainer Agent, TCP socket exposure) take no override at
all.

**Credentials surface:** several apps (`mysql`, `immich`, `paperless-ngx`)
generate a random password with `openssl rand` and write it to
`~/<app>.creds` *inside the container*, deliberately never printed to
stdout. The executor needs to read that file over SSH post-install to
surface credentials, capturing stdout is not sufficient.

## Q4: sample classification (24 apps, cross-category)

`postgresql, mysql, mariadb, mongodb, redis, jellyfin, plex, immich,
homeassistant, homebridge, zigbee2mqtt, docker, grafana, prometheus,
uptimekuma, gitea, n8n, pihole, adguard, nginxproxymanager, wireguard,
paperless-ngx, vaultwarden, proxmox-backup-server`

All 24 are single-CT (one `build_container` call each; a few `ct/*.sh`
files are long only because of an `update_script()` function for
re-installs against an existing container, not multi-CT orchestration).
Corpus-wide check confirms this isn't sample luck: **568 of 572 `ct/*.sh`
(99.3%) call `build_container` exactly once**; the 4 outliers use a
differently-named wrapper and weren't investigated further (immaterial to
the finding).

| App | Fresh-install prompt(s) | Blocks unattended install? | Env override |
|---|---|---|---|
| redis, homeassistant, homebridge, zigbee2mqtt, grafana, prometheus, uptimekuma, gitea, n8n, adguard, proxmox-backup-server | none | no | n/a |
| mariadb | "Add PhpMyAdmin? <y/N>" | **yes** (unguarded `read`, see Q1) | none |
| wireguard | "Add WGDashboard? <y/N>" | **yes** | none |
| paperless-ngx | "Add Adminer? <y/N>" | **yes** | none for this prompt; `PG_DB_PASS` covers the DB password separately |
| nginxproxymanager | none, but ships static default creds `admin@example.com` / `changeme` | no | n/a (worth a security note, not a blocker) |
| vaultwarden | admin-token reset prompt exists only on the *update* path, and is explicitly `PHS_SILENT`-guarded (`if PHS_SILENT: skip with warning`) | no (fresh install) | `PHS_SILENT` |
| jellyfin, plex | GPU-passthrough driver prompt, conditional on hardware | no (env + 60s timeout) | `INSTALL_NVIDIA_DRIVERS` |
| immich | ML-backend prompt, Intel-CPU-only | no in practice (EOF → default `1`) but not an intentional contract | `ML_TYPE` default only |
| postgresql | version picker, unconditional | **yes**, no default | none |
| mysql | 8.4-vs-8.0 choice + phpMyAdmin prompt | **yes** | none |
| mongodb | 8.0-vs-7.0 choice (x86 only; auto-skipped on arm64) | **yes** on x86 | none |
| docker | Portainer UI / Agent / TCP-socket-exposure, all unconditional | **yes** | none |
| pihole | continue-anyway confirm (**no answer → `exit 10`**, not just unattended-unsafe but actively hostile to a blind default) + 2 optional add-ons | **yes** | none |

## Classifier and executor implications

**Executor (doc 08 §4, unchanged in shape, two concrete additions):**

- Always exec with stdin closed (`/dev/null`, no PTY); turns any unguarded
  prompt into a fast deterministic failure instead of a hang that parks a
  `JobBackend` slot forever. Required regardless of classification, because
  a script we believe is prompt-free today could regress upstream.
- Proactively export `MODE=default` (or `appdefaults` once "save app
  defaults" is a feature) at the CT-creation invocation. This is real,
  already-built, and free; no reason not to set it explicitly rather than
  rely on no-TTY auto-detection alone.

**Classifier (doc 04 `catalog_entries.installable`/`unsupported_reason`):**
a mechanical, ingest-time static check on the *pinned* install script
content, no execution, no guessing:

- `installable = true` when: exactly one `build_container` call in the
  paired `ct/*.sh`, **and** no unguarded `read -[a-zA-Z]*p`/`whiptail`/
  `dialog` in the paired `install/*.sh` (excluding hits preceded by an
  env-var short-circuit, e.g. the `INSTALL_NVIDIA_DRIVERS`/`PG_DB_PASS`
  pattern, 4 known cases in the sample).
- `unsupported_reason = "install script requires interactive input, no
  non-interactive entrypoint"` otherwise; this is verbatim the example
  doc 04 already names.
- Applied corpus-wide as-is today, this rule seats **installable ≈ 493/559
  (88.2%)** on day one, zero extra engineering; a real number for Phase
  4's DoD ("the store reports the true installable count... no '300+
  scripts' placeholder") rather than a guess.
- Deliberately **not** recommending expect-style blind stdin injection
  (piping `"y\n16\n"` at scripts we don't control future versions of) to
  rescue the other 11.8%, that's exactly the "sandboxing theater" doc 11
  §1 already rules out. A script we can't drive honestly should say so.

## What was not investigated

- Whether the ~64 unguarded-prompt scripts could be fixed upstream (PR the
  `is_unattended()`/`prompt_confirm` framework into them), plausible given
  2 scripts already do it, but that's a community contribution, not
  something Phase 4 should block on.
- ARM64/Alpine-variant scripts, VM scripts (`vm/*.sh`), and `turnkey/*.sh`
  were out of scope, this spike is about the LXC app-install path only,
  matching doc 01 §3's one-CT model.
- No live PVE was used; every finding above is from static reading of the
  actual upstream script content plus one local bash repro of the
  `set -e`/`read`/EOF interaction, not a live install run. `misc/build.func`
  (7166 lines) and `misc/core.func` (1864 lines) were read via targeted grep
  + section reads, not line-by-line in full.

## Not yet done

Doc 08 §4 and doc 11 §1 both currently read as forward-looking ("before
Phase 4 invests further... a spike... checks whether"). Once this finding
is reviewed and accepted, both should get a short pointer to this doc
replacing that framing, left undone deliberately, per instruction to stop
here for review before any Phase 4 work (including doc edits) proceeds.
