import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Tooltip } from 'radix-ui'
import { Toaster } from 'sonner'
import '@fontsource-variable/inter'
import '@fontsource/montserrat/400.css'
import '@fontsource/montserrat/600.css'
import '@fontsource/montserrat/800.css'
import '@fontsource/montserrat/900.css'
import '@fontsource/poppins/400.css'
import '@fontsource/poppins/600.css'
import '@fontsource/poppins/800.css'
import '@fontsource/bebas-neue/400.css'
import '@fontsource/anton/400.css'
import '@fontsource/dm-serif-display/400.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/700.css'
import './index.css'
import { AppShell } from '@/components/layout/AppShell'
import { BudgetProvider } from '@/hooks/budget'
import { ImporterProvider } from '@/hooks/importer'
import { ApiError } from '@/lib/api'
import { EditorPage } from '@/pages/EditorPage'
import { LibraryPage } from '@/pages/LibraryPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { SettingsPage } from '@/pages/SettingsPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
      refetchOnWindowFocus: true,
      staleTime: 2_000,
    },
  },
})

const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: '/', element: <LibraryPage /> },
      { path: '/projects/:projectId', element: <EditorPage /> },
      { path: '/settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <Tooltip.Provider delayDuration={250}>
        <BudgetProvider>
          <ImporterProvider>
            <RouterProvider router={router} />
          </ImporterProvider>
        </BudgetProvider>
        <Toaster
          theme="system"
          position="bottom-left"
          toastOptions={{
            classNames: { description: '!text-fg-muted' },
            style: {
              background: 'var(--surface-2)',
              border: '1px solid var(--line-strong)',
              color: 'var(--fg)',
              fontFamily: 'var(--font-sans)',
            },
          }}
        />
      </Tooltip.Provider>
    </QueryClientProvider>
  </StrictMode>,
)
