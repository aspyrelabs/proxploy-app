import { createRoute, Link, useParams } from '@tanstack/react-router'
import { useState } from 'react'
import { InstallDialog } from '../components/InstallDialog'
import { StoreDetailContent } from '../components/StoreDetailContent'
import { shellRoute } from './shell'
import { quietCls } from '../components/ui/button'

/**
 * ROUTE shell for an app's detail view. The content lives in
 * components/StoreDetailContent.tsx so the Store grid can render the same
 * thing in its "Read more" dialog without the two drifting apart.
 *
 * Must not be deleted: backend/proxploy/api/search.py emits
 * `href: /store/{slug}` for every command-palette result, so this route is
 * what makes those results land (and what a pasted/bookmarked URL renders).
 *
 * InstallDialog opens here — and from the Store page's popup — so exactly one
 * Dialog is ever mounted: never a second focus trap or a second "Install"
 * button for e2e/journey.spec.ts to disambiguate.
 */
export function StoreDetailPage() {
  const { slug } = useParams({ strict: false }) as { slug: string }
  const [installing, setInstalling] = useState<string | null>(null)
  return (
    <div>
      <Link to={'/store' as never} className={`text-[12px] ${quietCls}`}>
        ← App Store
      </Link>
      <StoreDetailContent slug={slug} onInstall={setInstalling} />
      {installing && (
        <InstallDialog slug={installing} onClose={() => setInstalling(null)} />
      )}
    </div>
  )
}

// Registered in router.tsx next to storeRoute. `/store` is static and this is
// dynamic, so the router ranks the exact match first and the two never compete.
export const storeDetailRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/store/$slug',
  component: StoreDetailPage,
})
