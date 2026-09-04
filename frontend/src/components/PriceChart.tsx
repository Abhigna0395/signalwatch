import { useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import clsx from 'clsx'
import { useApi } from '../hooks/useApi'
import { api } from '../lib/api'
import { formatPrice } from '../lib/format'
import { ErrorState, Skeleton } from './primitives'

const RANGES = ['1W', '1M', '3M', '1Y'] as const
type Range = (typeof RANGES)[number]

export function PriceChart({
  symbol,
  currency,
  previousClose,
}: {
  symbol: string
  currency: string
  previousClose: number | null
}) {
  const [range, setRange] = useState<Range>('3M')
  const { data, error, isLoading, reload } = useApi(() => api.history(symbol, range), [symbol, range])

  const points = data?.points ?? []
  const rising =
    points.length > 1 ? points[points.length - 1].close >= points[0].close : true
  const stroke = rising ? '#22D391' : '#F26B6B'

  return (
    <div className="card p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-200">Price</h2>
        <div className="flex gap-1" role="group" aria-label="Chart time range">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              aria-pressed={range === r}
              className={clsx(
                'rounded-md px-2 py-1 text-2xs font-medium transition-colors',
                range === r
                  ? 'bg-ink-700 text-white'
                  : 'text-slate-500 hover:bg-ink-750 hover:text-slate-300',
              )}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <ErrorState title="Chart unavailable" message={error.message} onRetry={reload} />
      ) : points.length === 0 ? (
        <div className="flex h-64 items-center justify-center text-xs text-slate-500">
          No price history available for this range.
        </div>
      ) : (
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 4, right: 4, left: -12, bottom: 0 }}>
              <defs>
                <linearGradient id={`fill-${symbol}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={stroke} stopOpacity={0.22} />
                  <stop offset="100%" stopColor={stroke} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(148,163,184,0.08)" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fill: '#64748B', fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                minTickGap={40}
                tickFormatter={(d: string) =>
                  new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
                }
              />
              <YAxis
                domain={['auto', 'auto']}
                tick={{ fill: '#64748B', fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                width={58}
                tickFormatter={(v: number) => formatPrice(v, currency)}
              />
              <Tooltip
                contentStyle={{
                  background: '#111621',
                  border: '1px solid rgba(148,163,184,0.2)',
                  borderRadius: 8,
                  fontSize: 12,
                }}
                labelStyle={{ color: '#94A3B8', marginBottom: 4 }}
                labelFormatter={(d: string) =>
                  new Date(d).toLocaleDateString(undefined, {
                    weekday: 'short',
                    day: 'numeric',
                    month: 'short',
                    year: 'numeric',
                  })
                }
                formatter={(value: number, name: string) => [
                  formatPrice(value, currency),
                  name === 'close' ? 'Close' : name === 'sma20' ? '20-day avg' : '50-day avg',
                ]}
              />
              <Legend
                verticalAlign="top"
                height={24}
                iconType="plainline"
                wrapperStyle={{ fontSize: 10, color: '#64748B' }}
                formatter={(value: string) =>
                  value === 'close' ? 'Close' : value === 'sma20' ? '20-day avg' : '50-day avg'
                }
              />
              {previousClose !== null && (
                <Line
                  dataKey={() => previousClose}
                  stroke="rgba(148,163,184,0.3)"
                  strokeDasharray="3 3"
                  dot={false}
                  legendType="none"
                  isAnimationActive={false}
                  name="prev"
                />
              )}
              <Area
                type="monotone"
                dataKey="close"
                stroke={stroke}
                strokeWidth={1.8}
                fill={`url(#fill-${symbol})`}
                dot={false}
                animationDuration={600}
              />
              <Line
                type="monotone"
                dataKey="sma20"
                stroke="#5EA8FF"
                strokeWidth={1.5}
                strokeDasharray="5 3"
                dot={false}
                connectNulls
                animationDuration={600}
              />
              <Line
                type="monotone"
                dataKey="sma50"
                stroke="#FF9F45"
                strokeWidth={1.5}
                strokeDasharray="2 3"
                dot={false}
                connectNulls
                animationDuration={600}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
