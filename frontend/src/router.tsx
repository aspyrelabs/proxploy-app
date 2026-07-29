import { Outlet, createRootRoute, createRouter } from '@tanstack/react-router'

export const rootRoute = createRootRoute({ component: () => <Outlet /> })

import { loginRoute } from './routes/login'

export const routeTree = rootRoute.addChildren([loginRoute])
export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
