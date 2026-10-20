"""SQLite store for orders, positions, cash and alerts. Default DB: data/india_trader.db."""
import json
import sqlite3
from pathlib import Path

from .models import Order

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "india_trader.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT, qty INTEGER,
  exchange TEXT, series TEXT, product TEXT, order_type TEXT, validity TEXT,
  price REAL, status TEXT, reason TEXT, fill_price REAL, created_at TEXT);
CREATE TABLE IF NOT EXISTS positions (
  symbol TEXT PRIMARY KEY, qty INTEGER, avg_price REAL);
CREATE TABLE IF NOT EXISTS account (key TEXT PRIMARY KEY, value REAL);
CREATE TABLE IF NOT EXISTS lots (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, qty INTEGER, price REAL, date TEXT, charges_per_share REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS realized (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, qty INTEGER, buy_date TEXT, sell_date TEXT, buy_price REAL,
  sell_price REAL, gross_pnl REAL, charges REAL, net_pnl REAL, term TEXT, fy TEXT);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, rule TEXT, rung INTEGER DEFAULT 0);
"""


class Store:
    def __init__(self, path=DEFAULT_DB, starting_cash: float = 1_000_000.0):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        if self.get_cash() is None:
            self.set_cash(starting_cash)

    # cash
    def get_cash(self):
        r = self.db.execute("SELECT value FROM account WHERE key='cash'").fetchone()
        return r["value"] if r else None

    def set_cash(self, v: float):
        self.db.execute("INSERT OR REPLACE INTO account VALUES ('cash', ?)", (v,))
        self.db.commit()

    # orders
    def save_order(self, o: Order) -> Order:
        if o.id is None:
            cur = self.db.execute(
                "INSERT INTO orders (symbol,side,qty,exchange,series,product,order_type,validity,"
                "price,status,reason,fill_price,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (o.symbol, o.side, o.qty, o.exchange, o.series, o.product, o.order_type,
                 o.validity, o.price, o.status, o.reason, o.fill_price, o.created_at))
            o.id = cur.lastrowid
        else:
            self.db.execute("UPDATE orders SET status=?, reason=?, fill_price=? WHERE id=?",
                            (o.status, o.reason, o.fill_price, o.id))
        self.db.commit()
        return o

    def get_order(self, oid: int):
        r = self.db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        return Order(**dict(r)) if r else None

    def list_orders(self, status=None):
        q, args = "SELECT * FROM orders", ()
        if status:
            q, args = q + " WHERE status=?", (status,)
        return [Order(**dict(r)) for r in self.db.execute(q + " ORDER BY id DESC", args)]

    # positions
    def get_position(self, symbol: str):
        r = self.db.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
        return dict(r) if r else None

    def set_position(self, symbol: str, qty: int, avg_price: float):
        if qty == 0:
            self.db.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
        else:
            self.db.execute("INSERT OR REPLACE INTO positions VALUES (?,?,?)",
                            (symbol, qty, avg_price))
        self.db.commit()

    def positions(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM positions ORDER BY symbol")]

    # tax lots (one per buy fill) and realised gains
    def add_lot(self, symbol: str, qty: int, price: float, day: str, charges_per_share: float = 0.0) -> int:
        cur = self.db.execute("INSERT INTO lots (symbol,qty,price,date,charges_per_share) VALUES (?,?,?,?,?)",
                              (symbol, qty, price, day, charges_per_share))
        self.db.commit()
        return cur.lastrowid

    def list_lots(self, symbol: str = None, open_only: bool = True):
        q, args = "SELECT * FROM lots WHERE 1=1", []
        if symbol:
            q, args = q + " AND symbol=?", [symbol]
        if open_only:
            q += " AND qty>0"
        return [dict(r) for r in self.db.execute(q + " ORDER BY date, id", args)]

    def set_lot_qty(self, lot_id: int, qty: int):
        self.db.execute("UPDATE lots SET qty=? WHERE id=?", (qty, lot_id))
        self.db.commit()

    def add_realized(self, symbol: str, rows: list):
        for r in rows:
            self.db.execute("INSERT INTO realized (symbol,qty,buy_date,sell_date,buy_price,sell_price,gross_pnl,charges,net_pnl,term,fy)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (symbol, r["qty"], r["buy_date"], r["sell_date"], r["buy_price"], r["sell_price"],
                             r["gross_pnl"], r["charges"], r["net_pnl"], r["term"], r["fy"]))
        self.db.commit()

    def list_realized(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM realized ORDER BY sell_date, id")]

    def count_orders_on(self, day: str, statuses=("PENDING", "FILLED", "SENT")) -> int:
        marks = ",".join("?" * len(statuses))
        return self.db.execute(f"SELECT COUNT(*) FROM orders WHERE substr(created_at,1,10)=? AND status IN ({marks})",
                               (day, *statuses)).fetchone()[0]

    # alerts
    def add_alert(self, rule: dict) -> int:
        cur = self.db.execute("INSERT INTO alerts (rule) VALUES (?)", (json.dumps(rule),))
        self.db.commit()
        return cur.lastrowid

    def list_alerts(self):
        return [{"id": r["id"], **json.loads(r["rule"])}
                for r in self.db.execute("SELECT * FROM alerts ORDER BY id")]

    def delete_alert(self, aid: int):
        self.db.execute("DELETE FROM alerts WHERE id=?", (aid,))
        self.db.commit()
