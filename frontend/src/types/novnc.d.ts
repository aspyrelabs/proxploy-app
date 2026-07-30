// @novnc/novnc ships no type declarations, and the community @types/novnc__novnc
// package (last published for an older "lib/rfb" build layout) doesn't match
// this package's actual "./core/rfb.js" root export — so it's a minimal local
// shim instead, covering only what VncConsole.tsx uses.
declare module '@novnc/novnc' {
  export default class RFB {
    constructor(target: HTMLElement, url: string, options?: Record<string, unknown>)
    addEventListener(type: string, listener: (event: unknown) => void): void
    removeEventListener(type: string, listener: (event: unknown) => void): void
    disconnect(): void
    sendCtrlAltDel(): void
  }
}
