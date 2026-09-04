import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { CheckCircle2, AlertTriangle, Info, X } from 'lucide-react'
import clsx from 'clsx'

type ToastKind = 'success' | 'error' | 'info'
interface Toast {
  id: number
  kind: ToastKind
  message: string
}

const ToastContext = createContext<{ push: (kind: ToastKind, message: string) => void }>({
  push: () => {},
})

export function useToast() {
  return useContext(ToastContext)
}

const ICONS = { success: CheckCircle2, error: AlertTriangle, info: Info }
const STYLES: Record<ToastKind, string> = {
  success: 'border-up/30 text-up',
  error: 'border-down/30 text-down',
  info: 'border-line-strong text-slate-300',
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback((kind: ToastKind, message: string) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, kind, message }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500)
  }, [])

  const value = useMemo(() => ({ push }), [push])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed bottom-20 right-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2 sm:bottom-6"
        role="status"
        aria-live="polite"
      >
        {toasts.map((toast) => {
          const Icon = ICONS[toast.kind]
          return (
            <div
              key={toast.id}
              className={clsx(
                'pointer-events-auto flex animate-fade-up items-start gap-2.5 rounded-lg border bg-ink-750 px-3.5 py-3 text-sm shadow-lift',
                STYLES[toast.kind],
              )}
            >
              <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span className="flex-1 text-slate-200">{toast.message}</span>
              <button
                onClick={() => setToasts((t) => t.filter((x) => x.id !== toast.id))}
                className="rounded text-slate-500 hover:text-slate-200"
                aria-label="Dismiss notification"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}
