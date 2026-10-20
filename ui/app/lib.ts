export const API = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000/api";

export const inr = (n: number | null | undefined, digits = 2) =>
  n == null || Number.isNaN(n) ? "–" : new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: digits, minimumFractionDigits: digits }).format(n);

export const pct = (n: number | null | undefined, digits = 2) => (n == null ? "–" : `${n >= 0 ? "+" : ""}${n.toFixed(digits)}%`);

export async function api(path: string, init?: RequestInit): Promise<any> {
  let r: Response;
  try {
    r = await fetch(`${API}${path}`, { ...init, headers: { "Content-Type": "application/json" } });
  } catch {
    throw new Error("Cannot reach the backend at " + API + ". Start it with: uvicorn api.main:app");
  }
  let body: any = null;
  try { body = await r.json(); } catch { /* non-JSON error page */ }
  if (!r.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (HTTP ${r.status})`);
  return body;
}

export const post = (path: string, data?: unknown) => api(path, { method: "POST", body: JSON.stringify(data ?? {}) });

/** "TCS 40, ITC 30" or "TCS:40\nITC:30" -> {TCS: 40, ITC: 30} */
export function parseWeights(text: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const part of text.split(/[\n,;]+/)) {
    const m = part.trim().match(/^([A-Za-z0-9&\-]+)\s*[: ]\s*([\d.]+)$/);
    if (m) out[m[1].toUpperCase()] = parseFloat(m[2]);
  }
  return out;
}

/** Minutes between an ISO timestamp and now (null if unknown). */
export function ageMinutes(iso?: string | null): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : Math.max(0, Math.round((Date.now() - t) / 60000));
}

export function ageText(iso?: string | null): string {
  const m = ageMinutes(iso);
  if (m == null) return "age unknown";
  if (m < 2) return "just now";
  if (m < 120) return `${m} min old`;
  if (m < 60 * 48) return `${Math.round(m / 60)} hours old`;
  return `${Math.round(m / 1440)} days old`;
}

/** Plain-English explanations shown behind "What does this mean?" links. */
export const WORDS: Record<string, string> = {
  paper: "PAPER mode means practice money. Orders are simulated here: nothing is sent to a broker and no real rupee moves. Prices are real (but delayed), so it shows how a real day would have gone.",
  live: "LIVE mode would send orders to a real broker with real money. It is switched off unless you deliberately turn it on in several places.",
  market_open: "The NSE equity market has three parts of the day: pre-open 9:00–9:15 (opening price is discovered, no normal trading), normal trading 9:15–15:30, and a short closing session. Outside 9:15–15:30, on weekends and on exchange holidays, normal orders do not trade.",
  riskgate: "The risk gate is a set of limits YOU configured (maximum size per stock, cash you must keep, daily order count…). Every order is checked before it can be queued, and checked again at the moment you approve it. A blocked order can never be approved.",
  approval: "Nothing is bought or sold until you approve that exact order. Approving re-runs the risk gate with fresh numbers, so an order that was fine a minute ago can still be refused.",
  whole: "Indian shares are bought in whole numbers (no 0.3 of a share), so the money rarely divides exactly. Leftover rupees stay in cash.",
  delivery: "Delivery (CNC) means you buy the shares and keep them in your demat account for as long as you like. This tool only handles delivery. Intraday and futures & options are not supported.",
  market_order: "A MARKET order buys or sells at whatever the best available price is when it reaches the exchange. A LIMIT order only trades at your price or better, and may never trade.",
  charges: "Every trade costs money beyond the share price. The estimate adds: STT (a government tax on the trade value), exchange and SEBI fees, stamp duty (on buys), the depository fee when you sell, and GST on the fees. Your broker's brokerage is set to ₹0 here: change config/charges.json to match yours. These rates are estimates, not verified.",
  stcg: "Short-term capital gain (STCG): profit on shares sold within 12 months of buying. Long-term (LTCG): sold after more than 12 months, with a yearly exemption before tax applies. The rates in this app are unverified estimates: confirm with a chartered accountant.",
  roce: "ROCE (return on capital employed) is yearly operating profit divided by the money tied up in the business. Higher usually means a more efficient business. It is not meaningful for banks.",
  de: "Debt-to-equity compares what a company owes with what its owners put in. Below 1 means less debt than equity. Banks are naturally high because deposits are debt.",
  promoter: "Promoters are the founding owners. Their % holding comes from the quarterly shareholding pattern filed with SEBI. 0% means the company has no identified promoter group (ITC and HDFC Bank, for example), not that the data is missing.",
  bulk: "A bulk deal is a trade of more than 0.5% of a company's shares; a block deal is a large negotiated trade. They show WHO traded, not WHY. A matching buy and sell of the same size is usually shuffling between funds, not a signal.",
  fiidii: "FII/FPI are foreign investors, DII are domestic institutions (mutual funds, insurers). The table shows what they bought and sold in the cash market on the latest session, in ₹ crore.",
  screener: "A screener filters stocks by rules you can read, like 'ROCE at least 15'. It shows the number behind each pass and fail. It is a filter on reported numbers, not a recommendation.",
  stale: "'Stale' means the newest results available to the tool are older than what the company has already announced. Stale stocks fail the screen on purpose, because a screen on old numbers is misleading.",
  rebalance: "Rebalancing trades back toward your target weights, but only for stocks that drifted more than the band you set, and not when the trade is too small to be worth the fees. Selling creates tax: check the Portfolio page first.",
  rehearsal: "The rehearsal plays a whole trading session with dummy money: it reads the real market state and prices, runs the screen, sizes and queues orders through the risk gate, then plays YOU saying yes to each so the whole chain is exercised. It uses a separate throw-away database, so your own practice account is untouched.",
};

export const STATUS_WORDS: Record<string, string> = {
  PENDING: "Waiting for your decision. Nothing has been bought or sold.",
  BLOCKED: "Stopped by the risk gate. It can never be approved; change the order or your limits (deliberately) and try again.",
  FILLED: "Done: the paper order was executed at the price shown.",
  REJECTED: "Not executed: you declined it, it was invalid, or there was not enough cash or shares at approval time.",
  SENT: "Sent to the real broker and waiting for the exchange.",
};
