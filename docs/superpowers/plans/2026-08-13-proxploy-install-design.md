# App Store installation: Default and Advanced (GUI-driven) installs

Date: 2026-08-13
Status: proposed, supersedes the addon-delegated-installs design
Author framing: Aasim

## What this replaces and why

The prior design (addon-delegated installs) solved a narrow problem: five apps
whose upstream ct script builds an empty container, by having Proxploy silently
answer their prompts from a fixed allowlist, with no human involved. Its own
non-goals said "no human is required" and "interactive installs" were explicitly
excluded.

That is the opposite of what we want. We want the human in the loop, seeing and
choosing options in a GUI form, not a hidden allowlist answering on their behalf.
The five broken apps are not the point; they become one case that this broader
design also handles.

## The two install modes

Every installable app offers two paths. The user picks at install time.

### Default install
One click. Proxploy uses the app's documented defaults for everything and
proceeds with no questions. This is for the user who does not care to configure
and just wants the app. It must stay genuinely one-click: no form, no prompts.

### Advanced install
A GUI form. The user reviews and chooses every option, even if they end up
keeping the defaults, because the value is knowing the options existed. This
replaces the community-scripts console Q&A with a form: the user enables/selects
what they want, Proxploy assembles those choices into the same answers the
upstream installer would have collected interactively, and runs the install
non-interactively with those answers.

The mental model, stated plainly because it is the whole idea: community-scripts'
own installer runs a setup that collects answers, then uses those answers during
install. We replicate that exactly, but the answer collection happens in a GUI
form instead of a terminal.

## What the Advanced form contains

Two sections. They differ sharply in how buildable they are, and the design
treats them differently on purpose.

### Section 1: Container customization (fully buildable now)

This is the part we have complete data for, and it is the freedom every "I want
to change 512MB to 1GB" user is asking for. All of it comes from the app's cached
PocketBase metadata (`install_methods[].resources`) plus standard Proxmox
container settings:

- CTID: OPTIONAL, and validated against collisions when supplied.
  - Blank means Proxploy uses the next available ID on the target host (the
    upstream installer already does this when no ID is given). Blank never
    collides, so it needs no validation. Requiring a CTID today is a bug; fix it.
  - If the user types a CTID, the form validates it BEFORE allowing submit:
    (a) it is a valid Proxmox ID (numeric, >= 100), and (b) it is NOT already in
    use on the SELECTED target host. On collision, show an inline error naming it
    ("CTID 100 is already in use on host-01") and disable the Install button while
    it collides.
  - IDs are per-host, so re-run the check when the user changes the target host:
    a CTID free on one host may be taken on another.
  - The BACKEND is the real gate, not the form. The install endpoint must reject
    an already-in-use CTID at execution time, because a guest could be created
    between form validation and submit, and client-side validation is bypassable.
    Return a clear error rather than letting the underlying `pct create` fail with
    a raw message. The form check is the friendly early warning; the server
    enforces correctness.
- Hostname / CT name
- CPU (vCPU) - default from `resources.cpu`, user-overridable
- RAM (MB) - default from `resources.ram`, user-overridable
- Disk (GB) - default from `resources.hdd`, user-overridable
- OS / version - default from `resources.os` / `resources.version`
- Target host (when multiple hosts are managed)
- Storage pool
- Network / bridge
- Unprivileged toggle

These map to the environment variables the community-scripts installer reads, the
same mechanism installs already use. This section is app-agnostic in shape,
per-app in defaults, and is the bulk of the immediate value.

### Section 2: App-specific options (per-app answer schema, built over time)

Some apps ask questions beyond container settings: a database choice (komodo:
MongoDB vs FerretDB), a password, a version/edition, a domain. These live inside
the upstream install script.

The hard constraint, and the reason the prior doc existed: these prompts are NOT
knowable ahead of time by reading a pinned file. The upstream installer sources
its framework (`tools.func`, 10,000+ lines) fresh from `main` at execution time,
hardcoded and unpinnable. So Proxploy cannot reliably auto-generate a form of an
arbitrary app's exact questions, and cannot safely fire a fixed sequence of
answers at a prompt list that can shift under it.

The decision (Aasim): curate a GUI form for every app we can, and fall back to a
live terminal for apps we have not curated yet.

That gives a per-app "answer schema": a small, hand-authored, version-checked
definition of that app's real install questions and the field each maps to.

- Where a curated schema EXISTS: the Advanced form renders those app-specific
  fields (a dropdown for komodo's database, a password field, etc.), the user
  chooses, and Proxploy supplies those answers to the install non-interactively.
  Clean GUI, no terminal.
- Where NO schema exists yet: the app still installs. Advanced falls back to a
  live terminal (see below) so the user answers the real prompts as they appear.
  Nothing is un-installable just because we have not curated it.

The curated schemas grow over time, starting with the most-installed apps
(popularity data tells us which). Adding an app means writing down its questions
and their env-var mappings, and pinning the exact prompt text so an upstream
reword fails a test rather than a production install.

## The live terminal fallback

For any app without a curated schema, Advanced install streams the real install
in an interactive terminal (the app already ships xterm and a console/exec path).
The user sees the actual prompts and answers them. This is the general safety net
that makes "every app is installable" true without requiring every app to be
curated first.

Two honest properties of the fallback:

- It is a real terminal, so it works for any app, including ones with prompts we
  have never seen. That is its whole reason to exist.
- It requires the user to be present for that install. That is acceptable as a
  fallback and is strictly better than "not installable". Curated schemas exist
  precisely to remove the terminal for the apps people install most.

Proxploy NEVER auto-answers a prompt from a hidden allowlist. Either the user
answered it in the curated form (so Proxploy is submitting the user's own
choice), or the user answers it live in the terminal. There is no third path
where Proxploy guesses on the user's behalf. This is the key departure from the
prior design.

## The five "empty container" apps, folded in

dockge, komodo, coolify, runtipi, dokploy build an empty container upstream
because their ct script no longer runs an install; the real installer is
`tools/addon/<slug>.sh`, run inside the container. Under this design they are not
special:

- Proxploy runs the addon script as the install payload, inside the container,
  over the same `pct exec` channel updates already use, pinned to the row's
  `upstream_sha`.
- Their prompts are handled by the same two-tier rule as everything else: a
  curated schema if we have written one (dockge and komodo are simple: an app
  confirm, a Docker-dependency confirm, komodo's database choice), otherwise the
  live terminal.
- coolify/runtipi/dokploy prompt before fetching a third-party installer upstream
  explicitly disclaims as unaudited. Proxploy must NEVER answer that prompt
  itself. In the terminal fallback the user sees it and decides; there is no
  curated auto-answer for "run this unaudited third-party script". That is a
  decision only the human makes.

## Verification: by artefact, never by exit status

Unchanged from the prior analysis and still correct: the upstream cancel branch
is `exit 0` after the container exists, so exit status cannot prove an install
happened. The second step must confirm the app's own artefacts (e.g. dockge:
`/opt/dockge/compose.yaml` present and a running compose project). Per-app
evidence, defined alongside each curated schema. A failed check fails the install
loudly, files no App row, and leaves the container in place with the CTID named
(do not auto-destroy; the container is diagnostic evidence and the probe can be
wrong).

## What is settled vs open

Settled:
- Two modes: Default (one click, no questions) and Advanced (GUI form).
- CTID is optional; blank = next available. A typed CTID is validated for
  collisions against the selected host and blocks submit if taken; the backend
  rejects a taken CTID at install time as the real gate.
- Container customization (CPU/RAM/disk/etc.) is a full GUI form now, defaults
  from metadata, user-overridable.
- App-specific prompts: curated per-app GUI schema preferred; live terminal
  fallback where no schema exists.
- Proxploy never auto-answers from a hidden allowlist.
- Artefact verification, not exit status. No auto-destroy on failure.
- The five empty-container apps run their addon script as payload, handled by the
  same two-tier prompt rule.

Open (decide during build):
- The answer-schema format: how a curated app's questions and env-var mappings
  are declared (a per-app definition file/table), including pinned prompt text for
  tests.
- Whether the live terminal fallback is offered from day one or curated schemas
  ship for the top apps first with terminal following.
- Which apps get curated schemas first (drive from popularity).

## Unchanged constraints (carry from prior design)

- Scripts stay SHA-pinned; metadata (PocketBase) is presentation-only and never
  decides installability or type.
- Flat 2-`api.github.com`-call discovery ceiling; all payload fetches are
  raw.githubusercontent.com.
- Installs run over root SSH via `pct` / `pct exec`, the same channel the existing
  post-install checks and the e2e harness model. Any new step uses the same
  channel.
- LXC-only store; the classifier's interactive-input finding is not softened, it
  is what routes an app to "needs Advanced/terminal", not what hides it.
- No fork/vendor of upstream scripts.

## No em dashes anywhere in this document or any code implementing it.
