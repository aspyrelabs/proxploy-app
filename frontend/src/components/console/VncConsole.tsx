import RFB from '@novnc/novnc'
import { useEffect, useRef } from 'react'
import { Button } from '../ui/button'

export function VncConsole({ wsUrl, onDisconnect }: { wsUrl: string; onDisconnect?: () => void }) {
  const box = useRef<HTMLDivElement>(null)
  const rfb = useRef<InstanceType<typeof RFB> | null>(null)

  useEffect(() => {
    if (!box.current) return
    let unmounting = false
    const conn = new RFB(box.current, wsUrl)
    conn.addEventListener('disconnect', () => { if (!unmounting) onDisconnect?.() })
    rfb.current = conn
    return () => { unmounting = true; conn.disconnect() }
  }, [wsUrl])

  return (
    <div>
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
      <div ref={box} style={{ background: '#0a0e14' }} className="h-[480px] rounded-ctl border border-line-soft" />
    </div>
  )
}
