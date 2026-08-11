import { createRoute, useNavigate } from '@tanstack/react-router'
import { rootRoute } from '../router'
import { LoginForm } from '../components/LoginForm'

export const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
})

function LoginPage() {
  const navigate = useNavigate()
  // Plain URLSearchParams read, not a route search schema: this is the one
  // query param the login page ever looks at (set by GET /auth/oidc/callback's
  // failure redirect, Task 11), not worth a validateSearch contract.
  const ssoFailed = typeof window !== 'undefined'
    && new URLSearchParams(window.location.search).get('error') === 'oidc'
  return (
    <div className="grid min-h-screen place-items-center">
      <div className="flex flex-col items-center gap-3">
        {ssoFailed && (
          <p className="w-[360px] text-center text-[12.5px] text-red">
            Single sign-on failed, try again or use a password.
          </p>
        )}
        {/* cast: circular import with router.tsx blocks full route-tree inference here */}
        <LoginForm onSuccess={() => navigate({ to: '/hosts' as never })} />
      </div>
    </div>
  )
}
