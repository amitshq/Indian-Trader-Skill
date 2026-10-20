"use client";
import { useEffect, useState } from "react";
import { api, card, err, inr, td, th, warn } from "../lib";

export default function Market() {
  const [cal, setCal] = useState<any>(null);
  const [flows, setFlows] = useState<any[]>([]);
  const [deals, setDeals] = useState<any>(null);
  const [sym, setSym] = useState("ITC");
  const [own, setOwn] = useState<any>(null);
  const [news, setNews] = useState<any>(null);
  const [errors, setErrors] = useState<string[]>([]);

  const addErr = (m: string) => setErrors((e) => (e.includes(m) ? e : [...e, m]));
  useEffect(() => {
    api("/calendar").then(setCal).catch((e) => addErr(`calendar: ${e.message}`));
    api("/flows").then(setFlows).catch((e) => addErr(`flows: ${e.message}`));
    api("/deals?min_cr=50").then(setDeals).catch((e) => addErr(`deals: ${e.message}`));
  }, []);

  const lookup = async () => {
    setOwn(null); setNews(null);
    api(`/ownership/${sym}`).then(setOwn).catch((e) => addErr(`ownership: ${e.message}`));
    api(`/news/${sym}`).then(setNews).catch((e) => addErr(`news: ${e.message}`));
  };

  const upcoming = cal?.holidays?.filter((d: string) => d >= (cal.status.now_ist ?? "").slice(0, 10)).slice(0, 5) ?? [];
  return (
    <main style={{ maxWidth: 940, margin: "0 auto", padding: 24 }}>
      <h1 style={{ marginTop: 0 }}>Market</h1>
      {errors.map((e) => <p key={e} style={err}>{e}</p>)}
      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Calendar (NSE)</h3>
        Status: <b>{cal?.status?.status ?? "…"}</b> · next open {cal?.status?.next_open ?? "-"}
        <div>Upcoming trading holidays: {upcoming.join(", ") || "none listed"}</div>
        {cal?.special_sessions?.length > 0 && <div style={warn}>Special sessions (timings announced by NSE): {cal.special_sessions.join(", ")}</div>}
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>FII / DII cash flows (INR crore)</h3>
        <table style={{ width: "100%" }}>
          <thead><tr><th style={th}>Date</th><th style={th}>Who</th><th style={th}>Buy</th><th style={th}>Sell</th><th style={th}>Net</th></tr></thead>
          <tbody>{flows.map((f) => (
            <tr key={f.category}><td style={td}>{f.date}</td><td style={td}>{f.category}</td><td style={td}>{inr(f.buy)}</td><td style={td}>{inr(f.sell)}</td>
              <td style={{ ...td, color: f.net >= 0 ? "#52b788" : "#e07a5f" }}>{inr(f.net)}</td></tr>
          ))}</tbody>
        </table>
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Bulk &amp; block deals {deals ? `as on ${deals.as_on}` : ""} (≥ ₹50 cr)</h3>
        <table style={{ width: "100%" }}>
          <thead><tr><th style={th}>Stock</th><th style={th}>Buy cr</th><th style={th}>Sell cr</th><th style={th}>Net cr</th><th style={th}>Deals</th></tr></thead>
          <tbody>{deals?.stocks?.map((d: any) => (
            <tr key={d.symbol}><td style={td}>{d.symbol}</td><td style={td}>{d.buy_cr}</td><td style={td}>{d.sell_cr}</td><td style={td}>{d.net_cr}</td><td style={td}>{d.deals}</td></tr>
          ))}</tbody>
        </table>
        <p style={{ opacity: 0.6 }}>A deal shows who traded, not why. Similar buy and sell values usually mean churn or an inter-fund transfer.</p>
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Stock lookup</h3>
        <input aria-label="lookup symbol" value={sym} onChange={(e) => setSym(e.target.value.toUpperCase())} style={{ width: 110 }} />{" "}
        <button onClick={lookup}>Look up</button>
        {own && (
          <p>Promoter holding {own.latest.promoter_holding ?? "-"}% as of {own.latest.promoter_holding_as_of ?? "-"}
            {own.latest.promoter_holding_change != null && ` (${own.latest.promoter_holding_change >= 0 ? "+" : ""}${own.latest.promoter_holding_change} pts vs previous filing)`}
            {own.latest.promoter_holding === 0 && " — no identified promoter group"}</p>
        )}
        {news && (
          <>
            {news.errors.map((e: string) => <div key={e} style={warn}>{e}</div>)}
            {news.items.slice(0, 15).map((n: any) => (
              <div key={n.id} style={{ marginBottom: 6 }}>
                {n.important && <b style={warn}>! </b>}
                <span style={{ opacity: 0.6 }}>{n.kind} · {n.time?.slice(0, 16).replace("T", " ") ?? "-"} · </span>
                {n.url ? <a href={n.url} target="_blank" rel="noreferrer" style={{ color: "#8ab4f8" }}>{n.title}</a> : n.title}
                {n.tags.length > 0 && <span style={{ opacity: 0.6 }}> [{n.tags.join(", ")}]</span>}
              </div>
            ))}
            <p style={{ opacity: 0.6 }}>Headlines are leads, not facts: read the filing. No predictions.</p>
          </>
        )}
      </div>
    </main>
  );
}
