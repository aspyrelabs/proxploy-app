import { useMutation } from '@tanstack/react-query'
import { api } from './client'
import type { AppRow } from './hooks'
import { notify } from '../lib/notify'

// Address is read live off the guest's own NIC config on click, never off
// a column set at install: a DHCP lease or a manual re-IP moves the guest
// and a value cached at install would silently point at the old one. Same
// endpoint the Network tab's edit path already reads through
// (api/apps.py::app_network / services guest_nics, "no cache").
export function useOpenWebUi(app: AppRow) {
  return useMutation({
    mutationFn: async (tab: Window | null) => {
      // `addresses`, not `ip`. `ip` is the CONFIG, and a container on DHCP has
      // the literal word `dhcp` there, so this used to reject every DHCP guest
      // and report that it could not determine the address. `addresses` is
      // what the container actually holds: the configured address when there
      // is one, else what PVE reports on /lxc/{vmid}/interfaces.
      const nics = await api<{ addresses: string[] | null }[]>(`/apps/${app.id}/network`)
      const addr = nics.flatMap((n) => n.addresses ?? [])[0]?.split('/')[0]
      if (!addr) { tab?.close(); throw new Error('no address') }
      const url = `${app.web_protocol || 'http'}://${addr}:${app.catalog_port}${app.web_path || '/'}`
      // The tab is opened by the click handler, not here. Looking the address
      // up first would put this window.open after an await, outside the user
      // gesture, and a popup blocker would drop it: the one thing the button
      // exists to do. So the tab is opened empty up front and pointed at the
      // app once the address comes back.
      if (tab) tab.location.href = url
      else window.open(url, '_blank', 'noopener,noreferrer')
    },
    onError: () => notify.error(`Could not determine ${app.name}'s address.`),
  })
}
