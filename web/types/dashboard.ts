export type DepthKey = "2" | "5" | "10";

export interface DepthRow {
  depth_pct: number;
  depth_key: DepthKey;
  obi: number;
  obd?: number;
  prediction: "Up" | "Down" | null;
  accuracy: number;
  sample_size: number;
  threshold_suggestion?: number;
  threshold_accuracy?: number;
  threshold_sample_size?: number;
}

export interface DepthHistoryRow {
  timestamp: string;
  window_ts?: number;
  obi: Record<DepthKey, number>;
  obd?: Record<DepthKey, number>;
  predictions: Record<DepthKey, "Up" | "Down" | null>;
  actual: string;
  volatility?: number;
  drift?: number;
  market_p?: number;
  baseline_p?: number;
}

export interface TradeEvent {
  status: string;
  trade_id: number;
  timestamp: string;
  direction: string;
  size: number;
  market_p: number;
  my_p: number;
  edge: number;
  result?: string;
  pnl?: number;
  bankroll_after?: number;
}

export interface DashboardSnapshot {
  timestamp: string;
  status?: {
    running: boolean;
    feed_connected: boolean;
    last_error?: string | null;
    last_update_ts?: string | null;
  };
  engine: {
    state: string;
    auto_trade: boolean;
    feed_connected: boolean;
    pending_trade: boolean;
  };
  window: {
    window_ts?: number;
    window_slug?: string;
    seconds_left?: number;
    open_price?: number | null;
    current_price?: number | null;
  };
  market: {
    slug?: string | null;
    question?: string | null;
    up_price?: number | null;
    down_price?: number | null;
  };
  price_feed: {
    price?: number | null;
    spread?: number;
    mid_price?: number;
    top_bids?: number[][];
    top_asks?: number[][];
    candles_count?: number;
  };
  depth: {
    rows: DepthRow[];
    best_depth?: number | null;
    best_threshold?: number | null;
    best_method?: string;
    best_reason?: string;
  };
  model: {
    volatility?: number;
    drift?: number;
    best_obi?: number;
    baseline_probability_up?: number;
  };
  ml: {
    mode: string;
    ready: boolean;
    probability_up?: number | null;
    blended_probability_up?: number;
    trade_control_mode?: string;
    decision_source?: string;
    consensus?: {
      agreed?: boolean;
      baseline_direction?: string;
      ml_direction?: string;
    };
    details?: {
      reason?: string;
      feature_names?: string[];
      training?: {
        status?: string;
        rows?: number;
        calibration_method?: string;
        cv?: string;
        n_splits?: number;
        performance?: {
          folds?: number;
          log_loss_mean?: number;
          brier_mean?: number;
          accuracy_mean?: number;
        };
        feature_importance?: {
          sample_count?: number;
          top_features?: Array<{ name: string; score: number }>;
        };
      };
    };
  };
  signal: {
    direction: string;
    should_trade: boolean;
    edge: number;
    position_size: number;
  };
  risk: {
    can_trade: boolean;
    reason: string;
    bankroll: number;
  };
  stats: {
    total_trades?: number;
    wins?: number;
    losses?: number;
    win_rate?: number;
    total_pnl?: number;
    bankroll?: number;
  };
  trades: {
    recent: TradeEvent[];
  };
}
