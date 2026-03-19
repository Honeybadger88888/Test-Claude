"use client";

import React, { useEffect, useMemo, useState } from "react";

import { fetchDepthHistory, fetchSnapshot, fetchTradeHistory, getApiBase } from "@/lib/api";
import { openSnapshotStream } from "@/lib/sse";
import { DashboardSnapshot, DepthHistoryRow, TradeEvent } from "@/types/dashboard";

function fmtNumber(value?: number | null, digits = 3): string {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "—";
  }
  return value.toFixed(digits);
}

function fmtCurrency(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "—";
  }
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function fmtPercent(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "—";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function buildPolyline(values: number[], width = 720, height = 180): string {
  if (values.length === 0) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(0.000001, max - min);
  return values
    .map((value, idx) => {
      const x = (idx / Math.max(values.length - 1, 1)) * width;
      const y = height - ((value - min) / span) * height;
      return `${x},${y}`;
    })
    .join(" ");
}

export function Dashboard() {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [depthHistory, setDepthHistory] = useState<DepthHistoryRow[]>([]);
  const [tradeHistory, setTradeHistory] = useState<TradeEvent[]>([]);
  const [streamMessage, setStreamMessage] = useState<string>("Connecting...");
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const apiBase = getApiBase();

    async function hydrate() {
      try {
        const [snap, depthRows, tradeRows] = await Promise.all([
          fetchSnapshot(),
          fetchDepthHistory(240),
          fetchTradeHistory(120),
        ]);
        if (cancelled) return;
        setSnapshot(snap);
        setDepthHistory(depthRows);
        setTradeHistory(tradeRows);
        setStreamMessage("Live");
      } catch (error) {
        if (!cancelled) {
          setLoadError(String(error));
        }
      }
    }

    hydrate();
    const stream = openSnapshotStream(apiBase, {
      onSnapshot: (snap) => {
        if (cancelled) return;
        setSnapshot(snap);
        setStreamMessage("Live");
      },
      onError: (message) => {
        if (!cancelled) {
          setStreamMessage(message);
        }
      },
    });

    const historyRefresh = setInterval(async () => {
      try {
        const [depthRows, tradeRows] = await Promise.all([
          fetchDepthHistory(240),
          fetchTradeHistory(120),
        ]);
        if (cancelled) return;
        setDepthHistory(depthRows);
        setTradeHistory(tradeRows);
      } catch {
        // Best-effort refresh for historical sections.
      }
    }, 15000);

    return () => {
      cancelled = true;
      stream.close();
      clearInterval(historyRefresh);
    };
  }, []);

  const depthRows = snapshot?.depth?.rows ?? [];
  const bestDepth = snapshot?.depth?.best_depth;
  const bestMethod = snapshot?.depth?.best_method;
  const bestReason = snapshot?.depth?.best_reason;
  const mlTraining = snapshot?.ml?.details?.training;
  const mlPerf = mlTraining?.performance;
  const mlTopFeatures = mlTraining?.feature_importance?.top_features ?? [];
  const pendingTrades = useMemo(
    () => tradeHistory.filter((event) => event.status === "OPEN").length,
    [tradeHistory]
  );
  const chartRows = useMemo(() => depthHistory.slice(-60), [depthHistory]);
  const poly2 = useMemo(() => buildPolyline(chartRows.map((r) => r.obi?.["2"] ?? 0)), [chartRows]);
  const poly5 = useMemo(() => buildPolyline(chartRows.map((r) => r.obi?.["5"] ?? 0)), [chartRows]);
  const poly10 = useMemo(() => buildPolyline(chartRows.map((r) => r.obi?.["10"] ?? 0)), [chartRows]);

  return (
    <main className="container">
      <header className="header">
        <h1>Live Auto Paper Trading Dashboard</h1>
        <p className="subtitle">
          Mobile-friendly Next.js UI · Exact signal execution · OBI/OBD history across 2% / 5% / 10%
        </p>
      </header>

      <section className="status-grid">
        <div className="card">
          <h2>Engine</h2>
          <div className="stat-line">
            <span>State</span>
            <strong>{snapshot?.engine?.state ?? "initializing"}</strong>
          </div>
          <div className="stat-line">
            <span>Auto Trading</span>
            <strong>{snapshot?.engine?.auto_trade ? "ON" : "OFF"}</strong>
          </div>
          <div className="stat-line">
            <span>Feed</span>
            <strong>{snapshot?.engine?.feed_connected ? "Connected" : "Disconnected"}</strong>
          </div>
          <div className="stat-line">
            <span>Pending Trades</span>
            <strong>{pendingTrades}</strong>
          </div>
        </div>

        <div className="card">
          <h2>Window</h2>
          <div className="stat-line">
            <span>Slug</span>
            <strong className="mono">{snapshot?.window?.window_slug ?? "—"}</strong>
          </div>
          <div className="stat-line">
            <span>Time Left</span>
            <strong>{snapshot?.window?.seconds_left ?? "—"}s</strong>
          </div>
          <div className="stat-line">
            <span>Open Price</span>
            <strong>{fmtCurrency(snapshot?.window?.open_price)}</strong>
          </div>
          <div className="stat-line">
            <span>Current Price</span>
            <strong>{fmtCurrency(snapshot?.window?.current_price)}</strong>
          </div>
        </div>

        <div className="card">
          <h2>Signal (Executes Live)</h2>
          <div className="stat-line">
            <span>Direction</span>
            <strong>{snapshot?.signal?.direction ?? "None"}</strong>
          </div>
          <div className="stat-line">
            <span>Should Trade</span>
            <strong>{snapshot?.signal?.should_trade ? "YES" : "NO"}</strong>
          </div>
          <div className="stat-line">
            <span>Edge</span>
            <strong>{fmtNumber(snapshot?.signal?.edge)}</strong>
          </div>
          <div className="stat-line">
            <span>Size</span>
            <strong>{fmtCurrency(snapshot?.signal?.position_size)}</strong>
          </div>
        </div>
      </section>

      <section className="status-grid">
        <div className="card">
          <h2>Model + ML</h2>
          <div className="stat-line">
            <span>Baseline P(Up)</span>
            <strong>{fmtPercent(snapshot?.model?.baseline_probability_up)}</strong>
          </div>
          <div className="stat-line">
            <span>ML Mode</span>
            <strong>{snapshot?.ml?.mode ?? "shadow"}</strong>
          </div>
          <div className="stat-line">
            <span>Trade Control</span>
            <strong>{snapshot?.ml?.trade_control_mode ?? "blended"}</strong>
          </div>
          <div className="stat-line">
            <span>Decision Source</span>
            <strong>{snapshot?.ml?.decision_source ?? "baseline"}</strong>
          </div>
          <div className="stat-line">
            <span>ML P(Up)</span>
            <strong>{fmtPercent(snapshot?.ml?.probability_up ?? undefined)}</strong>
          </div>
          <div className="stat-line">
            <span>Final P(Up)</span>
            <strong>{fmtPercent(snapshot?.ml?.blended_probability_up)}</strong>
          </div>
          <div className="stat-line">
            <span>Volatility</span>
            <strong>{fmtNumber(snapshot?.model?.volatility, 4)}</strong>
          </div>
          <div className="stat-line">
            <span>ML Train Rows</span>
            <strong>{mlTraining?.rows ?? "warming"}</strong>
          </div>
          <div className="stat-line">
            <span>ML Accuracy (WF)</span>
            <strong>{fmtPercent(mlPerf?.accuracy_mean)}</strong>
          </div>
          <div className="stat-line">
            <span>ML Brier (WF)</span>
            <strong>{fmtNumber(mlPerf?.brier_mean, 4)}</strong>
          </div>
        </div>

        <div className="card">
          <h2>Market</h2>
          <div className="stat-line">
            <span>Polymarket Up</span>
            <strong>{fmtPercent(snapshot?.market?.up_price)}</strong>
          </div>
          <div className="stat-line">
            <span>Polymarket Down</span>
            <strong>{fmtPercent(snapshot?.market?.down_price)}</strong>
          </div>
          <div className="stat-line">
            <span>Best Depth</span>
            <strong>{bestDepth ? `${Math.round(bestDepth * 100)}%` : "warming"}</strong>
          </div>
          <div className="stat-line">
            <span>Selection Mode</span>
            <strong>{bestMethod ?? "warming"}</strong>
          </div>
          <div className="stat-line">
            <span>Best Reason</span>
            <strong>{bestReason ?? "collecting samples"}</strong>
          </div>
          <div className="stat-line">
            <span>Bankroll</span>
            <strong>{fmtCurrency(snapshot?.risk?.bankroll)}</strong>
          </div>
          <div className="stat-line">
            <span>Risk State</span>
            <strong>{snapshot?.risk?.can_trade ? "Can Trade" : snapshot?.risk?.reason}</strong>
          </div>
        </div>

        <div className="card">
          <h2>Live Status</h2>
          <div className="stat-line">
            <span>Stream</span>
            <strong>{streamMessage}</strong>
          </div>
          <div className="stat-line">
            <span>Last Update</span>
            <strong className="mono">{snapshot?.timestamp ?? "—"}</strong>
          </div>
          <div className="stat-line">
            <span>Total Trades</span>
            <strong>{snapshot?.stats?.total_trades ?? 0}</strong>
          </div>
          <div className="stat-line">
            <span>Win Rate</span>
            <strong>{fmtPercent(snapshot?.stats?.win_rate)}</strong>
          </div>
          <div className="stat-line">
            <span>PnL</span>
            <strong>{fmtCurrency(snapshot?.stats?.total_pnl)}</strong>
          </div>
        </div>
      </section>

      <section className="card table-card">
        <h2>ML Feature Importance Snapshot</h2>
        <table>
          <thead>
            <tr>
              <th>Feature</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {mlTopFeatures.length === 0 ? (
              <tr>
                <td colSpan={2}>Not available yet (ML still warming / training).</td>
              </tr>
            ) : (
              mlTopFeatures.map((feature) => (
                <tr key={feature.name}>
                  <td>{feature.name}</td>
                  <td>{fmtNumber(feature.score, 6)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>

      <section className="card table-card">
        <h2>Depth Comparison (Side by Side)</h2>
        <table>
          <thead>
            <tr>
              <th>Depth</th>
              <th>OBI</th>
              <th>OBD</th>
              <th>Prediction</th>
              <th>Accuracy</th>
              <th>Samples</th>
              <th>Threshold</th>
              <th>Thr Acc</th>
            </tr>
          </thead>
          <tbody>
            {depthRows.map((row) => (
              <tr key={row.depth_key} className={bestDepth === row.depth_pct ? "best-row" : ""}>
                <td>{Math.round(row.depth_pct * 100)}%</td>
                <td>{fmtNumber(row.obi)}</td>
                <td>{fmtNumber(row.obd ?? row.obi)}</td>
                <td>{row.prediction ?? "None"}</td>
                <td>{fmtPercent(row.accuracy)}</td>
                <td>{row.sample_size}</td>
                <td>{fmtNumber(row.threshold_suggestion, 4)}</td>
                <td>{fmtPercent(row.threshold_accuracy)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2>Historical OBI Trend Chart (Last 60 Windows)</h2>
        <div className="chart-wrap">
          <svg
            viewBox="0 0 720 180"
            width="100%"
            height="220"
            role="img"
            aria-label="OBI trend lines for 2 5 and 10 percent depth"
          >
            <line x1="0" y1="90" x2="720" y2="90" className="chart-axis" />
            {poly2 ? <polyline points={poly2} className="chart-line chart-line-2" /> : null}
            {poly5 ? <polyline points={poly5} className="chart-line chart-line-5" /> : null}
            {poly10 ? <polyline points={poly10} className="chart-line chart-line-10" /> : null}
          </svg>
        </div>
        <div className="chart-legend">
          <span><i className="legend-swatch legend-2" />2% depth</span>
          <span><i className="legend-swatch legend-5" />5% depth</span>
          <span><i className="legend-swatch legend-10" />10% depth</span>
        </div>
      </section>

      <section className="card table-card">
        <h2>Historical OBI/OBD by Depth</h2>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>OBI 2%</th>
              <th>OBD 2%</th>
              <th>OBI 5%</th>
              <th>OBD 5%</th>
              <th>OBI 10%</th>
              <th>OBD 10%</th>
              <th>Actual</th>
            </tr>
          </thead>
          <tbody>
            {depthHistory.slice(-20).reverse().map((row, idx) => (
              <tr key={`${row.timestamp}-${idx}`}>
                <td className="mono">{row.timestamp}</td>
                <td>{fmtNumber(row.obi?.["2"])}</td>
                <td>{fmtNumber((row.obd ?? row.obi)?.["2"])}</td>
                <td>{fmtNumber(row.obi?.["5"])}</td>
                <td>{fmtNumber((row.obd ?? row.obi)?.["5"])}</td>
                <td>{fmtNumber(row.obi?.["10"])}</td>
                <td>{fmtNumber((row.obd ?? row.obi)?.["10"])}</td>
                <td>{row.actual || "pending"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card table-card">
        <h2>Recent Trade Events</h2>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Status</th>
              <th>Dir</th>
              <th>Size</th>
              <th>Edge</th>
              <th>PnL</th>
            </tr>
          </thead>
          <tbody>
            {tradeHistory.slice(-20).reverse().map((trade) => (
              <tr key={`${trade.trade_id}-${trade.status}-${trade.timestamp}`}>
                <td className="mono">{trade.timestamp}</td>
                <td>{trade.status}</td>
                <td>{trade.direction}</td>
                <td>{fmtCurrency(trade.size)}</td>
                <td>{fmtNumber(trade.edge)}</td>
                <td>{fmtCurrency(trade.pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {loadError ? <p className="error">Load error: {loadError}</p> : null}
    </main>
  );
}
