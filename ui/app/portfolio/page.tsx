"use client";
import { useEffect, useState } from "react";
import { api, inr, pct } from "../lib";
import { Card, Chip, Err, Hint, Note, Page, Stat } from "../ui";

export default function Portfolio() {
  const [pf, setPf] = useState<any>(null);
  const [lots, setLots] = useState<any[]>([]);
  const [realized, setRealized] = useState<any[]>([]);
  const [est, setEst] = useState<any>(null);
  const [harvest, setHarvest] = useState<any[]>([]);
  const [f, setF] = useState({ symbol: "", qty: 1, price: 0, method: "FIFO" });
  const [sim, setSim] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/portfolio").then(setPf).catch((e) => setError(e.message));
    api("/tax/lots").then(setLots).catch(() => {});
    api("/tax/realized").then(setRealized).catch(() => {});
    api("/tax/estimate").then(setEst).catch(() => {});
    api("/tax/harvest").then(setHarvest).catch(() => {});
  }, []);

  const simulate = async () => {
    setError(""); setSim(null);
    try { setSim(await api(`/tax/simulate?symbol=${encodeURIComponent(f.symbol)}&qty=${f.qty}&price=${f.price}&method=${f.method}`)); }
    catch (e: any) { setError(e.message); }
  };

  const total = pf ? pf.cash + pf.holdings_value : null;
  const pnl = pf?.positions?.reduce((a: number, p: any) => a + (p.pnl ?? 0), 0) ?? 0;
  return (
    <Page title="Portfolio & tax" lead="What you hold, what it is worth now, and what selling it would cost in tax. All of it is practice money unless the badge says LIVE.">
      <Err msg={error} />
      <Card title="Your holdings">
        <div className="grid" style={{ marginBottom: 12 }}>
          <Stat k="Total value" v={inr(total)} n="cash + shares" />
          <Stat k="Cash" v={inr(pf?.cash)} />
          <Stat k="Shares" v={inr(pf?.holdings_value)} />
          <Stat k="Unrealised profit / loss" v={inr(pnl)} n="on shares you still hold" tone={pnl < 0 ? "bad" : "ok"} />
        </div>
        <table>
          <thead><tr><th>Stock</th><th className="num">Shares</th><th className="num">Average cost</th><th className="num">Price now</th><th className="num">Value</th><th className="num">Profit / loss</th></tr></thead>
          <tbody>{pf?.positions?.map((p: any) => (
            <tr key={p.symbol}><td>{p.symbol}</td><td className="num">{p.qty}</td><td className="num">{inr(p.avg_price)}</td><td className="num">{inr(p.ltp)}</td><td className="num">{inr(p.market_value)}</td>
              <td className={`num ${(p.pnl ?? 0) < 0 ? "bad" : "ok"}`}>{inr(p.pnl)}{p.pnl != null && p.avg_price ? ` (${pct((p.ltp / p.avg_price - 1) * 100)})` : ""}</td></tr>
          ))}</tbody>
        </table>
        {pf?.positions?.length === 0 && <p className="muted">You hold nothing yet. Use the Trade page to practise a buy.</p>}
        <p className="muted">“Average cost” is what you paid per share on average; the profit/loss ignores charges and tax.</p>
      </Card>

      <Card title="Capital-gains tax estimate" lead="Profit on shares you SOLD is taxed. This is an estimate for delivery trades only.">
        {est && (
          <>
            <div className="grid">
              <Stat k={`${est.fy} short-term profit`} v={inr(est.stcg_net)} n="sold within 12 months" />
              <Stat k="Long-term profit" v={inr(est.ltcg_net)} n="sold after more than 12 months" />
              <Stat k="Estimated tax" v={inr(est.estimated_tax)} tone={est.estimated_tax > 0 ? "warn" : "ok"} />
            </div>
            <Note tone="warn">Rates as of {est.rates_as_of} are <b>unverified</b>. {est.note}</Note>
          </>
        )}
        <Hint k="stcg" />
      </Card>

      <Card title="What if I sell?" lead="See which of your purchases a sale would use, the profit on each, and the tax it would add this year. Nothing is sold.">
        <div className="row">
          <label>Stock<input value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value.toUpperCase() })} style={{ width: 120 }} /></label>
          <label>Shares to sell<input type="number" value={f.qty} onChange={(e) => setF({ ...f, qty: +e.target.value })} style={{ width: 110 }} /></label>
          <label>Selling price (₹)<input type="number" value={f.price} onChange={(e) => setF({ ...f, price: +e.target.value })} style={{ width: 120 }} /></label>
          <label>Which purchases first?
            <select value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}><option value="FIFO">Oldest first (FIFO)</option><option value="HIFO">Most expensive first (HIFO)</option></select>
          </label>
          <button onClick={simulate}>Simulate</button>
        </div>
        {sim && (
          <>
            <table style={{ marginTop: 10 }}>
              <thead><tr><th className="num">Shares</th><th>Bought on</th><th className="num">Bought at</th><th className="num">Profit after charges</th><th>Type</th></tr></thead>
              <tbody>{sim.rows.map((r: any) => (
                <tr key={r.lot_id}><td className="num">{r.qty}</td><td>{r.buy_date}</td><td className="num">{inr(r.buy_price)}</td><td className={`num ${r.net_pnl < 0 ? "bad" : "ok"}`}>{inr(r.net_pnl)}</td><td><Chip tone={r.term === "LTCG" ? "ok" : "warn"}>{r.term === "LTCG" ? "long-term" : "short-term"}</Chip></td></tr>
              ))}</tbody>
            </table>
            <p>Estimated tax this year if you sold: <b>{inr(sim.estimate_if_sold.estimated_tax)}</b></p>
          </>
        )}
      </Card>

      <Card title="Your purchases (tax lots)" lead="Every purchase is tracked separately because tax depends on how long each one was held.">
        <table>
          <thead><tr><th>Stock</th><th className="num">Shares left</th><th className="num">Bought at</th><th>Bought on</th><th>If sold today</th></tr></thead>
          <tbody>{lots.map((l) => (
            <tr key={l.id}><td>{l.symbol}</td><td className="num">{l.qty}</td><td className="num">{inr(l.price)}</td><td>{l.date}</td><td><Chip tone={l.term === "LTCG" ? "ok" : "warn"}>{l.term === "LTCG" ? "long-term" : "short-term"}</Chip></td></tr>
          ))}</tbody>
        </table>
        {lots.length === 0 && <p className="muted">No purchases yet.</p>}
        <h3>Profit already booked</h3>
        {realized.length === 0 ? <p className="muted">No sales yet.</p> : realized.map((r) => (
          <div key={r.id}>{r.sell_date} · sold {r.qty} × {r.symbol} · profit after charges {inr(r.net_pnl)} · {r.term === "LTCG" ? "long-term" : "short-term"} · {r.fy}</div>
        ))}
      </Card>

      <Card title="Positions down more than ₹1,000 (information only)">
        {harvest.length === 0 ? <p className="muted">None.</p> : harvest.map((h) => (
          <div key={h.symbol}>{h.symbol}: {h.qty} shares, down {inr(-h.unrealised)} ({h.terms.map((t: string) => (t === "LTCG" ? "long-term" : "short-term")).join("/")})</div>
        ))}
        <p className="muted">Selling at a loss can reduce tax on other gains. Rules for buying the same stock back are not settled here: ask a chartered accountant. Intraday and futures & options profits are taxed differently and are not covered.</p>
      </Card>
    </Page>
  );
}
