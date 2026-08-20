/**
 * The "an update is waiting for this app" mark, in one place.
 *
 * A dot, not the word "update": the pill this replaced was as wide as some
 * app names and pushed the row's most important text around.
 *
 * Losing the word means the accessible name is now the ONLY wording there is,
 * so it carries the whole sentence rather than the bare label "update", and
 * the title repeats it for a sighted reader who cannot guess what an orange
 * dot means. That is also why this is a component rather than a copied span:
 * the markup was duplicated across the apps table, the guest list and the app
 * card, and three copies of an accessible name is three chances for one of
 * them to drift into meaninglessness.
 */
export function UpdateDot() {
  return (
    <span role="img" aria-label="Update available"
          title="An update is available for this app"
          className="size-2 shrink-0 rounded-full bg-amber" />
  )
}
