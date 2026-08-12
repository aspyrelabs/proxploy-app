/**
 * Google's Material Symbols stylesheet (see vite.config.ts's
 * materialSymbolsLink plugin, which injects the <link> into index.html)
 * does not set font-display on its @font-face rule: the browser's default
 * applies, which most engines implement as a short invisible period before
 * falling back to visible fallback-font text. This app's Icon component
 * renders each icon's readable ligature name ("settings") as its own text
 * content, so if that fallback period expires before the font arrives (a
 * slow or blocked CDN), the literal word flashes where a glyph belongs.
 *
 * This keeps every `.material-symbols-outlined` element invisible (see the
 * opacity rule in styles/tokens.css) until the font has actually settled,
 * success or failure, then reveals them all at once via an `icons-ready`
 * class on <html>. It still reveals icons on a failed load rather than
 * hiding them forever: every icon in this app sits next to a text label
 * (a nav item's own text, a button's aria-label) that already carries the
 * meaning, so a missing decorative glyph is a smaller problem than an icon
 * that never appears at all.
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
