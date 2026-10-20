export const API = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000/api";

export const inr = (n: number | null | undefined, digits = 2) =>
  n == null ? "-" : new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: digits, minimumFractionDigits: digits }).format(n);

export async function api(path: string, init?: RequestInit): Promise<any> {
  const r = await fetch(`${API}${path}`, { ...init, headers: { "Content-Type": "application/json" } });
  let body: any = null;
  try { body = await r.json(); } catch { /* non-JSON error page */ }
  if (!r.ok) throw new Error(body?.detail ?? `HTTP ${r.status}`);
  return body;
}

export const post = (path: string, data: unknown) => api(path, { method: "POST", body: JSON.stringify(data) });

export const card = { background: "#171a21", borderRadius: 8, padding: 16, marginBottom: 16 } as const;
export const th = { textAlign: "left", padding: "4px 8px", opacity: 0.7, fontWeight: 500 } as const;
export const td = { padding: "4px 8px" } as const;
export const err = { color: "#e07a5f" } as const;
export const warn = { color: "#e9c46a" } as const;

/** "TCS 40, ITC 30" or "TCS:40\nITC:30" -> {TCS: 40, ITC: 30} */
export function parseWeights(text: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const part of text.split(/[\n,;]+/)) {
    const m = part.trim().match(/^([A-Za-z0-9&\-]+)\s*[: ]\s*([\d.]+)$/);
    if (m) out[m[1].toUpperCase()] = parseFloat(m[2]);
  }
  return out;
}
