import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { StockDetail } from './pages/StockDetail'
import { Watchlists } from './pages/Watchlists'
import { Signals } from './pages/Signals'
import { Activity } from './pages/Activity'
import { ErrorState } from './components/primitives'

/**
 * A last line of defence. A render error in one page must not take down the
 * shell — the user can still navigate away from a broken route.
 */
class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('Render error:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="mx-auto max-w-lg p-8">
          <div className="card">
            <ErrorState
              title="This view hit an error"
              message={this.state.error.message}
              onRetry={() => this.setState({ error: null })}
            />
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/stocks/:symbol" element={<StockDetail />} />
          <Route path="/watchlists" element={<Watchlists />} />
          <Route path="/signals" element={<Signals />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  )
}
