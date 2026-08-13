import { createRoute, Link, useParams } from '@tanstack/react-router'
import { useState } from 'react'
import { InstallDialog } from '../components/InstallDialog'
import { StoreDetailContent } from '../components/StoreDetailContent'
import { shellRoute } from './shell'

/**
 * The ROUTE shell for an app's detail view. Everything inside it lives in
 * components/StoreDetailContent.tsx, because the Store grid renders that same
 * content in a Dialog: "Read more" on a card opens a popup rather than
 * navigating, and one component in two shells is what stops the popup and the
 * page drifting apart.
 *
 * This route stays, and must: backend/proxploy/api/search.py emits
 * `href: /store/{slug}` for every command-palette result, so deleting it would
 * reintroduce the "palette result opens Not Found" bug. It is also what a
 * pasted or bookmarked URL renders.
 *
 * InstallDialog is opened HERE rather than inside the content, for the same
 * reason the popup opens it from the Store page: exactly one Dialog is ever
 * mounted, so there is never a second focus trap or a second "Install" button
 * for e2e/journey.spec.ts to disambiguate.
 */
export function StoreDetailPage() {
  const { slug } = useParams({ strict: false }) as { slug: string }
  const [installing, setInstalling] = useState<string | null>(null)
  return (
    <div>
      <Link to={'/store' as never} className="text-[12px] text-text-3 hover:text-text">
        ← App Store
      </Link>
      <StoreDetailContent slug={slug} onInstall={setInstalling} />
      {installing && (
        <InstallDialog slug={installing} onClose={() => setInstalling(null)} />
      )}
    </div>
  )
}

// Registered in router.tsx next to storeRoute. `/store` is a static path and
// this is a dynamic one, so the router ranks the exact match first and the two
// never compete. This path is not invented here: backend/proxploy/api/search.py
// already emits `href: /store/{slug}` for command-palette results, so making
// the route exist is what makes those results land somewhere.
export const storeDetailRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/store/$slug',
  component: StoreDetailPage,
})
