"use client";
import { useState } from "react";
import { card, err, inr, parseWeights, post, td, th, warn } from "../lib";

export default function Plan() {
  const [weights, setWeights] = useState("TCS 40\nITC 30\nINFY 30");
  const [budget, setBudget] = useState(500000);
  const [maxPos, setMaxPos] = useState(45);
  const [size, setSize] = useState<any>(null);
  const [reb, setReb] = useState<any>(null);
  const [band, setBand] = useState(5);
  const [error, setError] = useState("");

  const runSize = async (queue: boolean) => {
    setError("");
    try { setSize(await post("/size", { weights: parseWeights(weights), budget, max_position_pct: maxPos, queue })); } catch (e: any) { setError(e.message); }
  };
  const runReb = async (queue: boolean) => {
    setError("");
    try { setReb(await post("/rebalance", { targets: parseWeights(weights), band_pct: band, queue })); } catch (e: any) { setError(e.message); }
  };

  return (
    <main style={{ maxWidth: 940, margin: "0 auto", padding: 24 }}>
      <h1 style={{ marginTop: 0 }}>Plan trades</h1>
      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Target weights (symbol weight, one per line)</h3>
        <textarea aria-label="weights" rows={5} value={weights} onChange={(e) => setWeights(e.target.value)} style={{ width: "100%", fontFamily: "monospace", background: "#0f1115", color: "#e6e6e6" }} />
        {error && <p style={err}>{error}</p>}
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Invest a budget (whole shares)</h3>
        Budget ₹ <input type="number" value={budget} onChange={(e) => setBudget(+e.target.value)} style={{ width: 110 }} />{" "}
        Max per stock % <input type="number" value={maxPos} onChange={(e) => setMaxPos(+e.target.value)} style={{ width: 60 }} />{" "}
        <button onClick={() => runSize(false)}>Preview</button>{" "}
        <button onClick={() => runSize(true)} disabled={!size}>Send to approval queue</button>
        {size && (
          <>
            <table style={{ width: "100%", marginTop: 8 }}>
              <thead><tr><th style={th}>Symbol</th><th style={th}>Qty</th><th style={th}>Price</th><th style={th}>Value</th><th style={th}>Target</th><th style={th}>Actual</th></tr></thead>
              <tbody>{size.orders.map((o: any) => (
                <tr key={o.symbol}><td style={td}>{o.symbol}</td><td style={td}>{o.qty}</td><td style={td}>{inr(o.price)}</td><td style={td}>{inr(o.value)}</td>
                  <td style={td}>{(o.weight_target * 100).toFixed(1)}%</td><td style={td}>{(o.weight_actual * 100).toFixed(1)}%</td></tr>
              ))}</tbody>
            </table>
            <p>Invested {inr(size.invested)} · leftover {inr(size.leftover)} · prices: <span style={warn}>{size.price_source}</span></p>
            {size.skipped.map((s: any) => <div key={s[0]} style={warn}>skipped {s[0]}: {s[1]}</div>)}
            {size.queued?.map((q: any) => <div key={q.id}>#{q.id} {q.symbol}: <b>{q.status}</b> {q.reason}</div>)}
          </>
        )}
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Rebalance current holdings to these weights</h3>
        Trade only if off target by more than <input type="number" value={band} onChange={(e) => setBand(+e.target.value)} style={{ width: 50 }} /> points{" "}
        <button onClick={() => runReb(false)}>Preview</button>{" "}
        <button onClick={() => runReb(true)} disabled={!reb || reb.orders.length === 0}>Send to approval queue</button>
        {reb && (
          <>
            <p>Portfolio {inr(reb.table.total_value)} (cash {inr(reb.table.cash)})</p>
            <table style={{ width: "100%" }}>
              <thead><tr><th style={th}>Symbol</th><th style={th}>Now</th><th style={th}>Target</th><th style={th}>Drift</th></tr></thead>
              <tbody>{reb.table.rows.map((r: any) => (
                <tr key={r.symbol}><td style={td}>{r.symbol}{r.tracked ? "" : " (untracked)"}</td><td style={td}>{r.current_pct}%</td><td style={td}>{r.target_pct}%</td><td style={td}>{r.drift_pct > 0 ? "+" : ""}{r.drift_pct}</td></tr>
              ))}</tbody>
            </table>
            {reb.orders.length === 0 ? <p>Nothing to do: every tracked stock is inside the band.</p> :
              reb.orders.map((o: any) => <div key={o.symbol}>{o.side} {o.qty} {o.symbol} @ {inr(o.price)} = {inr(o.value)} · est. charges {inr(o.est_charges)} ({o.reason})</div>)}
            {reb.orders.some((o: any) => o.side === "SELL") && <p style={warn}>Selling realises tax: check the Tax page first.</p>}
            {reb.queued?.map((q: any) => <div key={q.id}>#{q.id} {q.side} {q.symbol}: <b>{q.status}</b> {q.reason}</div>)}
          </>
        )}
        <p style={{ opacity: 0.6 }}>Queued orders are only proposals: approve each one on the Dashboard after the risk gate.</p>
      </div>
    </main>
  );
}
