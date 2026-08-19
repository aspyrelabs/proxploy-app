import RFB from '@novnc/novnc'
import { useEffect, useRef } from 'react'
import { Button } from '../ui/button'

export function VncConsole({ wsUrl, onDisconnect, bare = false }:
  { wsUrl: string; onDisconnect?: () => void
    /** Full bleed for the console window: the canvas takes whatever is left
     *  under the Ctrl+Alt+Del row instead of a fixed 480px box with a border.
     *  Those two buttons stay in both modes, they are the only way to send
     *  Ctrl+Alt+Del to a guest that has taken the keystroke itself. */
    bare?: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  const rfb = useRef<InstanceType<typeof RFB> | null>(null)

  useEffect(() => {
    if (!box.current) return
    const target = box.current
    let unmounting = false
    let conn: InstanceType<typeof RFB> | null = null

    // wsUrl carries a single-use ticket, same as Terminal.tsx: a second RFB
    // opened against it is refused by the server and tears down the first,
    // working one. StrictMode's synchronous mount/cleanup/mount replay in dev
    // opens the socket a tick late so the throwaway invocation's cleanup can
    // cancel it before it ever redeems the ticket.
    const openTimer = setTimeout(() => {
      conn = new RFB(target, wsUrl)
      conn.addEventListener('disconnect', () => { if (!unmounting) onDisconnect?.() })
      rfb.current = conn
    }, 0)
    return () => {
      unmounting = true
      clearTimeout(openTimer)
      conn?.disconnect()
    }
  }, [wsUrl])

  return (
    <div className={bare ? 'flex h-full flex-col p-2' : undefined}>
      <div className="mb-2 flex gap-2">
        <Button variant="ghost" className="px-2 py-1 text-[11px]"
          onClick={() => rfb.current?.sendCtrlAltDel()}>
          Ctrl+Alt+Del
        </Button>
        <Button variant="ghost" className="px-2 py-1 text-[11px]"
          onClick={() => box.current?.requestFullscreen()}>
          Fullscreen
        </Button>
      </div>
      <div ref={box} style={{ background: '#0a0e14' }}
        className={bare ? 'flex-1 min-h-0' : 'h-[480px] rounded-ctl border border-line-soft'} />
    </div>
  )
}
