# CT-MIF Production System

> Productionized **CT-MIF** (multi-view Isolation-Forest anomaly detection) for the
> SWaT industrial water-treatment testbed, wrapped in a **4-agent LangGraph reasoning
> pipeline** (classify → assess → mitigate), a **FastAPI WebSocket sensor stream**, a
> **Supabase** event store with Realtime broadcasting, a controllable **Replay Engine**,
> and a **Next.js** dashboard. Dockerized, CI/CD via GitHub Actions, deployable to
> Render (backend) + Vercel (frontend).

---

## Architecture

```mermaid
flowchart LR
  subgraph B["Browser — Vercel"]
    UI["Next.js dashboard<br/>(chart · feed · agent panel)"]
  end
  subgraph API["FastAPI — Render"]
    WS["/ws/sensor-stream/"]
    REST["REST: /analyze · /anomalies · /replay/*"]
    RE["Replay Engine"]
    SC["CT-MIF online scorer"]
    AG["LangGraph 4-agent pipeline"]
  end
  SB[("Supabase<br/>Postgres + Realtime")]
  GROQ["Groq LLM"]

  UI -- WebSocket --> WS
  UI -- Realtime subscribe --> SB
  UI -- REST --> REST
  WS --> RE --> SC --> AG
  AG -- reasoning --> GROQ
  AG -- write anomaly_events --> SB
```

**Agent pipeline** (downstream agents run only on a confirmed anomaly):

```mermaid
flowchart LR
  D["① AnomalyDetector<br/>CT-MIF score + view attribution"] -->|anomaly| C["② AttackClassifier<br/>DoS / FDI / Replay / Stealth"]
  D -->|normal| E([END])
  C --> A["③ ImpactAssessor<br/>severity + blast radius"]
  A --> M["④ MitigationAdvisor<br/>prioritized actions"]
  M --> E
```

---

## Stack

| Layer | Tech |
|---|---|
| Core ML | CT-MIF — 3-view Isolation Forest + score fusion (`pp.py`, `train.py`, `test.py`) |
| Online inference | `core/ctmif.py` — causal, one-reading-at-a-time scorer (verified bit-exact vs offline) |
| Agents | LangGraph, 4 agents on **Groq** (`langchain-groq`), heuristic fallback |
| Backend | FastAPI (REST + WebSocket) |
| Database | Supabase (PostgreSQL + Realtime) |
| Frontend | Next.js (App Router) + Recharts + `@supabase/supabase-js` |
| DevOps | Docker, docker-compose, GitHub Actions, Render, Vercel |

---

## Repository layout

```
core/ctmif.py          Online CT-MIF scorer (rolling buffers; reproduces training pipeline causally)
pp.py train.py test.py  Existing CT-MIF training/eval (preprocess → 3-view IF → fuse → threshold)
agents/                4 agents + LangGraph graph + SWaT domain knowledge
api/                   FastAPI app, routes (analyze / anomalies / stream), Supabase client
replay/engine.py       Seekable "live" stream: play/pause/speed/jump + debounced events
frontend/              Next.js dashboard (2 pages: live dashboard + anomaly history)
tests/                 pytest: scorer, API, agents, replay (16 tests)
scripts/               extract_sample · build_replay_data · diag_detector · live_test
db/supabase_setup.sql  Schema + Realtime + RLS read policy
Dockerfile docker-compose.yml render.yaml   Deployment
.github/workflows/     ci.yml (pytest + next build) · docker.yml (GHCR on tag)
```

---

## Quickstart

### 1. Backend

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows; use bin/activate on *nix
pip install -r requirements.txt
cp .env.example .env        # fill SUPABASE_*, GROQ_API_KEY
```

Trained models live in `artifacts/*.pkl` (committed). To regenerate from the raw dataset:

```bash
python pp.py data/swat_combined.csv     # preprocess (writes artifacts/, incl. scaler/freq)
python train.py                         # train 3 Isolation Forests + thresholds
python scripts/build_replay_data.py     # optional: full 35-attack replay file
```

> **Windows note:** prefix scripts with `PYTHONIOENCODING=utf-8` — the console's cp1252
> codec chokes on the Unicode in some print statements.

Run the API:

```bash
uvicorn api.main:app --reload        # http://localhost:8000/docs
```

### 2. Supabase

In the Supabase SQL editor, run [`db/supabase_setup.sql`](db/supabase_setup.sql). It creates
the tables, enables Realtime on `anomaly_events`, and adds the **anon read policy** the
browser needs (without it, RLS makes anon reads return `[]` and Realtime stays silent).

### 3. Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local     # API URLs + Supabase anon key (browser-safe)
npm run dev                          # http://localhost:3000
```

### Everything at once (Docker)

```bash
docker compose up --build            # api :8000 + frontend :3000
```

---

## The CT-MIF detector

`train.py` builds three Isolation-Forest "views" — raw+temporal sensor features (View A),
PCA + actuator-state surprise (View B), and step-over-step change (View C) — then fuses,
smooths, and thresholds their normalized scores.

`core/ctmif.py` reproduces that pipeline **causally**, one reading at a time, using rolling
buffers for the 60-row rolling-std, the step-difference, and the smoothing window. It is
**verified bit-exact** against the offline batch (max diff `5e-7`, 100 % prediction
agreement over 3 000 rows). Live point-wise performance: **P ≈ 0.68, R ≈ 0.64**, 25/35
attack segments detected — solid for a real-time detector. (The paper's headline F1 relies
on non-causal point-adjustment, which a live system can't use, so it's intentionally
omitted here.)

False positives near attack onset / on a cold start are handled in the **replay layer**
(silent warm-up after a jump + confirm-after-3 / clear-after-20 debounce), keeping the
verified detector untouched.

---

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/analyze` | Score a reading → run agents → persist → return `agent_report` |
| GET | `/anomalies?severity=&limit=&offset=` | Paginated anomaly events |
| GET | `/anomalies/{id}` | Full 4-agent report for one event |
| WS | `/ws/sensor-stream` | Live readings + events; accepts `{cmd: play\|pause\|speed\|jump\|seek\|restart}` |
| POST | `/replay/start` `/replay/jump` `/replay/pause` `/replay/speed` | Replay control |
| GET | `/health` | Model / Supabase / Groq status |

---

## Testing

```bash
pytest tests/ -v        # 16 tests: scorer, API, agents (heuristic), replay + WebSocket
```

Tests run without any secrets (agents fall back to heuristics, DB writes skip). With
`GROQ_API_KEY` / `SUPABASE_*` set they exercise the live paths.

---

## Deployment

- **Backend → Render:** the [`render.yaml`](render.yaml) blueprint deploys the Dockerized
  API. Set `SUPABASE_URL`, `SUPABASE_KEY`, `GROQ_API_KEY`, and `CORS_ORIGINS`
  (= your Vercel URL) in the dashboard. Render injects `$PORT`.
- **Frontend → Vercel:** import the repo, set **Root Directory = `frontend`**, and add
  `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_API_WS_URL` (your Render `wss://…/ws/sensor-stream`),
  `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
- **Image → GHCR:** pushing a `v*` tag builds and publishes the backend image
  (`.github/workflows/docker.yml`).

---

## Security

Never commit real secrets. The backend reads `.env` (gitignored); the `SUPABASE_KEY`
(service-role) bypasses RLS and must stay server-side. Only the **anon** key belongs in the
frontend. If a service-role/Groq key is ever exposed, rotate it in the provider dashboard.

---

## Résumé bullet

> Productionized a published CT-MIF anomaly-detection framework with a 4-agent LangGraph
> reasoning pipeline (attack classification → impact assessment → mitigation) on Groq, a
> FastAPI WebSocket sensor stream, a Supabase PostgreSQL event store with Realtime
> broadcasting, a Replay Engine for controlled attack-scenario demos, a Next.js dashboard,
> GitHub Actions CI/CD, and Dockerized deployment to Render + Vercel.
