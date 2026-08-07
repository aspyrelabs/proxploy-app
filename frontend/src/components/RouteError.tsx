import { Button } from './ui/button'

/**
 * Replaces TanStack Router's built-in ErrorComponent, which styles itself
 * with inline `style={}` and so ignores the theme entirely.
 *
 * An unreachable backend and a bug in the app want different things from the
 * user, one wants a retry, the other wants a way out and (in dev) a stack.
 * Collapsing them into "Something went wrong" is exactly what the built-in
 * fallback already does badly.
 */
export function RouteError({ error, reset }: { error: unknown; reset?: () => void }) {
  // A fetch that never reached the server throws TypeError('Failed to fetch')
  // in every browser we target; an ApiError means the server answered, so it
  // is reachable and something else is wrong.
  const unreachable = error instanceof TypeError && /fetch/i.test(error.message)
  return (
    <div className="grid min-h-screen place-items-center bg-ink p-6">
      <div className="w-[520px] rounded-card border border-line-soft bg-panel p-7 text-center">
        <h1 className="font-display text-[18px] text-text">
          {unreachable ? 'Proxploy is not answering' : 'Something in Proxploy broke'}
        </h1>
        <p className="mt-2 text-[13px] text-text-2">
          {unreachable
            ? 'The backend did not respond. It may be restarting after an update.'
            : 'This is a bug, not something you did. The page could not be rendered.'}
        </p>
        {reset && <Button className="mt-5" onClick={reset}>Try again</Button>}
        {import.meta.env.DEV && (
          <pre className="mt-4 overflow-x-auto rounded-ctl bg-elev p-3 text-left font-mono text-[11px] text-text-3">
            {String(error instanceof Error ? error.stack ?? error.message : error)}
          </pre>
        )}
      </div>
    </div>
  )
}
