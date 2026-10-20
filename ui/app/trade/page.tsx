"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { STATUS_WORDS, ageText, api, inr, parseWeights, post } from "../lib";
import { CHARGE_WORDS, Card, Checks, Chip, Err, Hint, Note, Page, Tabs } from "../ui";

type Order = { id: number; symbol: string; side: string; qty: number; status: string; fill_price: number | null; reason: string; created_at: string };
const tone = (s: string) => (s === "FILLED" ? "ok" : s === "PENDING" ? "info" : s === "SENT" ? "info" : "bad") as "ok" | "info" | "bad";

export default function Trade() {
  const [form, setForm] = useState({ symbol: "ITC", side: "BUY", qty: 10, order_type: "MARKET", price: 0 });
  const [pv, setPv] = useState<any>(null);
  const [pvErr, setPvErr] = useState("");
  const [orders, setOrders] = useState<Order[]>([]);
  const [notice, setNotice] = useState<any>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("budget");
  const timer = useRef<any>(null);

  const loadOrders = useCallback(() => api("/orders").then(setOrders).catch((e) => setError(e.message)), []);
  useEffect(() => { loadOrders(); }, [loadOrders]);

  // live preview while typing (debounced); nothing is saved by a preview
  useEffect(() => {
    clearTimeout(timer.current);
    if (!form.symbol || !(form.qty > 0)) { setPv(null); return; }
    timer.current = setTimeout(() => {
      setPvErr("");
      post("/orders/preview", { ...form, price: form.order_type === "LIMIT" ? form.price : null })
        .then(setPv).catch((e) => { setPv(null); setPvErr(e.message); });
    }, 500);
    return () => clearTimeout(timer.current);
  }, [form]);

  const queue = async () => {
    setError(""); setNotice(null);
    try { setNotice(await post("/orders", { ...form, price: form.order_type === "LIMIT" ? form.price : null })); loadOrders(); }
    catch (e: any) { setError(e.message); }
  };
  const act = async (id: number, what: "approve" | "reject") => {
    setError("");
    try { await post(`/orders/${id}/${what}`); loadOrders(); } catch (e: any) { setError(e.message); }
  };

  const pending = orders.filter((o) => o.status === "PENDING");
  const sideWord = form.side === "BUY" ? "buy" : "sell";
  const verdict = pv?.risk?.verdict;

  return (
    <Page title="Trade" lead="Build an order, see everything that will happen to it before you commit, then approve it yourself. In practice mode nothing leaves this computer.">
      <Err msg={error} />
      <Card title="1. Build an order" lead="The preview updates as you type. It saves nothing and sends nothing.">
        <div className="row">
          <label>Stock (NSE symbol)<input value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value.toUpperCase() })} style={{ width: 130 }} aria-label="symbol" /></label>
          <label>Action<select value={form.side} onChange={(e) => setForm({ ...form, side: e.target.value })} aria-label="side"><option>BUY</option><option>SELL</option></select></label>
          <label>Number of shares<input type="number" min={1} value={form.qty} onChange={(e) => setForm({ ...form, qty: Math.floor(+e.target.value) })} style={{ width: 120 }} aria-label="quantity" /></label>
          <label>Order type<select value={form.order_type} onChange={(e) => setForm({ ...form, order_type: e.target.value })}><option value="MARKET">MARKET (best available price)</option><option value="LIMIT">LIMIT (my price or better)</option></select></label>
          {form.order_type === "LIMIT" && <label>Limit price (₹)<input type="number" step="0.05" value={form.price} onChange={(e) => setForm({ ...form, price: +e.target.value })} style={{ width: 120 }} /></label>}
        </div>
        <Hint k="market_order" /><Hint k="delivery" />
        <Err msg={pvErr} />

        {pv && (
          <>
            <h3>2. What would happen</h3>
            {pv.errors?.length > 0 && <Note tone="bad">This order is not valid: {pv.errors.join("; ")}</Note>}
            {pv.price != null && (
              <Note>
                You would <b>{sideWord} {form.qty} share{form.qty === 1 ? "" : "s"} of {form.symbol}</b> at about <b>{inr(pv.price)}</b> per share, a total of <b>{inr(pv.value)}</b>,
                plus roughly <b>{inr(pv.charges?.total)}</b> in charges.
                {pv.price_detail?.as_of
                  ? <> The price is from <b>{new Date(pv.price_detail.as_of).toLocaleString("en-IN")}</b> ({ageText(pv.price_detail.as_of)}){pv.price_detail.prev_close ? <>; previous close {inr(pv.price_detail.prev_close)}</> : null}.</>
                  : <> The price source did not say how old it is.</>}
              </Note>
            )}
            {pv.price == null && !pv.errors?.length && <Note tone="warn">No price found for {form.symbol}. Check the symbol (NSE trading symbol, e.g. M&amp;M, BAJAJ-AUTO).</Note>}

            {pv.charges && (
              <>
                <h3>Estimated charges</h3>
                <table>
                  <thead><tr><th>Item</th><th className="num">₹</th><th>What it is</th></tr></thead>
                  <tbody>{(["brokerage", "stt", "exchange_txn", "sebi", "stamp_duty", "dp", "gst"] as const).filter((k) => pv.charges[k] > 0 || k === "brokerage").map((k) => (
                    <tr key={k}><td>{k.replace("_", " ")}</td><td className="num">{pv.charges[k].toFixed(2)}</td><td className="muted">{CHARGE_WORDS[k]}</td></tr>
                  ))}<tr><td><b>Total</b></td><td className="num"><b>{pv.charges.total.toFixed(2)}</b></td><td className="muted">{((pv.charges.total / pv.value) * 100).toFixed(3)}% of the trade value</td></tr></tbody>
                </table>
                <Hint k="charges" />
              </>
            )}

            {pv.risk && (
              <>
                <h3>3. Risk gate: <Chip tone={verdict === "PASS" ? "ok" : "bad"}>{verdict === "PASS" ? "PASS" : "BLOCKED"}</Chip></h3>
                <p className="muted" style={{ marginTop: 0 }}>Every rule below was looked at, in order. ✓ passed, ✗ failed, – could not be checked yet.</p>
                <Checks checks={pv.risk.checks} />
                {pv.risk.warnings.map((w: string) => <Note key={w} tone="warn">{w}</Note>)}
                <Hint k="riskgate" />
              </>
            )}
            <div style={{ marginTop: 14 }}>
              <button onClick={queue} disabled={!pv.valid || verdict !== "PASS"}>Put in the approval queue</button>
              <span className="muted" style={{ marginLeft: 10 }}>{verdict === "BLOCK" ? "Blocked orders cannot be queued." : "This does NOT buy anything yet: you approve it below."}</span>
            </div>
          </>
        )}
        {notice && <Note tone={notice.order.status === "PENDING" ? "ok" : "bad"}>Order #{notice.order.id} is <b>{notice.order.status}</b>. {STATUS_WORDS[notice.order.status]} {notice.order.reason}</Note>}
      </Card>

      <Card title="4. Approval queue" lead="Orders wait here until you decide. Approving re-runs the risk gate with fresh numbers.">
        {pending.length === 0 && <p className="muted">No orders waiting.</p>}
        {pending.map((o) => (
          <div key={o.id} className="row" style={{ padding: "6px 0", borderBottom: "1px solid var(--line)" }}>
            <span><b>#{o.id}</b> {o.side} {o.qty} × {o.symbol}</span>
            <button onClick={() => act(o.id, "approve")}>Approve (practice)</button>
            <button className="danger" onClick={() => act(o.id, "reject")}>Reject</button>
          </div>
        ))}
        <Hint k="approval" />
      </Card>

      <Card title="Order history">
        <table>
          <thead><tr><th>#</th><th>Order</th><th>Status</th><th className="num">Fill price</th><th>What it means</th></tr></thead>
          <tbody>{orders.map((o) => (
            <tr key={o.id}><td>{o.id}</td><td>{o.side} {o.qty} × {o.symbol}</td><td><Chip tone={tone(o.status)}>{o.status}</Chip></td>
              <td className="num">{o.fill_price ? inr(o.fill_price) : "–"}</td><td className="muted">{STATUS_WORDS[o.status]} {o.reason}</td></tr>
          ))}</tbody>
        </table>
        {orders.length === 0 && <p className="muted">No orders yet.</p>}
      </Card>

      <Card title="Plan several trades at once">
        <Tabs tabs={[["budget", "Invest a budget"], ["rebalance", "Rebalance what I hold"]]} value={tab} onChange={setTab} />
        {tab === "budget" ? <Budget onQueued={loadOrders} /> : <Rebalance onQueued={loadOrders} />}
      </Card>
    </Page>
  );
}

function Budget({ onQueued }: { onQueued: () => void }) {
  const [weights, setWeights] = useState("TCS 40\nITC 30\nINFY 30");
  const [budget, setBudget] = useState(100000);
  const [maxPos, setMaxPos] = useState(35);
  const [size, setSize] = useState<any>(null);
  const [error, setError] = useState("");
  const go = async (queue: boolean) => {
    setError("");
    try { setSize(await post("/size", { weights: parseWeights(weights), budget, max_position_pct: maxPos, queue })); if (queue) onQueued(); } catch (e: any) { setError(e.message); }
  };
  return (
    <>
      <p className="muted">Say how much to invest and how to split it. The tool turns it into whole-share buy orders using current prices.</p>
      <Err msg={error} />
      <label>Stocks and relative weights (one per line, e.g. <code>TCS 40</code>)<textarea rows={4} value={weights} onChange={(e) => setWeights(e.target.value)} aria-label="weights" /></label>
      <div className="row" style={{ marginTop: 10 }}>
        <label>Budget (₹)<input type="number" value={budget} onChange={(e) => setBudget(+e.target.value)} /></label>
        <label>Max % in one stock<input type="number" value={maxPos} onChange={(e) => setMaxPos(+e.target.value)} style={{ width: 90 }} /></label>
        <button onClick={() => go(false)}>Preview the orders</button>
        <button className="ghost" disabled={!size} onClick={() => go(true)}>Send them to the approval queue</button>
      </div>
      <Hint k="whole" />
      {size && (
        <>
          <table style={{ marginTop: 10 }}>
            <thead><tr><th>Stock</th><th className="num">Shares</th><th className="num">Price</th><th className="num">Amount</th><th className="num">Wanted</th><th className="num">Got</th></tr></thead>
            <tbody>{size.orders.map((o: any) => (
              <tr key={o.symbol}><td>{o.symbol}</td><td className="num">{o.qty}</td><td className="num">{inr(o.price)}</td><td className="num">{inr(o.value)}</td><td className="num">{(o.weight_target * 100).toFixed(1)}%</td><td className="num">{(o.weight_actual * 100).toFixed(1)}%</td></tr>
            ))}</tbody>
          </table>
          <p>Invests {inr(size.invested)}; {inr(size.leftover)} stays in cash (5% is a deliberate safety buffer, the rest is whole-share rounding). Prices: <i>{size.price_source}</i>.</p>
          {size.skipped.map((s: any) => <Note key={s[0]} tone="warn">Skipped {s[0]}: {s[1]}</Note>)}
          {size.queued?.map((q: any) => <div key={q.id}>Order #{q.id} {q.symbol}: <Chip tone={tone(q.status)}>{q.status}</Chip> {q.reason}</div>)}
        </>
      )}
    </>
  );
}

function Rebalance({ onQueued }: { onQueued: () => void }) {
  const [targets, setTargets] = useState("TCS 40\nITC 30\nINFY 30");
  const [band, setBand] = useState(5);
  const [reb, setReb] = useState<any>(null);
  const [error, setError] = useState("");
  const go = async (queue: boolean) => {
    setError("");
    try { setReb(await post("/rebalance", { targets: parseWeights(targets), band_pct: band, queue })); if (queue) onQueued(); } catch (e: any) { setError(e.message); }
  };
  return (
    <>
      <p className="muted">Compare what you hold with the split you want, and propose only the trades that are worth making.</p>
      <Err msg={error} />
      <label>Target split (one per line)<textarea rows={4} value={targets} onChange={(e) => setTargets(e.target.value)} /></label>
      <div className="row" style={{ marginTop: 10 }}>
        <label>Ignore drift smaller than (percentage points)<input type="number" value={band} onChange={(e) => setBand(+e.target.value)} style={{ width: 90 }} /></label>
        <button onClick={() => go(false)}>Show drift and proposals</button>
        <button className="ghost" disabled={!reb || reb.orders.length === 0} onClick={() => go(true)}>Send proposals to the approval queue</button>
      </div>
      <Hint k="rebalance" />
      {reb && (
        <>
          <p>Portfolio {inr(reb.table.total_value)} (cash {inr(reb.table.cash)}).</p>
          <table>
            <thead><tr><th>Stock</th><th className="num">Now</th><th className="num">Target</th><th className="num">Drift</th></tr></thead>
            <tbody>{reb.table.rows.map((r: any) => (
              <tr key={r.symbol}><td>{r.symbol}{r.tracked ? "" : " (not in my targets)"}</td><td className="num">{r.current_pct}%</td><td className="num">{r.target_pct}%</td><td className="num">{r.drift_pct > 0 ? "+" : ""}{r.drift_pct}</td></tr>
            ))}</tbody>
          </table>
          {reb.orders.length === 0 ? <Note tone="ok">Nothing to do: everything is inside your band.</Note> :
            reb.orders.map((o: any) => <div key={o.symbol}>{o.side} {o.qty} × {o.symbol} at {inr(o.price)} = {inr(o.value)} (charges about {inr(o.est_charges)}) — {o.reason}</div>)}
          {reb.orders.some((o: any) => o.side === "SELL") && <Note tone="warn">Selling can create capital-gains tax. Check the Portfolio page first.</Note>}
          {reb.queued?.map((q: any) => <div key={q.id}>Order #{q.id} {q.side} {q.symbol}: <Chip tone={tone(q.status)}>{q.status}</Chip> {q.reason}</div>)}
        </>
      )}
    </>
  );
}
