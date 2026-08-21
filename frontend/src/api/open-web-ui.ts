import { useMutation } from '@tanstack/react-query'
import { api, apiErrorDetail } from './client'
import type { AppRow } from './hooks'
import { notify } from '../lib/notify'

// The URL is built by the backend, not here, because the browser cannot work
// out two thirds of it. The address is read live off the guest's own NIC
// config on every click, never off a column set at install: a DHCP lease or a
// manual re-IP moves the guest and a cached value would silently point at the
// old one. The SCHEME is the half this page has no way to answer at all: the
// catalog upstream gives us carries a port and no protocol, so the app itself
// has to be asked, and a cross-origin request from here to a self-signed
// https app fails the same opaque way as an app that is not there.
//
// This used to be `${app.web_protocol || 'http'}://...` over an address
// fetched from /network. Every row said "http", because install and adopt
// wrote that string whether or not it was true, so Actual Budget (https on
// 5006) opened at http:// and failed to load.
export function useOpenWebUi(app: AppRow) {
  return useMutation({
    mutationFn: async (tab: Window | null) => {
      // The tab is opened by the click handler, not here. Looking the URL up
      // first would put this window.open after an await, outside the user
      // gesture, and a popup blocker would drop it: the one thing the button
      // exists to do. So the tab is opened empty up front and pointed at the
      // app once the URL comes back.
      const { url } = await api<{ url: string }>(`/apps/${app.id}/web-url`)
      if (tab) tab.location.href = url
      else window.open(url, '_blank', 'noopener,noreferrer')
    },
    // The blank tab is closed here rather than at each throw site so every
    // failure clears it, including the ones the backend reports.
    onError: (e, tab) => {
      tab?.close()
      // The backend's 409s name what is actually missing (no address, no
      // port, the app did not answer), so they are shown as written instead
      // of being flattened into one sentence that says none of it.
      notify.error(apiErrorDetail(e, `Could not open ${app.name}.`))
    },
  })
}
