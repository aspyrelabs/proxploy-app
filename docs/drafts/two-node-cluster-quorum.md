# DRAFT for the public docs site

Destination: docs.proxploy.com, troubleshooting section. Not part of the
development docs. Written 2026-08-14 from a real two-node cluster; whoever
picks this up should match the site's existing page structure, frontmatter and
heading style, and check the commands against the current Proxmox release
before publishing.

The one editorial decision already made, please keep it: QDevice is presented
first and `two_node: 1` second, with its tradeoffs stated in the same breath.
Publishing `two_node: 1` as flat advice would read as safe when it is not.

---

# Two-node clusters and quorum

If you run Proxmox as a cluster of exactly two nodes, there is a Proxmox
setting you should check before relying on Proxploy. This is not a Proxploy
setting and Proxploy cannot change it for you, but the way it fails is easy to
mistake for a Proxploy fault.

## The symptom

One node goes down. In Proxploy the surviving host still shows as connected,
its node card still updates, CPU and memory graphs keep moving. Everything
looks healthy.

Then you try to do something and it fails:

- installing an app fails
- changing a container's configuration fails
- storage changes fail
- the errors mention a read-only file system, or fail with no clear cause

Reads work, writes do not.

## Why it happens

Proxmox stores cluster configuration in `/etc/pve`, a shared filesystem backed
by corosync. To accept writes, a node must hold quorum, meaning it can see
more than half the cluster's votes.

On a two-node cluster the default is two votes with quorum at two. Lose one
node and the survivor holds one vote out of two, which is not more than half.
Corosync therefore makes `/etc/pve` read-only on the node that is still
running. The node is up, the API answers, guests keep running, but nothing can
be written.

Proxploy keeps reporting the host as healthy because, from its point of view,
it is: the Proxmox API still responds and `/cluster/resources` still returns
data. Only writes fail. If you enrolled both nodes in Proxploy, this is more
confusing rather than less, because the surviving endpoint keeps answering for
the whole cluster.

## Check whether it applies to you

Run this on either node:

```bash
pvecm status
```

Look at these lines:

```
Expected votes:   2
Quorum:           2
```

`Quorum: 2` on a two-node cluster means you are exposed. `Quorum: 1` means it
is already handled.

This page does not apply to you if:

- your hosts are standalone and not clustered, since there is no quorum at all
- your cluster has three or more nodes, since losing one still leaves a
  majority

## Option 1: add a QDevice (recommended)

A QDevice is a third vote provided by a small service on any other always-on
machine, such as a NAS or a Raspberry Pi. It does not have to be a Proxmox
node and it does not run any guests. With three votes, losing one node leaves
two, which is a majority, and the survivor keeps working normally.

This is Proxmox's own recommendation for two-node clusters, and it is the only
option here with no tradeoff.

On the third machine, install the `corosync-qnetd` package. On both Proxmox
nodes:

```bash
apt install corosync-qdevice
```

Then, from one node:

```bash
pvecm qdevice setup <ip-of-the-third-machine>
```

Confirm with `pvecm status` that total votes is now 3.

## Option 2: enable two-node mode

If you cannot add a third machine, corosync has a two-node mode that lowers
quorum to one so the survivor keeps working.

Read the tradeoffs below before using it. It is a real reduction in safety,
not just a setting.

On one node, edit the cluster configuration:

```bash
cp /etc/pve/corosync.conf /etc/pve/corosync.conf.bak
cp /etc/pve/corosync.conf /etc/pve/corosync.conf.new
```

In `/etc/pve/corosync.conf.new`, add `two_node: 1` inside the `quorum` block
and increase `config_version` by one:

```
quorum {
  provider: corosync_votequorum
  two_node: 1
}
```

Then move it into place. Editing the `.new` file and moving it is the
supported way to change this; Proxmox picks up the change and distributes it
to both nodes.

```bash
mv /etc/pve/corosync.conf.new /etc/pve/corosync.conf
pvecm status
```

You should now see `Quorum: 1`.

### The two tradeoffs, both real

**No fencing means split-brain is possible.** If the network link between the
nodes fails while both are still running, each one now has quorum on its own
and each believes it is the survivor. Both can write. On a cluster with no
shared storage and no HA this is usually harmless. If you use shared storage
or HA, do not use this option, use a QDevice.

**Cold starts wait for both nodes.** Corosync enables `wait_for_all` together
with `two_node`. After both nodes have been powered off, the first one to come
back will not have quorum until it has seen the other at least once. This is
deliberate and it prevents split-brain on boot, but it surprises people during
a power cut: one node is up, and `/etc/pve` is still read-only.

If you need that node working before the other returns, run:

```bash
pvecm expected 1
```

This is temporary and lasts until corosync restarts. Use it to get out of
trouble, not as a permanent configuration.

## What Proxploy does about it

Nothing, deliberately. Quorum belongs to Proxmox, and a tool that silently
lowered your cluster's safety threshold to make its own writes succeed would
be making a decision that is not its to make.

If a write fails while the host still shows as connected, run `pvecm status`
on the node before assuming the problem is in Proxploy.
