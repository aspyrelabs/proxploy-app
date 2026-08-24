/**
 * The brand mark. Two artwork files per lockup, not one recoloured file.
 *
 * The old mark was traced into inline paths with every fill set to
 * `currentColor`, so one copy served both themes. This artwork is
 * multi-coloured (amber, plus near-white on dark and near-black on light), so
 * there is no single colour to inherit and the two variants are genuinely
 * different files.
 *
 * Which one shows is decided in CSS, not JavaScript: `dark:` is bound to
 * `[data-theme="dark"]` in styles/tokens.css, so both are in the markup and
 * the browser picks. That means the swap lands in the same frame as the theme
 * itself, including mid-way through ThemeToggle's view transition, where a
 * React state update would arrive a frame late and flicker.
 *
 * The theme gate is on a `display: contents` wrapper rather than on the image.
 * Callers pass their own display classes (Topbar sends `hidden ... sm:block`
 * for the responsive swap), and a caller's `sm:block` beat the variant's
 * `hidden`, so at wide sizes in light mode BOTH marks rendered. The wrapper
 * takes the theme decision, `contents` keeps it out of the layout, and the
 * caller's classes still land on the image where they were aimed.
 *
 * The favicon is deliberately NOT handled here. A tab icon sits on browser
 * chrome, which follows the operating system rather than this app's theme, so
 * index.html scopes those to prefers-color-scheme instead.
 */

/** The square mark on its own: the small-screen form, cropped tight. */
export function GhostMark({ className = "" }: { className?: string }) {
  return (
    <>
      <span className="hidden dark:contents">
        <img src="/proxploy-favicon-dark.svg" alt="" aria-hidden="true"
             className={className} />
      </span>
      <span className="contents dark:hidden">
        <img src="/proxploy-favicon-light.svg" alt="" aria-hidden="true"
             className={className} />
      </span>
    </>
  );
}

/**
 * Mark plus wordmark, 1010x205 in its own units (aspect ratio ~4.9), so callers
 * set a height and leave the width to `w-auto`.
 *
 * READ THE FILE NAMES AS THE INK, NOT THE THEME. `-dark` is the dark-inked
 * artwork, which belongs on a LIGHT background, and `-light` is the near-white
 * one for a DARK background. They were wired the other way round at first,
 * which puts black on near-black in dark mode and all but hides the wordmark.
 * The favicon pair below is named the other way (by theme) and is correct as
 * it stands; do not "make them consistent" by flipping one without looking at
 * the fills in both.
 */
export default function Logo({ className = "" }: { className?: string }) {
  return (
    <>
      <span className="hidden dark:contents">
        <img src="/proxploy-logo-light.svg" alt="Proxploy" className={className} />
      </span>
      <span className="contents dark:hidden">
        <img src="/proxploy-logo-dark.svg" alt="Proxploy" className={className} />
      </span>
    </>
  );
}
