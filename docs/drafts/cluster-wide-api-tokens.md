# DRAFT for the public docs site

Destination: docs.proxploy.com, troubleshooting section. Not part of the
development docs. Written 2026-08-15, from a real support episode the same
night that cost an evening on a two-node cluster named "lab-cluster" (node1,
node2); whoever picks this up should match the site's existing page
structure, frontmatter and heading style, and check the commands against the
current Proxmox release before publishing.

The editorial decisions already made, please keep them: lead with the fact
that the API token is cluster-wide, since everything else in this page
follows from it and readers arrive assuming tokens are per node. Per-node
tokens are mentioned only as the worse fallback, with the cost of that choice
stated in the same breath, never as the default remedy.

---

# API tokens across a cluster

If your Proxmox nodes are in a cluster, an API token you create for Proxploy
on one node already exists on every node in that cluster. Proxploy does not
know that yet on its own, and the way that gap shows up is easy to mistake for
a broken token.

## The symptom

You enroll a second node of a cluster you already use with Proxploy. One node
shows a capability, say monitoring or backups, as configured and working. The
other node of the same cluster shows the same capability as not configured.

You go to fix it by running the setup script again on the second node. It
fails, reporting that the user, the roles and the tokens already exist.

Both of those are expected. Neither means the token is broken.

## Why it happens

Proxmox keeps its users, roles, ACLs and API tokens in `/etc/pve`, and
`/etc/pve` is replicated across every node in the cluster. Create a token on
one node and the rest of the cluster has it immediately, no extra step
needed. In a real two-node test, running the setup script on node2 only was
enough for node1 to already list the `proxploy@pve` user, all four tokens
(monitoring, lifecycle, console, backup), and the `ProxployConsole` role
including a privilege that had actually been added from the other node.

So the setup script only needs to run once per cluster, not once per node.
Run it again on a second node and it will tell you the user, roles and
tokens already exist. That is the script confirming the cluster already has
them, not a failure to fix.

The script is also safe to re-run for another reason: its role lines
converge to the same set of privileges whether the role is new or already
there. Its token lines deliberately do not touch a token that already
exists, because re-creating a token mints a new secret, and that would break
the copy of the old secret already stored in Proxploy for a host that is
currently working. If a token line reports a failure, read it as the token
existing and the stored secret still being valid. Leave it alone.

## Why Proxploy still shows the second node as unconfigured

Proxmox scopes the token to the cluster. Proxploy scopes stored credentials
to the host. Those are different things, and enrolling a second node of the
same cluster does not carry the first node's stored token over to it.

Proxploy does not currently copy a stored token to sibling hosts on its own,
so until the second node has its own copy of the same token id and secret
recorded against it, it will report that capability as not configured, even
though the same token would authenticate against it without any trouble. You
are not creating a second token here. You are giving the second host the same
token id and the same secret you already have on the first, because it is one
token being used from two hosts.

## What to actually do

1. On the node that already works, find the token id and secret you recorded
   for Proxploy (monitoring, lifecycle, console or backup, whichever is
   showing unconfigured).
2. On the second node's entry in Proxploy, enter that same token id and the
   same secret.
3. Do not re-run the setup script expecting it to fix this. It already told
   you the token exists, which is correct, and running it again will not put
   the secret into the second host's entry in Proxploy for you.

## If you did not keep the secret

A Proxmox API token secret is shown exactly once, at creation. If you did not
save it, you cannot recover it. From here you have two options.

The better one is to re-create that one token, which mints a new secret, and
update the stored copy on every host in Proxploy that uses it. This keeps one
token doing one job across the whole cluster.

The worse one is to create an additional, per-node token instead. This
avoids updating the existing hosts, but it multiplies what you have to
rotate and audit later for no real benefit, since every extra token is
another secret that can go stale or leak. Prefer re-minting the one token
unless you have a specific reason not to.
