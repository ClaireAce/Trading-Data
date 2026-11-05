"""Lấy nến H1 / M15 / M5 + lịch tin ForexFactory, lưu vào thư mục data/."""
import json
import os
import urllib.request
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

os.makedirs("data", exist_ok=True)

# Vàng dùng hợp đồng tương lai GC=F (Yahoo không có vàng spot), giá lệch spot OANDA -> tính offset bên dưới
SYMBOLS = {"XAUUSD": "GC=F", "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X"}
FRAMES = {"H1": ("60m", "60d"), "M15": ("15m", "20d"), "M5": ("5m", "5d")}
meta = {"fetched_utc": datetime.now(timezone.utc).isoformat(), "errors": []}


def clean(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    idx = pd.to_datetime(df.index)
    df.index = idx.tz_convert("UTC") if idx.tz is not None else idx.tz_localize("UTC")
    df.index.name = "time_utc"
    return df


for name, tk in SYMBOLS.items():
    for tf, (interval, period) in FRAMES.items():
        try:
            df = clean(yf.download(tk, interval=interval, period=period, progress=False, auto_adjust=False))
            df.to_csv(f"data/{name}_{tf}.csv")
        except Exception as e:  # noqa: BLE001
            meta["errors"].append(f"{name} {tf}: {e}")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode()


# Giá vàng spot để quy đổi mức giá GC=F sang giá spot (gần đúng)
def gold_spot():
    errs = []
    try:
        return float(json.loads(get("https://api.gold-api.com/price/XAU"))["price"])
    except Exception as e:  # noqa: BLE001
        errs.append(f"gold-api: {e}")
    try:
        rows = get("https://stooq.com/q/l/?s=xauusd&f=sd2t2ohlc&h&e=csv").strip().splitlines()
        return float(rows[1].split(",")[6])
    except Exception as e:  # noqa: BLE001
        errs.append(f"stooq: {e}")
    raise RuntimeError("; ".join(errs))


try:
    spot = gold_spot()
    fut = float(pd.read_csv("data/XAUUSD_M5.csv")["Close"].iloc[-1])
    meta["gold_spot"] = spot
    meta["gold_future_last"] = fut
    meta["gold_offset_future_minus_spot"] = round(fut - spot, 2)
except Exception as e:  # noqa: BLE001
    meta["errors"].append(f"gold spot: {e}")

# Lịch tin tuần này
try:
    cal = get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
    json.loads(cal)
    with open("data/calendar.json", "w") as f:
        f.write(cal)
except Exception as e:  # noqa: BLE001
    meta["errors"].append(f"calendar: {e}")

with open("data/meta.json", "w") as f:
    json.dump(meta, f, indent=2)
print(json.dumps(meta, indent=2))
