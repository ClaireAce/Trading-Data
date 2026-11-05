"""Đọc data/ -> in bản tóm tắt cấu trúc cho từng cặp (H4 xu hướng, vùng H1, vùng M15, tin đỏ).
Cách chạy: python analyze.py <thư_mục_data>
"""
import json
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

DATA = sys.argv[1] if len(sys.argv) > 1 else "data"
PAIRS = ["XAUUSD", "EURUSD", "GBPUSD"]
VN = timezone(timedelta(hours=7))


def load(name, tf):
    df = pd.read_csv(f"{DATA}/{name}_{tf}.csv", index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def to_h4(h1):
    return h1.resample("4h", origin="epoch").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()


def atr(df, n=14):
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return float(tr.rolling(n).mean().iloc[-1])


def pivots(df, n):
    """Trả về list (vị trí, loại 'H'/'L', giá) của swing đã xác nhận."""
    out = []
    h, l = df["High"].values, df["Low"].values
    for i in range(n, len(df) - n):
        if h[i] == max(h[i - n:i + n + 1]):
            out.append((i, "H", float(h[i])))
        if l[i] == min(l[i - n:i + n + 1]):
            out.append((i, "L", float(l[i])))
    return out


def structure(df, n):
    """Xu hướng theo BOS/CHoCH bằng giá đóng cửa phá swing."""
    piv = pivots(df, n)
    c = df["Close"].values
    trend, last_h, last_l, events = 0, None, None, []
    pi = 0
    for i in range(len(df)):
        while pi < len(piv) and piv[pi][0] + n <= i:  # swing chỉ được biết sau n nến
            if piv[pi][1] == "H":
                last_h = piv[pi]
            else:
                last_l = piv[pi]
            pi += 1
        if last_h and c[i] > last_h[2]:
            kind = "BOS" if trend == 1 else "CHoCH"
            events.append((df.index[i], kind + " tăng", last_h[2]))
            trend, last_h = 1, None
        elif last_l and c[i] < last_l[2]:
            kind = "BOS" if trend == -1 else "CHoCH"
            events.append((df.index[i], kind + " giảm", last_l[2]))
            trend, last_l = -1, None
    highs = [p for p in piv if p[1] == "H"]
    lows = [p for p in piv if p[1] == "L"]
    return trend, events, highs, lows


def zones(df, n):
    """Vùng cung/cầu: nến trước cú đẩy tạo FVG + phá swing. Trả về vùng CHƯA mitigated."""
    piv = pivots(df, n)
    h, l, c = df["High"].values, df["Low"].values, df["Close"].values
    last_h = last_l = None
    pi, found = 0, []
    for i in range(3, len(df)):
        while pi < len(piv) and piv[pi][0] + n <= i:
            if piv[pi][1] == "H":
                last_h = piv[pi][2]
            else:
                last_l = piv[pi][2]
            pi += 1
        if last_h is not None and c[i] > last_h:
            for off in range(0, 3):
                j = i - off
                if j >= 2 and l[j] > h[j - 2]:  # FVG tăng
                    o = j - 2
                    found.append({"type": "CẦU", "top": float(h[o]), "bot": float(min(l[o], l[o + 1])), "pos": o, "t": df.index[o]})
                    break
            last_h = None
        if last_l is not None and c[i] < last_l:
            for off in range(0, 3):
                j = i - off
                if j >= 2 and h[j] < l[j - 2]:  # FVG giảm
                    o = j - 2
                    found.append({"type": "CUNG", "top": float(max(h[o], h[o + 1])), "bot": float(l[o]), "pos": o, "t": df.index[o]})
                    break
            last_l = None
    fresh = []
    for z in found:
        after = df.iloc[z["pos"] + 3:]
        if z["type"] == "CẦU":
            touched = (after["Low"] <= z["top"]).any()
        else:
            touched = (after["High"] >= z["bot"]).any()
        if not touched:
            fresh.append(z)
    return fresh


def fmt(x, name):
    return f"{x:,.2f}" if name == "XAUUSD" else f"{x:.5f}"


def nearest(zs, price, k=3):
    above = sorted([z for z in zs if z["bot"] > price], key=lambda z: z["bot"])[:k]
    below = sorted([z for z in zs if z["top"] < price], key=lambda z: -z["top"])[:k]
    inside = [z for z in zs if z["bot"] <= price <= z["top"]]
    return above, below, inside


def report(name, meta):
    h1, m15 = load(name, "H1"), load(name, "M15")
    h4 = to_h4(h1)
    price = float(m15["Close"].iloc[-1])
    last_t = m15.index[-1].tz_convert(VN)
    adj = meta.get("gold_offset_future_minus_spot", 0.0) if name == "XAUUSD" else 0.0
    f = lambda x: fmt(x - adj, name)  # noqa: E731

    tr4, ev4, hs4, ls4 = structure(h4, 3)
    tr1, ev1, _, _ = structure(h1, 3)
    lines = [f"===== {name} =====",
             f"Nến cuối: {last_t:%d/%m %H:%M} (giờ VN) | Giá: {f(price)}" + (f" (đã trừ offset GC-spot {adj})" if adj else ""),
             f"ATR14: H4={fmt(atr(h4), name)} H1={fmt(atr(h1), name)} M15={fmt(atr(m15), name)}"]
    lines.append(f"H4 xu hướng: {'TĂNG' if tr4 == 1 else 'GIẢM' if tr4 == -1 else 'chưa rõ'}")
    for t, k, lv in ev4[-4:]:
        lines.append(f"  H4 {k} qua {f(lv)} lúc {t.tz_convert(VN):%d/%m %H:%M}")
    if hs4 and ls4:
        # Sóng hiện tại: từ swing đối diện gần nhất tới cực trị kể từ đó
        if tr4 == 1:
            p = ls4[-1][0]
            rng_lo, rng_hi = ls4[-1][2], float(h4["High"].iloc[p:].max())
        elif tr4 == -1:
            p = hs4[-1][0]
            rng_hi, rng_lo = hs4[-1][2], float(h4["Low"].iloc[p:].min())
        else:
            rng_hi, rng_lo = hs4[-1][2], ls4[-1][2]
        sh, sl = rng_hi, rng_lo
        pd_pct = (price - rng_lo) / (rng_hi - rng_lo) * 100 if rng_hi > rng_lo else float("nan")
        lines.append(f"  Swing H4 gần nhất: đỉnh {f(sh)} | đáy {f(sl)} | EQ {f((rng_hi + rng_lo) / 2)} | giá ở {pd_pct:.0f}% (>50 premium, <50 discount)")
    lines.append(f"H1 xu hướng: {'TĂNG' if tr1 == 1 else 'GIẢM' if tr1 == -1 else 'chưa rõ'}")
    for t, k, lv in ev1[-3:]:
        lines.append(f"  H1 {k} qua {f(lv)} lúc {t.tz_convert(VN):%d/%m %H:%M}")

    for tf, df in (("H1", h1), ("M15", m15)):
        ab, be, ins = nearest(zones(df, 3), price)
        for label, zs in (("phía trên", ab), ("phía dưới", be), ("giá đang trong", ins)):
            for z in zs:
                lines.append(f"  {tf} {z['type']} {label}: {f(z['bot'])} – {f(z['top'])} (tạo {z['t'].tz_convert(VN):%d/%m %H:%M})")
    lines.append(f"Đỉnh/đáy 24h: {f(float(h1['High'].iloc[-24:].max()))} / {f(float(h1['Low'].iloc[-24:].min()))}")
    return "\n".join(lines)


def news():
    try:
        cal = json.load(open(f"{DATA}/calendar.json"))
    except Exception:  # noqa: BLE001
        return "Không có lịch tin (calendar.json lỗi/thiếu)."
    now = datetime.now(VN)
    out = ["===== TIN ĐỎ (USD/EUR/GBP) 48h tới, giờ VN ====="]
    for e in cal:
        if e.get("impact") != "High" or e.get("country") not in ("USD", "EUR", "GBP"):
            continue
        t = datetime.fromisoformat(e["date"]).astimezone(VN)
        if now - timedelta(hours=2) <= t <= now + timedelta(hours=48):
            out.append(f"{t:%a %d/%m %H:%M} {e['country']} {e['title']} | dự báo {e.get('forecast') or '-'} | trước {e.get('previous') or '-'}")
    if len(out) == 1:
        out.append("Không có tin đỏ USD/EUR/GBP trong 48h tới.")
    return "\n".join(out)


if __name__ == "__main__":
    meta = json.load(open(f"{DATA}/meta.json"))
    print(f"Dữ liệu lấy lúc (UTC): {meta.get('fetched_utc')} | lỗi: {meta.get('errors')}")
    for p in PAIRS:
        try:
            print(report(p, meta))
        except Exception as e:  # noqa: BLE001
            print(f"===== {p} ===== LỖI: {e}")
    print(news())
