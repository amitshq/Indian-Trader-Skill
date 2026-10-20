"use client";
import { useEffect, useState } from "react";
import { api, inr, post } from "./lib";
import { Card, Chip, Err, Hint, Note, Page, Stat } from "./ui";

const STATUS_TEXT: Record<string, [string, "ok" | "warn" | "bad", string]> = {
  open: ["OPEN", "ok", "Normal trading is running (9:15–15:30 IST). Market orders execute right away."],
  pre_open: ["PRE-OPEN", "warn", "9:00–9:15 IST. The exchange is collecting orders to set the opening price. Normal trading starts at 9:15."],
  closed: ["CLOSED", "bad", "Outside trading hours. Practice orders here fill at the LAST price, as a rehearsal; a real order would wait for the next session."],
  holiday: ["HOLIDAY / WEEKEND", "bad", "The exchange is shut today. Nothing trades until the next trading day."],
  special_session: ["SPECIAL SESSION DAY", "warn", "A special-hours day such as Diwali Muhurat trading. NSE announces the timings separately, so this tool cannot say whether it is open."],
};

const STEP_WHY: Record<string, string> = {
  "Exchange status": "Tests: can we read what NSE itself says about the market, and does it agree with our own holiday calendar?",
  "Quotes": "Tests: do we get a price for every stock, and how OLD is each price? An old price means the market is closed or the feed is delayed.",
  "Screen": "Tests: the results screener (NSE filings + Yahoo). 'Nothing passed' is the correct answer when results data is stale: the screen fails closed instead of guessing.",
  "Basket": "Which stocks the rehearsal trades. If none passed the screen it uses an arbitrary equal-weight list, only to exercise the rest of the pipeline.",
  "Sizing": "Tests: turning rupees into whole-share orders, respecting the per-stock cap and cash buffer.",
  "Risk gate": "Tests: every order goes through your limits before it can be queued.",
  "Approval": "Tests: the approval and fill path. Here the rehearsal plays you and says yes to each order; in real use you approve one order at a time.",
  "Mark to market": "Tests: revaluing holdings at fresh prices. Without waiting, the P&L is just charges and price noise.",
  "Sell": "Tests: selling, tax lots and the capital-gains estimate.",
  "Bulk": "Tests: NSE bulk/block deal data.",
  "FII": "Tests: foreign/domestic institutional flow data.",
  "Promoter": "Tests: shareholding-pattern data from SEBI filings.",
  "News": "Tests: announcements and headline feeds.",
};
const why = (name: string) => Object.entries(STEP_WHY).find(([k]) => name.startsWith(k))?.[1];

export default function Today() {
  const [cal, setCal] = useState<any>(null);
  const [exch, setExch] = useState<any>(null);
  const [exchErr, setExchErr] = useState("");
  const [pf, setPf] = useState<any>(null);
  const [error, setError] = useState("");
  const [cap, setCap] = useState(100000);
  const [hold, setHold] = useState(0);
  const [screen, setScreen] = useState(false);
  const [running, setRunning] = useState(false);
  const [res, setRes] = useState<any>(null);

  useEffect(() => {
    api("/calendar").then(setCal).catch((e) => setError(e.message));
    api("/market/exchange").then(setExch).catch((e) => setExchErr(e.message));
    api("/portfolio").then(setPf).catch(() => {});
  }, []);

  const run = async () => {
    setRunning(true); setRes(null); setError("");
    try { setRes(await post("/demo/run", { capital: cap, hold_minutes: hold, include_screen: screen })); }
    catch (e: any) { setError(e.message); }
    setRunning(false);
  };

  const st = cal?.status?.status;
  const [label, tone, meaning] = STATUS_TEXT[st] ?? ["…", "warn", "Reading the market state…"];
  const upcoming: string[] = (cal?.holidays ?? []).filter((d: string) => d >= (cal?.status?.now_ist ?? "").slice(0, 10)).slice(0, 4);

  return (
    <Page title="Today" lead="A plain-English view of the market and your practice account, plus a button that rehearses a full trading day with dummy money so you can see whether every part works, without spending anything.">
      <Err msg={error} />
      <Card title="1. Is the market open?">
        <div className="row" style={{ marginBottom: 8 }}>
          <Stat k="Our calendar says" v={<Chip tone={tone}>{label}</Chip>} n={`Now ${cal?.status?.now_ist?.replace("T", " ").slice(0, 16) ?? "…"} IST`} />
          <Stat k="NSE itself says" v={exch ? exch.state : exchErr ? "unavailable" : "…"} n={exch ? `Last trade ${exch.trade_date} · NIFTY 50 ${exch.nifty} (${exch.nifty_change_pct}%)` : exchErr || "asking NSE…"} />
          <Stat k="Next normal open" v={cal?.status?.next_open?.replace("T", " ").slice(0, 16) ?? "…"} n="IST (Indian Standard Time, UTC+5:30)" />
        </div>
        <Note tone={tone === "bad" ? "warn" : tone}>{meaning}</Note>
        {exch && cal && (exch.state || "").toLowerCase() === "open" !== (st === "open") && (
          <Note tone="warn">NSE and our calendar disagree. For “is it open right now?”, trust NSE; then check the holiday list in <code>config/holidays.json</code>.</Note>
        )}
        <p className="muted">Upcoming trading holidays (from NSE's list): {upcoming.join(", ") || "none listed"}.{cal?.special_sessions?.length ? ` Special session: ${cal.special_sessions.join(", ")}.` : ""}</p>
        <Hint k="market_open" />
      </Card>

      <Card title="2. Your practice account" lead="This is the account you trade with on the Trade page. It starts with ₹10,00,000 of practice money.">
        <div className="grid">
          <Stat k="Cash" v={inr(pf?.cash)} n="Money not invested" />
          <Stat k="Shares" v={inr(pf?.holdings_value)} n="Value of what you hold, at the latest price" />
          <Stat k="Total" v={inr(pf ? pf.cash + pf.holdings_value : null)} n="Cash + shares" />
          <Stat k="Mode" v={pf?.mode ?? "…"} n={pf?.mode === "LIVE" ? "Real money" : "Practice money"} tone={pf?.mode === "LIVE" ? "bad" : "ok"} />
        </div>
        <Hint k="paper" />
      </Card>

      <Card title="3. Rehearse a trading day with dummy money" lead="One click runs the whole chain on real market data: market state, prices, screen, sizing, risk gate, approval, fill, selling and tax. Every step reports OK, a warning, or a failure, with the reason. It does not touch your practice account or any broker.">
        <div className="row">
          <label>Dummy capital (₹)<input type="number" min={1000} step={10000} value={cap} onChange={(e) => setCap(+e.target.value)} /></label>
          <label>Wait before re-pricing (minutes)
            <select value={hold} onChange={(e) => setHold(+e.target.value)}>
              <option value={0}>0: don't wait</option><option value={5}>5</option><option value={10}>10</option><option value={20}>20</option>
            </select>
          </label>
          <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}><input type="checkbox" checked={screen} onChange={(e) => setScreen(e.target.checked)} /> include the fundamentals screen (slower)</label>
          <button onClick={run} disabled={running}>{running ? "Running… this takes up to a minute" : "Run the rehearsal"}</button>
        </div>
        <Hint k="rehearsal" />
        {res && (
          <>
            <h3>Result</h3>
            <div className="row" style={{ marginBottom: 8 }}>
              <Chip tone="ok">{res.report.counts.OK} OK</Chip><Chip tone="warn">{res.report.counts.WARN} warnings</Chip><Chip tone="bad">{res.report.counts.FAIL} failures</Chip>
              <span className="muted">Cash left {inr(res.report.cash_left)} · estimated charges {inr(res.report.estimated_charges_paid)} · saved to <code>{res.file}</code></span>
            </div>
            {res.report.steps.map((s: any, i: number) => (
              <div key={i} className="card" style={{ marginBottom: 10, padding: 14 }}>
                <b>{i + 1}. {s.name}</b> <Chip tone={s.status === "OK" ? "ok" : s.status === "WARN" ? "warn" : "bad"}>{s.status}</Chip>
                <div>{s.summary}</div>
                {why(s.name) && <div className="muted" style={{ fontSize: 14 }}>{why(s.name)}</div>}
                {s.lines.length > 0 && <div className="mono muted" style={{ marginTop: 6 }}>{s.lines.join("\n")}</div>}
              </div>
            ))}
          </>
        )}
      </Card>

      <Card title="4. Where to next">
        <div className="grid">
          <a className="stat" href="/research" style={{ textDecoration: "none", color: "inherit" }}><div className="v">Research →</div><div className="n">Look up a stock, screen by rules, see institutional flows.</div></a>
          <a className="stat" href="/trade" style={{ textDecoration: "none", color: "inherit" }}><div className="v">Trade →</div><div className="n">Preview an order with every check explained, then approve it yourself.</div></a>
          <a className="stat" href="/portfolio" style={{ textDecoration: "none", color: "inherit" }}><div className="v">Portfolio & tax →</div><div className="n">Holdings, tax lots and what a sale would cost in tax.</div></a>
        </div>
      </Card>
    </Page>
  );
}
