"""Upstox live adapter (equity delivery only), behind every gate the paper broker has plus more.

STATUS: written from Upstox's public API v2 documentation; it has NOT been run against the real
Upstox API (no account/credentials were available while building). Unit tests use a fake HTTP
transport. Before any real order: run it against your own account with one tiny order, read
https://upstox.com/developer/api-documentation, and note SEBI's retail-algo rules (static IP whitelisting
for API orders) - check your broker's current requirements.

Hard rules enforced in code (see UpstoxBroker.approve):
  * live_enabled in config/live.json AND env INDIA_TRADER_LIVE == I_UNDERSTAND_THIS_USES_REAL_MONEY
  * no kill-switch file; order value and daily order count under the live caps
  * risk gate re-checked at approval time against the BROKER's real funds and holdings
  * CNC (delivery) only, instrument must resolve, every attempt written to an audit log
  * secrets only from environment variables, never written to disk
"""
import csv
import gzip
import io
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional
from urllib.parse import urlencode

from core import risk
from core.models import Order
from core.store import Store

from .base import Executor

API = "https://api.upstox.com/v2"
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"
CONFIG = Path(__file__).resolve().parents[2] / "config" / "live.json"
ROOT = Path(__file__).resolve().parents[2]
LIVE_PHRASE = "I_UNDERSTAND_THIS_USES_REAL_MONEY"


class UpstoxError(Exception):
    pass


class LiveBlocked(Exception):
    """A safety gate stopped a live order. Nothing was sent to the broker."""


def load_live_config(path: Path = CONFIG) -> dict:
    cfg = {"live_enabled": False, "max_order_value": 10000, "max_orders_per_day": 5, "kill_switch_file": "data/KILL_SWITCH"}
    try:
        cfg.update({k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if not k.startswith("_")})
    except FileNotFoundError:
        pass
    return cfg


class InstrumentMap:
    """NSE equity symbol -> Upstox instrument_key (e.g. NSE_EQ|INE002A01018)."""

    def __init__(self, keys: Dict[str, str]):
        self.keys = keys

    @classmethod
    def from_csv_text(cls, text: str) -> "InstrumentMap":
        out = {}
        for r in csv.DictReader(io.StringIO(text)):
            if r.get("instrument_type") == "EQUITY" and (r.get("exchange") or "").upper() in ("NSE_EQ", "NSE"):
                out[r["tradingsymbol"].upper()] = r["instrument_key"]
        return cls(out)

    @classmethod
    def download(cls, http_get: Callable[[str], bytes]) -> "InstrumentMap":
        return cls.from_csv_text(gzip.decompress(http_get(INSTRUMENTS_URL)).decode("utf-8"))

    def key(self, symbol: str) -> str:
        try:
            return self.keys[symbol.upper()]
        except KeyError:
            raise UpstoxError(f"{symbol}: no Upstox instrument (not an NSE equity symbol Upstox lists)")


class UpstoxClient:
    """Thin REST client. `http` needs .request(method, url, headers=, params=, json=, data=) -> obj with
    .status_code and .json() (httpx.Client works)."""

    def __init__(self, token: Optional[str] = None, http=None, api_key=None, api_secret=None, redirect_uri=None):
        self.token = token or os.getenv("UPSTOX_ACCESS_TOKEN")
        self.api_key, self.api_secret = api_key or os.getenv("UPSTOX_API_KEY"), api_secret or os.getenv("UPSTOX_API_SECRET")
        self.redirect_uri = redirect_uri or os.getenv("UPSTOX_REDIRECT_URI")
        self._http = http

    def _h(self):
        if self._http is None:
            import httpx
            self._http = httpx.Client(timeout=20)
        return self._http

    def _call(self, method, path, **kw):
        if not self.token and not path.startswith("/login"):
            raise UpstoxError("no access token: log in via Upstox first (tokens expire daily)")
        headers = {"Accept": "application/json", **({"Authorization": f"Bearer {self.token}"} if self.token else {})}
        r = self._h().request(method, API + path, headers=headers, **kw)
        try:
            body = r.json()
        except ValueError:
            raise UpstoxError(f"{path}: HTTP {r.status_code}, not JSON")
        if r.status_code != 200 or body.get("status") != "success":
            errs = body.get("errors") or [{"message": body.get("message", f"HTTP {r.status_code}")}]
            raise UpstoxError(f"{path}: " + "; ".join(str(e.get("message", e)) for e in errs))
        return body.get("data")

    # --- login (OAuth2 authorization code)
    def login_url(self) -> str:
        if not (self.api_key and self.redirect_uri):
            raise UpstoxError("set UPSTOX_API_KEY and UPSTOX_REDIRECT_URI")
        return f"{API}/login/authorization/dialog?" + urlencode(
            {"client_id": self.api_key, "redirect_uri": self.redirect_uri, "response_type": "code"})

    def exchange_code(self, code: str) -> str:
        if not (self.api_key and self.api_secret and self.redirect_uri):
            raise UpstoxError("set UPSTOX_API_KEY, UPSTOX_API_SECRET and UPSTOX_REDIRECT_URI")
        r = self._h().request("POST", API + "/login/authorization/token", headers={"Accept": "application/json"},
                              data={"code": code, "client_id": self.api_key, "client_secret": self.api_secret,
                                    "redirect_uri": self.redirect_uri, "grant_type": "authorization_code"})
        body = r.json()
        if r.status_code != 200 or not body.get("access_token"):
            raise UpstoxError(f"token exchange failed: {body.get('message') or body.get('errors') or r.status_code}")
        self.token = body["access_token"]
        return self.token

    # --- account and market data
    def funds(self) -> float:
        d = self._call("GET", "/user/get-funds-and-margin", params={"segment": "SEC"})
        return float(d["equity"]["available_margin"])

    def holdings(self) -> list:
        return self._call("GET", "/portfolio/long-term-holdings") or []

    def ltp(self, keys) -> dict:
        d = self._call("GET", "/market-quote/ltp", params={"instrument_key": ",".join(keys)}) or {}
        return {v["instrument_token"]: float(v["last_price"]) for v in d.values()}

    # --- orders
    def place_order(self, payload: dict) -> str:
        return self._call("POST", "/order/place", json=payload)["order_id"]

    def order_status(self, order_id: str) -> dict:
        return self._call("GET", "/order/details", params={"order_id": order_id})

    def cancel_order(self, order_id: str) -> str:
        return self._call("DELETE", "/order/cancel", params={"order_id": order_id})["order_id"]


class UpstoxQuotes:
    source = "Upstox (live)"

    def __init__(self, client: UpstoxClient, instruments: InstrumentMap):
        self.client, self.instruments = client, instruments

    def ltp(self, symbols):
        keys = {self.instruments.key(s): s for s in symbols if s.upper() in self.instruments.keys}
        if not keys:
            return {}
        return {keys[k]: p for k, p in self.client.ltp(list(keys)).items() if k in keys}


class UpstoxBroker(Executor):
    live = True

    def __init__(self, store: Store, client: UpstoxClient, instruments: InstrumentMap, risk_cfg: Optional[risk.RiskConfig] = None,
                 live_cfg: Optional[dict] = None, audit_path: Optional[Path] = None, env: Optional[dict] = None,
                 clock: Callable[[], date] = date.today, market_status: Callable[[], str] = lambda: "open"):
        self.store, self.client, self.instruments = store, client, instruments
        self.risk_cfg, self.cfg = risk_cfg or risk.RiskConfig.load(), live_cfg or load_live_config()
        self.audit_path = audit_path or ROOT / "data" / "live_audit.jsonl"
        self.env, self.clock, self.market_status = os.environ if env is None else env, clock, market_status
        self.quotes = UpstoxQuotes(client, instruments)

    # --- gates
    def gate_errors(self) -> list:
        errs = []
        if not self.cfg.get("live_enabled"):
            errs.append("live trading is disabled in config/live.json")
        if self.env.get("INDIA_TRADER_LIVE") != LIVE_PHRASE:
            errs.append(f"env INDIA_TRADER_LIVE must equal {LIVE_PHRASE}")
        if (ROOT / self.cfg["kill_switch_file"]).exists():
            errs.append("kill switch is active (delete data/KILL_SWITCH to resume)")
        if not self.client.token:
            errs.append("not logged in to Upstox (tokens expire daily)")
        return errs

    def _audit(self, event: str, **kw):
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **kw}) + "\n")

    def risk_verdict(self, order: Order, exclude_id: Optional[int] = None) -> dict:
        """Risk gate against the broker's REAL cash and holdings, not the local paper book."""
        cash = self.client.funds()
        holdings = {h["trading_symbol"].upper(): {"qty": int(h["quantity"]), "avg_price": float(h.get("average_price") or 0)}
                    for h in self.client.holdings()}
        prices = self.quotes.ltp(sorted(set(holdings) | {order.symbol}))
        pend = [o for o in self.store.list_orders("PENDING") if o.id != exclude_id and o.id != order.id]
        return risk.check_orders([order], self.risk_cfg, cash=cash, positions=holdings, prices=prices,
                                 orders_today=self.store.count_orders_on(self.clock().isoformat()),
                                 market_status=self.market_status(), pending=pend)[0]

    def submit(self, order: Order) -> Order:
        errs = order.validate()
        if errs:
            order.status, order.reason = "REJECTED", "; ".join(errs)
            return self.store.save_order(order)
        try:
            self.instruments.key(order.symbol)
            v = self.risk_verdict(order)
        except UpstoxError as e:
            order.status, order.reason = "REJECTED", str(e)
            return self.store.save_order(order)
        if v["verdict"] == "BLOCK":
            order.status, order.reason = "BLOCKED", "RISK: " + "; ".join(v["reasons"])
        return self.store.save_order(order)

    def reject(self, order_id: int, reason: str = "") -> Order:
        o = self._pending(order_id)
        o.status, o.reason = "REJECTED", reason or "declined by user"
        return self.store.save_order(o)

    def approve(self, order_id: int) -> Order:
        """Send ONE explicitly approved order. Raises LiveBlocked (nothing sent) if any gate fails."""
        o = self._pending(order_id)
        try:
            errs = self.gate_errors()
            if errs:
                raise LiveBlocked("; ".join(errs))
            ref = self.quotes.ltp([o.symbol]).get(o.symbol)
            value = o.qty * (o.price if o.order_type == "LIMIT" else ref or 0)
            if not value:
                raise LiveBlocked("no price to value the order")
            if value > self.cfg["max_order_value"]:
                raise LiveBlocked(f"order value {value:,.0f} exceeds the live cap {self.cfg['max_order_value']:,.0f}")
            if self.store.count_orders_on(self.clock().isoformat(), ("SENT", "FILLED")) >= self.cfg["max_orders_per_day"]:
                raise LiveBlocked("live daily order cap reached")
            v = self.risk_verdict(o, exclude_id=o.id)
            if v["verdict"] == "BLOCK":
                raise LiveBlocked("risk gate: " + "; ".join(v["reasons"]))
            payload = {"quantity": o.qty, "product": "D", "validity": "DAY", "price": float(o.price or 0) if o.order_type == "LIMIT" else 0,
                       "tag": f"it{o.id}", "instrument_token": self.instruments.key(o.symbol), "order_type": o.order_type,
                       "transaction_type": o.side, "disclosed_quantity": 0, "trigger_price": 0, "is_amo": self.market_status() not in ("open", "pre_open")}
            self._audit("place_attempt", order_id=o.id, fingerprint=v["fingerprint"], payload=payload)
            broker_id = self.client.place_order(payload)
        except (LiveBlocked, UpstoxError) as e:
            self._audit("blocked" if isinstance(e, LiveBlocked) else "broker_error", order_id=o.id, reason=str(e))
            if isinstance(e, LiveBlocked):
                raise
            o.status, o.reason = "REJECTED", f"broker error: {e}"
            return self.store.save_order(o)
        o.status, o.reason = "SENT", f"upstox order id {broker_id}"
        self._audit("sent", order_id=o.id, broker_order_id=broker_id)
        return self.store.save_order(o)

    def refresh(self, order_id: int) -> Order:
        """Poll Upstox for a SENT order and update its status."""
        o = self.store.get_order(order_id)
        if o is None or o.status != "SENT":
            raise ValueError(f"order {order_id} is not SENT")
        bid = o.reason.rsplit(" ", 1)[-1]
        d = self.client.order_status(bid)
        st = (d.get("status") or "").lower()
        if st == "complete":
            o.status, o.fill_price = "FILLED", float(d.get("average_price") or 0) or None
        elif st in ("rejected", "cancelled"):
            o.status, o.reason = "REJECTED", f"upstox {st}: {d.get('status_message') or ''}".strip()
        self._audit("refresh", order_id=o.id, status=st)
        return self.store.save_order(o)

    def positions(self) -> list:
        return [{"symbol": h["trading_symbol"], "qty": int(h["quantity"]), "avg_price": float(h.get("average_price") or 0)}
                for h in self.client.holdings()]

    def _pending(self, order_id: int) -> Order:
        o = self.store.get_order(order_id)
        if o is None:
            raise KeyError(f"order {order_id} not found")
        if o.status != "PENDING":
            raise ValueError(f"order {order_id} is {o.status}, not PENDING")
        return o
