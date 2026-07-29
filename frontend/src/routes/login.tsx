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
  return (
    <div className="grid min-h-screen place-items-center">
      {/* cast: circular import with router.tsx blocks full route-tree inference here */}
      <LoginForm onSuccess={() => navigate({ to: '/cluster' as never })} />
    </div>
  )
}
