# CODE 2026 — Submission fields (copy/paste)

Everything below maps 1:1 to the submission form.

---

## Title

```
SignalWatch — Know What Changed
```

---

## Description

```
SignalWatch is a smart market watchlist that answers the question you actually
arrive with: "what changed while I was away, and what deserves my attention now?"

An ordinary watchlist shows you a wall of tickers and coloured percentages, and
leaves you to scan every row. SignalWatch instead tracks what YOU have already
acknowledged — price, volume, attention score, technical regime, the exact set
of live signals, news state — and when you return it diffs the live market
against that personal baseline and shows only what meaningfully changed. Loading
the page does not consume the deltas; only pressing "Mark all as reviewed" moves
your baseline forward. Two people with identical watchlists see different
priorities, because they last reviewed at different times.

THREE IDEAS, EXECUTED CAREFULLY

1. Since you last checked — a per-user baseline, diffed on every return.
   "NVDA: +6.46% since your last review · attention 18 → 78 · 7 new signals."

2. Why this matters — a written interpretation, not a list of indicators.
   Price AND volume is confirmation; price WITHOUT volume is suspect; volume
   WITHOUT price is a coiled spring. The engine says which it is seeing.

3. Attention Score (0–100) — NOT an opaque AI score. It is the literal
   arithmetic sum of six bounded components (price move, volume anomaly,
   technical regime, news, volatility, change-since-your-visit), each with a
   configurable maximum, each reporting its own inputs and a plain-English
   sentence. If the UI shows 78, the backend tells you exactly which points
   came from where, and the numbers add up by hand.

ENGINEERING MATURITY (the brief asks for this explicitly)

- Provider abstraction: one MarketDataProvider interface, demo ⇄ Finnhub swap
  changes nothing above the registry. Missing API key → a visible, labelled
  fallback, never a crash.
- Data freshness: every value carries source + timestamp + a FRESH / RECENT /
  STALE / UNAVAILABLE band. Stale data is shown as stale, never as real-time.
- Conflicting data: a second source is cross-checked; when two sources disagree
  beyond tolerance, BOTH values are stored and shown, with which one is used
  and why — never silently merged.
- Scalability: one API call renders the whole homepage; batch quote fetches;
  a cache with stale-read fallback (in-process default, Redis-swappable);
  cached indicators; throttled, fingerprint-deduplicated event writes;
  composite DB indexes on the hot queries.

REPLAY (for the demo)
A one-click "Replay market changes" control steps a server-side clock. The
provider then returns different data, the signal engine RE-DETECTS from scratch,
and the score genuinely re-rates — NVDA climbs from ~15 (Stable) to ~78
(High Attention) across five frames. It is real recomputation, not an animation.

STACK
Frontend: React + TypeScript + Vite + Tailwind + Recharts.
Backend:  FastAPI + SQLAlchemy 2.0 + Pydantic v2. SQLite by default (zero setup),
          PostgreSQL by changing one env var. 84 passing tests, with the signal
          engine written as a pure function so scoring is asserted exactly.

SignalWatch surfaces market changes for informational purposes. It does not
provide investment advice — it shows HIGH ATTENTION / WATCH / STABLE, never
buy or sell.
```

---

## Theme

Pick the option closest to **Smart Market Watchlist / Fintech / Data & Analytics**
(whichever the dropdown offers for this track).

---

## Snapshots — upload these 7 (all < 3 MB, in `screenshots/`)

| File | Shows |
|---|---|
| `screenshots/1-dashboard.png` | The homepage: "Since your last visit" cards with deltas, why-it-matters, new-signal chips |
| `screenshots/2-attention-queue.png` | The Attention Queue — every stock ranked, banded High/Watch/Stable, top reason + freshness |
| `screenshots/3-stock-detail.png` | NVDA detail: score ring, since-you-last-checked stats, why-it-matters narrative |
| `screenshots/4-score-breakdown.png` | The explainable score — six components, each with its points and reason |
| `screenshots/5-timeline-news.png` | Signal timeline (sequenced, categorised) + topic-clustered news with sentiment |
| `screenshots/6-watchlists.png` | Multi-watchlist management, drag-and-drop reorder |
| `screenshots/7-signals.png` | The scoring policy itself — live weights and thresholds, published |

---

## Video URL

Record a 60–90s screen capture (Loom / OBS / built-in recorder), upload to
YouTube/Loom (unlisted is fine), paste the link. Suggested script:

1. (0:00) Overview page — "8 meaningful changes since I last checked. NVDA needs
   the most attention." Point at the NVDA card: +6.46%, attention 18 → 78.
2. (0:15) Sidebar → Replay → **Reset**. NVDA drops to ~15, Stable. "This is the
   quiet market — I've now 'seen' it."
3. (0:22) Click **Replay**. Narrate as it steps: volume builds → price
   accelerates → news arrives → score re-rates. NVDA → 78, High Attention.
4. (0:45) Click NVDA. Open **"Why is this score 78?"** — walk the six components,
   "the number adds up by hand." Show the timeline and clustered news.
5. (1:00) Back to Overview → **Mark reviewed** on NVDA → it leaves "Since your
   last visit"; the others stay. "That's the core loop."
6. (1:10) Point at the Data quality panel — META's two sources disagree 2.9%,
   both values kept; NFLX flagged 22-min delayed. "It never hides bad data."

---

## Demo Link

This runs locally (no public deploy). Either:
- Put your repo URL here again and rely on **Instructions to Run** below, or
- Deploy in ~15 min: frontend → Vercel/Netlify (`frontend/`, build `npm run build`,
  output `dist`), backend → Render/Railway (`backend/`, start
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`), set the frontend's
  `VITE_API_BASE_URL` to the backend URL. `DEMO_MODE=true` needs no keys.

---

## Repository URL

Create an empty repo on GitHub, then from `c:\Users\user\OneDrive\Desktop\Groww`:

```
git branch -M main
git remote add origin https://github.com/<you>/signalwatch.git
git push -u origin main
```

(The repo is already initialised and committed locally.)

---

## Source Code — upload this file

```
c:\Users\user\OneDrive\Desktop\SignalWatch-source.zip
```

1.4 MB, 92 files, no `node_modules` / `.venv` / database — a clean checkout.

---

## Instructions to Run

```
Prerequisites: Python 3.11+, Node 18+. No database server needed (SQLite).

BACKEND
  cd backend
  python -m venv .venv
  .venv\Scripts\activate          (Windows)  |  source .venv/bin/activate  (macOS/Linux)
  pip install -r requirements.txt
  copy .env.example .env          (all defaults work; DEMO_MODE=true, no API key)
  python seed.py --reset          (builds the demo world + a review baseline)
  uvicorn app.main:app --port 8000

FRONTEND  (second terminal)
  cd frontend
  npm install
  npm run dev

Open http://localhost:5173
API docs: http://localhost:8000/docs

30-SECOND DEMO
  1. Overview page → right sidebar → "Replay market changes" → Reset
  2. Click Replay — watch NVDA go from ~15 (Stable) to ~78 (High Attention)
  3. Click NVDA → expand "Why is this score 78?" to see the six components
  4. Back on Overview → "Mark reviewed" on NVDA → it leaves "Since your last visit"

Tests:  cd backend && pytest -q      (84 passing)
```
