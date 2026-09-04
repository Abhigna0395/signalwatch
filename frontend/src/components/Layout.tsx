import { NavLink, Outlet, useLocation } from 'react-router-dom'
import clsx from 'clsx'
import { Activity, LayoutDashboard, ListChecks, Radar } from 'lucide-react'
import { QuickAdd } from './QuickAdd'
import { DemoBadge } from './primitives'
import { useApi } from '../hooks/useApi'
import { api } from '../lib/api'

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/watchlists', label: 'Watchlists', icon: ListChecks, end: false },
  { to: '/signals', label: 'Signals', icon: Radar, end: false },
  { to: '/activity', label: 'Activity', icon: Activity, end: false },
]

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
        <rect width="32" height="32" rx="8" className="fill-ink-700" />
        <path
          d="M6 21l5-6 4 3 5-8 6 5"
          className="stroke-accent"
          strokeWidth="2.5"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <div className="leading-none">
        <p className="text-sm font-semibold tracking-tight text-white">SIGNALWATCH</p>
        <p className="mt-0.5 hidden text-2xs text-slate-500 sm:block">
          Know what changed
        </p>
      </div>
    </div>
  )
}

export function Layout() {
  const { pathname } = useLocation()
  // Health is cheap and tells us whether we're on demo data; polling it slowly
  // also means a backend restart is reflected without a page reload.
  const { data: health } = useApi(() => api.health(), [], { refreshMs: 60_000 })

  return (
    <div className="flex min-h-full flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-ink-700 focus:px-3 focus:py-2 focus:text-sm"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-30 border-b border-line bg-ink-900/85 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-4 px-4 sm:px-6">
          <Logo />

          <nav className="ml-4 hidden items-center gap-0.5 md:flex" aria-label="Primary">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-colors',
                    isActive
                      ? 'bg-ink-700 text-white'
                      : 'text-slate-400 hover:bg-ink-750 hover:text-slate-200',
                  )
                }
              >
                <Icon className="h-3.5 w-3.5" aria-hidden />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <QuickAdd />
            {health?.provider_is_demo && <span className="hidden sm:block"><DemoBadge /></span>}
            <div
              className="flex h-8 w-8 items-center justify-center rounded-full border border-line bg-ink-700 text-2xs font-semibold text-slate-300"
              title="Demo Analyst · demo@signalwatch.app"
            >
              DA
            </div>
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto w-full max-w-[1600px] flex-1 px-4 pb-24 pt-5 sm:px-6 md:pb-10">
        <Outlet />
      </main>

      <footer className="hidden border-t border-line px-6 py-4 md:block">
        <p className="mx-auto max-w-[1600px] text-2xs text-slate-600">
          SignalWatch surfaces market changes for informational purposes. It does not provide
          investment advice.
          {health?.provider_is_demo && ' Displaying deterministic demo data.'}
        </p>
      </footer>

      {/* Mobile bottom navigation */}
      <nav
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-line bg-ink-850/95 backdrop-blur-xl md:hidden"
        aria-label="Primary"
      >
        {NAV.map(({ to, label, icon: Icon, end }) => {
          const active = end ? pathname === to : pathname.startsWith(to)
          return (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={clsx(
                'flex flex-col items-center gap-1 py-2.5 text-2xs transition-colors',
                active ? 'text-accent' : 'text-slate-500',
              )}
            >
              <Icon className="h-4 w-4" aria-hidden />
              {label}
            </NavLink>
          )
        })}
      </nav>
    </div>
  )
}
