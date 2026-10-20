"use client";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api } from "./lib";

const LINKS: [string, string][] = [["/", "Today"], ["/research", "Research"], ["/trade", "Trade"], ["/portfolio", "Portfolio & tax"]];

/** Top navigation + the PAPER/LIVE badge, read from the backend so it can never disagree with it. */
export default function Nav() {
  const path = usePathname();
  const [mode, setMode] = useState<string>("…");
  const [killed, setKilled] = useState(false);

  useEffect(() => {
    api("/health").then((h) => setMode(h.mode)).catch(() => setMode("BACKEND OFFLINE"));
  }, []);

  const kill = async () => {
    if (!confirm("Stop ALL live order sending until you delete data/KILL_SWITCH?")) return;
    await api("/live/kill", { method: "POST", body: "{}" });
    setKilled(true);
  };

  const live = mode === "LIVE";
  const color = live ? "#b5179e" : mode === "PAPER" ? "#1a7f4b" : "#6c757d";
  return (
    <nav className="top" aria-label="Main">
      <b style={{ marginRight: 10 }}>India Trader</b>
      {LINKS.map(([href, label]) => (
        <a key={href} href={href} className={(href === "/" ? path === "/" : path.startsWith(href)) ? "active" : ""}>{label}</a>
      ))}
      {live && <button className="danger" style={{ marginLeft: "auto" }} onClick={kill} disabled={killed}>{killed ? "Kill switch ON" : "Kill switch"}</button>}
      <span className="badge" style={{ background: color, marginLeft: live ? 8 : "auto" }} title={live ? "Orders go to a real broker" : "Practice money: nothing is sent to a broker"}>
        {live ? "LIVE: REAL MONEY" : mode === "PAPER" ? "PAPER: practice money" : mode}
      </span>
    </nav>
  );
}
