# Paper Trading Edge Bot + Mobile Live Dashboard

This repository now runs as a **live auto paper-trading system** with:

- Python trading engine (signal + risk + execution)
- FastAPI backend (snapshot/history/SSE APIs)
- Next.js mobile-first frontend dashboard
- Side-by-side depth analysis (2%, 5%, 10%)
- Historical OBI/OBD data across depth levels
- ML integration scaffold (gradient-boosted classifier in shadow/active modes)

---

## 1) Install dependencies

### Python

```bash
python3 -m pip install -r requirements.txt
```

### Frontend

```bash
cd web
npm install
```

---

## 2) Run the backend (auto-trading engine + APIs)

```bash
python3 -m uvicorn api_server:app --host 0.0.0.0 --port 8000
```

APIs:

- `GET /api/health`
- `GET /api/snapshot`
- `GET /api/history/depth?limit=200`
- `GET /api/history/trades?limit=200`
- `GET /api/stream` (SSE)

> Note: if Binance WebSocket is blocked by region (HTTP 451), the feed auto-falls back to Coinbase REST for live price/book updates.

---

## 3) Run the Next.js mobile UI

In another terminal:

```bash
cd web
npm run dev
```

Open:

- `http://localhost:3000`

Optional API base override:

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

---

## 4) CLI-only engine mode (no UI)

```bash
python3 main.py
```

---

## 5) Testing

Run backend/unit tests:

```bash
python3 -m pytest -q
```

Build frontend:

```bash
cd web
npm run build
```

---

## Data shown in the UI

- Engine status / connectivity / pending trade state
- Live price feed + top-of-book snapshots
- Polymarket window + implied probabilities
- Baseline model probability, ML probability, blended probability
- Walk-forward ML quality metrics (accuracy, Brier, calibration context)
- ML feature-importance snapshot
- Signal direction, edge, position size, and risk gate status
- Auto trade events (OPEN + RESOLVED)
- Side-by-side depth rows (2/5/10%)
- Historical OBI trend chart (2/5/10)
- Historical OBI/OBD rows by depth with outcomes

## Optional ML trade-control mode

Set `ML_TRADE_CONTROL_MODE` in `config.py`:

- `baseline` → existing analytical model only
- `blended` → weighted baseline+ML probability (default)
- `ml_only` → ML probability only
- `consensus` → only trades when baseline and ML agree on direction
