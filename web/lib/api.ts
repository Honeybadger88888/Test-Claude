import { DashboardSnapshot, DepthHistoryRow, TradeEvent } from "@/types/dashboard";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export function getApiBase() {
  return API_BASE;
}

export async function fetchSnapshot(): Promise<DashboardSnapshot> {
  const response = await fetch(`${API_BASE}/api/snapshot`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Snapshot fetch failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchDepthHistory(limit = 120): Promise<DepthHistoryRow[]> {
  const response = await fetch(`${API_BASE}/api/history/depth?limit=${limit}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Depth history fetch failed: ${response.status}`);
  }
  const payload = await response.json();
  return payload.rows ?? [];
}

export async function fetchTradeHistory(limit = 120): Promise<TradeEvent[]> {
  const response = await fetch(`${API_BASE}/api/history/trades?limit=${limit}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Trade history fetch failed: ${response.status}`);
  }
  const payload = await response.json();
  return payload.rows ?? [];
}
