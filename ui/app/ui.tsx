"use client";
import { ReactNode } from "react";
import { WORDS } from "./lib";

/** Collapsible "What does this mean?" explanation. Pass a key of WORDS or your own children. */
export function Hint({ k, title = "What does this mean?", children }: { k?: string; title?: string; children?: ReactNode }) {
  return (
    <details className="hint">
      <summary>{title}</summary>
      <div className="body">{children ?? (k ? WORDS[k] : null)}</div>
    </details>
  );
}

export function Stat({ k, v, n, tone }: { k: string; v: ReactNode; n?: ReactNode; tone?: "ok" | "warn" | "bad" }) {
  return (
    <div className="stat">
      <div className="k">{k}</div>
      <div className={`v ${tone ?? ""}`}>{v}</div>
      {n && <div className="n">{n}</div>}
    </div>
  );
}

export function Chip({ tone, children }: { tone: "ok" | "warn" | "bad" | "info"; children: ReactNode }) {
  return <span className={`chip ${tone}`}>{children}</span>;
}

export function Note({ tone, children }: { tone?: "ok" | "warn" | "bad"; children: ReactNode }) {
  return <div className={`note ${tone ?? ""}`}>{children}</div>;
}

export function Card({ title, lead, children }: { title?: string; lead?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {title && <h2>{title}</h2>}
      {lead && <p className="lead" style={{ marginBottom: 12 }}>{lead}</p>}
      {children}
    </section>
  );
}

export function Page({ title, lead, children }: { title: string; lead: ReactNode; children: ReactNode }) {
  return (
    <main className="wrap">
      <h1>{title}</h1>
      <p className="lead">{lead}</p>
      {children}
    </main>
  );
}

export function Err({ msg }: { msg?: string }) {
  return msg ? <Note tone="bad">{msg}</Note> : null;
}

export function Tabs({ tabs, value, onChange }: { tabs: [string, string][]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([id, label]) => (
        <button key={id} role="tab" aria-selected={value === id} className={value === id ? "on" : ""} onClick={() => onChange(id)}>{label}</button>
      ))}
    </div>
  );
}

/** One risk-gate check: ✓ passed, ✗ failed, – not evaluated, always with the reason in words. */
export function Checks({ checks }: { checks: { name: string; ok: boolean | null; detail: string }[] }) {
  return (
    <div>
      {checks.map((c, i) => (
        <div className="check" key={i}>
          <span className={c.ok === true ? "ok" : c.ok === false ? "bad" : "muted"} aria-label={c.ok === true ? "passed" : c.ok === false ? "failed" : "not checked"}>
            {c.ok === true ? "✓" : c.ok === false ? "✗" : "–"}
          </span>
          <span><b>{c.name}.</b> <span className={c.ok === false ? "bad" : "muted"}>{c.detail}</span></span>
        </div>
      ))}
    </div>
  );
}

export const CHARGE_WORDS: Record<string, string> = {
  brokerage: "what your broker charges per order (set to ₹0 here)",
  stt: "Securities Transaction Tax: a government tax on the trade value",
  exchange_txn: "NSE's transaction fee",
  sebi: "the market regulator's turnover fee",
  stamp_duty: "state stamp duty (charged on buys only)",
  dp: "the depository's fee for moving shares out of your demat account (charged on sells only)",
  gst: "GST on brokerage and exchange/SEBI fees",
};
