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
      {/* '/cluster' lands in the route tree in Task 14; cast until then */}
      <LoginForm onSuccess={() => navigate({ to: '/cluster' as never })} />
    </div>
  )
}
