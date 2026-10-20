"use client";
import { useEffect, useState } from "react";
import { ageText, api, inr, pct, post } from "../lib";
import { Card, Chip, Err, Hint, Note, Page, Stat, Tabs } from "../ui";

export default function Research() {
  const [tab, setTab] = useState("stock");
  return (
    <Page title="Research" lead="Understand a stock or the market before you trade. Every number says where it came from and how old it is; when the data is stale or sources disagree, it tells you instead of hiding it.">
      <Tabs tabs={[["stock", "Look up a stock"], ["screen", "Screen stocks by rules"], ["market", "Market today"]]} value={tab} onChange={setTab} />
      {tab === "stock" && <Stock />}
      {tab === "screen" && <Screen />}
      {tab === "market" && <MarketToday />}
    </Page>
  );
}

function Stock() {
  const [sym, setSym] = useState("ITC");
  const [data, setData] = useState<any>(null);
  const [news, setNews] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const go = async () => {
    setBusy(true); setError(""); setData(null); setNews(null);
    try { setData(await api(`/stock/${encodeURIComponent(sym)}`)); } catch (e: any) { setError(e.message); }
    api(`/news/${encodeURIComponent(sym)}`).then(setNews).catch(() => setNews({ items: [], errors: ["news unavailable"] }));
    setBusy(false);
  };
  const r = data?.results;
  const q = data?.quote;
  return (
    <>
      <Card title="Look up a stock" lead="Type an NSE symbol (e.g. TCS, ITC, RELIANCE, M&M). The first lookup of a stock reads NSE filings and can take 20–40 seconds; later lookups are cached.">
        <div className="row">
          <label>NSE symbol<input value={sym} onChange={(e) => setSym(e.target.value.toUpperCase())} onKeyDown={(e) => e.key === "Enter" && go()} style={{ width: 150 }} aria-label="lookup symbol" /></label>
          <button onClick={go} disabled={busy || !sym}>{busy ? "Looking up…" : "Look up"}</button>
        </div>
        <Err msg={error} />
      </Card>
      {data && (
        <>
          <Card title={`${data.symbol}: price`}>
            {q ? (
              <div className="grid">
                <Stat k="Last price" v={inr(q.price)} n={q.as_of ? `${new Date(q.as_of).toLocaleString("en-IN")} · ${ageText(q.as_of)}` : "time unknown"} />
                <Stat k="Previous close" v={inr(q.prev_close)} n={q.prev_close ? `Change ${pct((q.price / q.prev_close - 1) * 100)}` : ""} tone={q.prev_close && q.price < q.prev_close ? "bad" : "ok"} />
              </div>
            ) : <Note tone="warn">No price found for this symbol.</Note>}
            <p className="muted">Prices come from Yahoo (unofficial, may be delayed). If the market is closed you see the last close.</p>
          </Card>

          <Card title={`${data.symbol}: latest results`} lead="From the exchange-filed results where available, cross-checked with Yahoo.">
            {!r && <Note tone="warn">No results data could be read. {Object.values(data.results_errors || {}).join("; ")}</Note>}
            {r && (
              <>
                {r.data_warnings && <Note tone="warn"><b>Read before trusting these numbers:</b> {r.data_warnings}</Note>}
                {r.results_overdue === 1 || r.announced_newer_than_data === 1 ? <Hint k="stale" /> : null}
                <div className="grid">
                  <Stat k="Latest quarter in data" v={r.latest_quarter ?? "–"} n={r.reporting_basis ?? ""} />
                  <Stat k="Revenue growth (year on year)" v={pct(r.revenue_growth_yoy)} n="vs the same quarter last year" />
                  <Stat k="Profit growth (year on year)" v={pct(r.profit_growth_yoy)} n="profit to shareholders" />
                  <Stat k="Net margin" v={r.net_margin != null ? `${r.net_margin}%` : "–"} n="profit as % of revenue" />
                  <Stat k="ROCE" v={r.roce != null ? `${r.roce}%` : "–"} n="from Yahoo" />
                  <Stat k="Debt / equity" v={r.debt_to_equity ?? "–"} n="from Yahoo" />
                </div>
                <Hint k="roce" /><Hint k="de" />
              </>
            )}
            {data.promoter && (
              <p>Promoter holding: <b>{data.promoter.promoter_holding}%</b> as of {data.promoter.promoter_holding_as_of}
                {data.promoter.promoter_holding_change != null && <> ({data.promoter.promoter_holding_change >= 0 ? "+" : ""}{data.promoter.promoter_holding_change} points vs the previous filing)</>}.</p>
            )}
            <Hint k="promoter" />
          </Card>

          <Card title={`${data.symbol}: news and announcements`} lead="Filings from the exchange come first (marked !). Headlines are leads, not facts: open the source before believing one.">
            {!news && <p className="muted">Loading…</p>}
            {news?.errors?.map((e: string) => <Note key={e} tone="warn">{e}</Note>)}
            {news?.items?.slice(0, 15).map((n: any) => (
              <div key={n.id} style={{ padding: "6px 0", borderBottom: "1px solid var(--line)" }}>
                {n.important && <b className="warn">! </b>}
                <Chip tone={n.kind === "filing" ? "info" : "warn"}>{n.kind}</Chip>{" "}
                {n.url ? <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a> : n.title}
                <div className="muted" style={{ fontSize: 13 }}>{n.time ? new Date(n.time).toLocaleString("en-IN") : "time unknown"} · {n.source}{n.tags.length ? ` · ${n.tags.join(", ")}` : ""}</div>
              </div>
            ))}
          </Card>
        </>
      )}
    </>
  );
}

function Screen() {
  const [rules, setRules] = useState("");
  const [source, setSource] = useState("sample");
  const [symbols, setSymbols] = useState("RELIANCE, TCS, HDFCBANK, INFY, ITC, ICICIBANK");
  const [res, setRes] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api(`/screen/example-rules`).then((j) => setRules(JSON.stringify(j, null, 2))).catch((e) => setError(e.message)); }, []);

  const run = async () => {
    setError(""); setRes(null);
    let spec;
    try { spec = JSON.parse(rules); } catch { return setError("The rules are not valid JSON: check commas and quotes."); }
    setBusy(true);
    try { setRes(await post("/screen", { spec, source, symbols: symbols.split(/[ ,]+/).filter(Boolean) })); } catch (e: any) { setError(e.message); }
    setBusy(false);
  };

  return (
    <>
      <Card title="Screen stocks by rules" lead="A screen keeps only the stocks that meet every rule, and shows the exact number behind each pass and fail.">
        <div className="row">
          <label>Data
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="sample">Sample data (3 INVENTED companies, instant: for learning how it works)</option>
              <option value="verified">Real data (NSE filings + Yahoo: slow the first time)</option>
            </select>
          </label>
          {source === "verified" && <label>Symbols (max 20)<input value={symbols} onChange={(e) => setSymbols(e.target.value.toUpperCase())} style={{ width: 340 }} /></label>}
        </div>
        <label style={{ marginTop: 10 }}>Rules (JSON). Each rule has a metric, a comparison and a value; <code>missing: "fail"</code> means a stock with no number for a rule does not pass.
          <textarea rows={14} value={rules} onChange={(e) => setRules(e.target.value)} aria-label="rules" /></label>
        <div style={{ marginTop: 10 }}><button onClick={run} disabled={busy}>{busy ? "Screening… (real data can take a minute or two)" : "Run the screen"}</button></div>
        <Hint k="screener" />
        <Err msg={error} />
      </Card>
      {res && (
        <Card title="Result">
          {res.sample_data && <Note tone="warn">These are <b>invented</b> companies used to show how the screen works. Switch to real data for real stocks.</Note>}
          <p className="muted">Source: {res.source}</p>
          <h3>Passed ({res.passed.length})</h3>
          {res.passed.length === 0 && <Note>No stock passed. {res.sample_data ? "" : "With stale or missing results data this is the correct answer: the screen fails closed instead of guessing."}</Note>}
          {res.passed.map((p: any) => (
            <div key={p.ticker} style={{ marginBottom: 10 }}>
              <b>{p.ticker}</b> {p.name} <Chip tone="ok">score {p.score ?? "–"}</Chip>
              <ul style={{ margin: "4px 0 0" }}>{p.passes.map((w: string) => <li key={w}>{w}</li>)}</ul>
              {res.data_warnings?.[p.ticker] && <Note tone="warn">{res.data_warnings[p.ticker]}</Note>}
            </div>
          ))}
          <h3>Did not pass ({res.failed.length})</h3>
          {res.failed.map((f: any) => (
            <div key={f.ticker} style={{ marginBottom: 8 }}>
              <b>{f.ticker}</b> <span className="muted">{f.name}</span>
              <ul style={{ margin: "2px 0 0" }}>{f.fails.map((w: string) => <li key={w} className="bad">{w}</li>)}</ul>
              {res.data_warnings?.[f.ticker] && <div className="muted" style={{ fontSize: 14 }}>{res.data_warnings[f.ticker]}</div>}
            </div>
          ))}
          <Hint k="stale" />
          <p className="muted">{res.note}</p>
        </Card>
      )}
    </>
  );
}

function MarketToday() {
  const [flows, setFlows] = useState<any[]>([]);
  const [deals, setDeals] = useState<any>(null);
  const [cal, setCal] = useState<any>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const add = (m: string) => setErrors((e) => (e.includes(m) ? e : [...e, m]));
  useEffect(() => {
    api("/flows").then(setFlows).catch((e) => add(`Institutional flows: ${e.message}`));
    api("/deals?min_cr=50").then(setDeals).catch((e) => add(`Bulk/block deals: ${e.message}`));
    api("/calendar").then(setCal).catch((e) => add(`Calendar: ${e.message}`));
  }, []);
  return (
    <>
      {errors.map((e) => <Note key={e} tone="warn">{e}</Note>)}
      <Card title="Who is buying and selling: FII / DII" lead="Daily cash-market activity of foreign (FII/FPI) and domestic (DII) institutions, in ₹ crore.">
        <table>
          <thead><tr><th>Date</th><th>Who</th><th className="num">Bought</th><th className="num">Sold</th><th className="num">Net</th></tr></thead>
          <tbody>{flows.map((f) => (
            <tr key={f.category}><td>{f.date}</td><td>{f.category}</td><td className="num">{inr(f.buy)}</td><td className="num">{inr(f.sell)}</td>
              <td className={`num ${f.net >= 0 ? "ok" : "bad"}`}>{inr(f.net)}</td></tr>
          ))}</tbody>
        </table>
        <Hint k="fiidii" />
      </Card>
      <Card title={`Big trades: bulk & block deals${deals ? ` (${deals.as_on})` : ""}`} lead="Deals of at least ₹50 crore on the latest session, summed per stock.">
        <table>
          <thead><tr><th>Stock</th><th className="num">Bought ₹ cr</th><th className="num">Sold ₹ cr</th><th className="num">Net ₹ cr</th><th className="num">Deals</th></tr></thead>
          <tbody>{deals?.stocks?.map((d: any) => (
            <tr key={d.symbol}><td>{d.symbol}</td><td className="num">{d.buy_cr}</td><td className="num">{d.sell_cr}</td><td className="num">{d.net_cr}</td><td className="num">{d.deals}</td></tr>
          ))}</tbody>
        </table>
        <Hint k="bulk" />
      </Card>
      {cal && (
        <Card title="Trading holidays" lead="From NSE's official list.">
          <p>{cal.holidays.filter((d: string) => d >= (cal.status.now_ist ?? "").slice(0, 10)).join(" · ") || "none left this year"}</p>
          {cal.special_sessions?.length > 0 && <Note>Special session day(s): {cal.special_sessions.join(", ")}: timings announced by NSE.</Note>}
        </Card>
      )}
    </>
  );
}
