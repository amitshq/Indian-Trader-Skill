"use client";
import { useEffect, useState } from "react";
import { api, card, err, inr, td, th, warn } from "../lib";

export default function Tax() {
  const [lots, setLots] = useState<any[]>([]);
  const [realized, setRealized] = useState<any[]>([]);
  const [est, setEst] = useState<any>(null);
  const [sim, setSim] = useState<any>(null);
  const [harvest, setHarvest] = useState<any[]>([]);
  const [f, setF] = useState({ symbol: "", qty: 1, price: 0, method: "FIFO" });
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api("/tax/lots"), api("/tax/realized"), api("/tax/estimate"), api("/tax/harvest")])
      .then(([l, r, e, h]) => { setLots(l); setRealized(r); setEst(e); setHarvest(h); })
      .catch((e) => setError(e.message));
  }, []);

  const simulate = async () => {
    setError("");
    try { setSim(await api(`/tax/simulate?symbol=${encodeURIComponent(f.symbol)}&qty=${f.qty}&price=${f.price}&method=${f.method}`)); }
    catch (e: any) { setError(e.message); setSim(null); }
  };

  return (
    <main style={{ maxWidth: 940, margin: "0 auto", padding: 24 }}>
      <h1 style={{ marginTop: 0 }}>Tax (delivery equity)</h1>
      {error && <p style={err}>{error}</p>}
      {est && (
        <div style={card}>
          <h3 style={{ marginTop: 0 }}>{est.fy} estimate</h3>
          STCG {inr(est.stcg_net)} · LTCG {inr(est.ltcg_net)} → estimated tax <b>{inr(est.estimated_tax)}</b>
          <p style={warn}>Rates as of {est.rates_as_of} are UNVERIFIED. {est.note}</p>
        </div>
      )}
      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Open lots</h3>
        <table style={{ width: "100%" }}>
          <thead><tr><th style={th}>Symbol</th><th style={th}>Qty</th><th style={th}>Buy price</th><th style={th}>Bought</th><th style={th}>If sold today</th></tr></thead>
          <tbody>{lots.map((l) => <tr key={l.id}><td style={td}>{l.symbol}</td><td style={td}>{l.qty}</td><td style={td}>{inr(l.price)}</td><td style={td}>{l.date}</td><td style={td}>{l.term}</td></tr>)}</tbody>
        </table>
        {lots.length === 0 && <p>No open lots.</p>}
      </div>
      <div style={card}>
        <h3 style={{ marginTop: 0 }}>What if I sell?</h3>
        <input placeholder="symbol" value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value.toUpperCase() })} style={{ width: 90 }} />{" "}
        qty <input type="number" value={f.qty} onChange={(e) => setF({ ...f, qty: +e.target.value })} style={{ width: 70 }} />{" "}
        price <input type="number" value={f.price} onChange={(e) => setF({ ...f, price: +e.target.value })} style={{ width: 90 }} />{" "}
        <select value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}><option>FIFO</option><option>HIFO</option></select>{" "}
        <button onClick={simulate}>Simulate</button>
        {sim && (
          <div style={{ marginTop: 8 }}>
            {sim.rows.map((r: any) => <div key={r.lot_id}>{r.qty} from lot {r.lot_id} ({r.buy_date} @ {inr(r.buy_price)}): net {inr(r.net_pnl)} · {r.term}</div>)}
            <div>Estimated tax this FY if sold: <b>{inr(sim.estimate_if_sold.estimated_tax)}</b></div>
          </div>
        )}
      </div>
      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Realised gains</h3>
        {realized.length === 0 ? <p>None yet.</p> : realized.map((r) => (
          <div key={r.id}>{r.sell_date} {r.symbol} {r.qty} · net {inr(r.net_pnl)} · {r.term} · {r.fy}</div>
        ))}
      </div>
      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Loss-harvest candidates (information only)</h3>
        {harvest.length === 0 ? <p>No holding is down by more than ₹1,000.</p> : harvest.map((h) => (
          <div key={h.symbol}>{h.symbol} {h.qty} sh · unrealised {inr(h.unrealised)} ({h.terms.join("/")})</div>
        ))}
        <p style={{ opacity: 0.6 }}>Check the treatment of re-buying with a chartered accountant. Intraday and F&amp;O gains are business income and are not covered here.</p>
      </div>
    </main>
  );
}
