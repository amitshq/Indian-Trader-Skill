"use client";
import { useEffect, useState } from "react";
import { api } from "./lib";

/** PAPER (green) or LIVE (red, with the kill switch) badge, read from the backend so it can never disagree with it. */
export default function Banner() {
  const [mode, setMode] = useState<string>("…");
  const [killed, setKilled] = useState(false);

  useEffect(() => {
    api("/health").then((h) => setMode(h.mode)).catch(() => setMode("API OFFLINE"));
  }, []);

  const kill = async () => {
    if (!confirm("Stop ALL live order sending until you delete data/KILL_SWITCH?")) return;
    await api("/live/kill", { method: "POST", body: "{}" });
    setKilled(true);
  };

  const live = mode === "LIVE";
  return (
    <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
      {live && <button onClick={kill} disabled={killed}>{killed ? "Kill switch ON" : "Kill switch"}</button>}
      <span style={{ background: live ? "#b5179e" : mode === "PAPER" ? "#2d6a4f" : "#6c757d", padding: "2px 10px", borderRadius: 4, fontSize: 13, fontWeight: 600 }}>
        {live ? "LIVE: REAL MONEY" : mode}
      </span>
    </span>
  );
}
