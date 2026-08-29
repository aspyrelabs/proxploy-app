import '@fontsource/space-grotesk/400.css'
import '@fontsource/space-grotesk/600.css'
import '@fontsource/space-grotesk/700.css'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/600.css'
import './styles/tokens.css'
import './lib/reveal-icons-when-ready'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { router } from './router'
import { applyStoredTheme } from './lib/theme'
import { notify } from './lib/notify'
import { apiErrorDetail } from './api/client'

// Runs before the shell mounts so every route (including /login, which never
// mounts Topbar/ThemeToggle) honours a previously chosen theme instead of
// index.html's static data-theme="dark".
applyStoredTheme()

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 15_000 } },
  // Last resort for a mutation nobody handled. Of 107 mutate() call sites, 86
  // pass an onError and the rest relied on nothing: the request failed and the
  // button simply did nothing. That went unnoticed for as long as it did
  // because the unhandled paths were ones that had never actually failed. The
  // install 409 was the first to fire and it was completely silent.
  //
  // Skipped when the mutation defines its own onError, so a handled failure is
  // reported once, in the words its own call site chose.
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => {
      if (mutation.options.onError) return
      notify.error(apiErrorDetail(error, 'That did not work. Try again.'))
    },
  }),
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
