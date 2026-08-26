/**
 * Material Symbols (see vite.config.ts's materialSymbolsLink plugin) sets no
 * font-display, so before the font loads the ligature name ("settings")
 * flashes as literal text. Keep every `.material-symbols-outlined` invisible
 * (opacity rule in styles/tokens.css) until the font settles, then reveal via
 * an `icons-ready` class on <html>. Reveal on failure too: every icon sits
 * next to a text label carrying the meaning, so a missing glyph beats an icon
 * that never appears.
 */
export function revealIconsWhenReady(doc: Document = document): void | Promise<void> {
  const reveal = () => doc.documentElement.classList.add('icons-ready')
  const fonts = (doc as Document & { fonts?: { load(font: string): Promise<unknown> } }).fonts
  if (!fonts) {
    reveal()
    return
  }
  return fonts.load('400 24px "Material Symbols Outlined"').then(reveal, reveal)
}

revealIconsWhenReady()
