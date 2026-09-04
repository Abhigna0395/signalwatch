/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // ── Surfaces ────────────────────────────────────────────────────────
        // A near-black navy rather than pure black: it keeps the borders and
        // elevation steps visible without the whole page turning grey.
        ink: {
          900: '#070910',
          850: '#0A0D15',
          800: '#0D111A',
          750: '#111621',
          700: '#161C29',
          650: '#1C2331',
          600: '#232B3B',
        },
        line: {
          DEFAULT: 'rgba(148, 163, 184, 0.11)',
          strong: 'rgba(148, 163, 184, 0.20)',
        },
        // ── Financial semantics ─────────────────────────────────────────────
        // Green and red are reserved *exclusively* for direction of money.
        // Nothing decorative is allowed to use them.
        up: { DEFAULT: '#22D391', soft: 'rgba(34, 211, 145, 0.12)' },
        down: { DEFAULT: '#F26B6B', soft: 'rgba(242, 107, 107, 0.12)' },
        // ── Attention bands ─────────────────────────────────────────────────
        // Deliberately amber/blue/slate rather than red/green, so a high
        // attention score is never mistaken for a bullish signal.
        attention: {
          high: '#FF9F45',
          watch: '#5EA8FF',
          stable: '#7A879C',
        },
        accent: '#38E8A0',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      letterSpacing: {
        label: '0.08em',
      },
      boxShadow: {
        card: '0 1px 2px rgba(0,0,0,0.4), 0 8px 24px -12px rgba(0,0,0,0.6)',
        lift: '0 2px 4px rgba(0,0,0,0.4), 0 16px 40px -16px rgba(0,0,0,0.7)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
        'pulse-ring': {
          '0%': { boxShadow: '0 0 0 0 rgba(255,159,69,0.45)' },
          '70%': { boxShadow: '0 0 0 7px rgba(255,159,69,0)' },
          '100%': { boxShadow: '0 0 0 0 rgba(255,159,69,0)' },
        },
segment: { from: { strokeDashoffset: 'var(--dash)' }, to: { strokeDashoffset: '0' } },
      },
      animation: {
        'fade-up': 'fade-up 0.34s cubic-bezier(0.22, 1, 0.36, 1) both',
        'fade-in': 'fade-in 0.25s ease-out both',
        shimmer: 'shimmer 1.6s infinite',
        'pulse-ring': 'pulse-ring 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        segment: 'segment 0.9s cubic-bezier(0.22, 1, 0.36, 1) both',
      },
    },
  },
  plugins: [],
}
