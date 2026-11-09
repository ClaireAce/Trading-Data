"""Canh giá vàng theo vùng ghim trên Telegram.
- 🔔 Giá chạm vùng
- 🟢/🔴 Có CHoCH M5 trong vùng -> gợi ý vào luôn hay đặt limit ở đâu, SL, TP, RR
- ❌ Vùng bị phá
Dòng vùng trong tin ghim: ZONES XAU: BUY 4101-4110 | SELL 4148-4160
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

import pandas as pd

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT = os.environ["TELEGRAM_CHAT_ID"]
STATE = "data/alert_state.json"
API = f"https://api.telegram.org/bot{TOKEN}"
PIV = 2  # độ dài swing M5


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode()


def send(text):
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": text, "parse_mode": "HTML"}).encode()
    try:
        urllib.request.urlopen(f"{API}/sendMessage", data=data, timeout=30)
    except Exception:  # noqa: BLE001  (lỗi HTML thì gửi chữ thường)
        plain = re.sub(r"<[^>]+>", "", text).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        urllib.request.urlopen(f"{API}/sendMessage", data=urllib.parse.urlencode({"chat_id": CHAT, "text": plain}).encode(), timeout=30)


def px(x):
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:.1f}"


def vn(ts):
    return ts.tz_convert("Asia/Ho_Chi_Minh").strftime("%H:%M")


def load_bars(off):
    import yfinance as yf

    df = yf.download("GC=F", interval="5m", period="2d", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close"]].dropna() - off
    idx = pd.to_datetime(df.index)
    df.index = idx.tz_convert("UTC") if idx.tz is not None else idx.tz_localize("UTC")
    return df


def pivot_highs(df, n=PIV):
    h = df["High"].values
    return [i for i in range(n, len(df) - n) if h[i] == max(h[i - n:i + n + 1])]


def pivot_lows(df, n=PIV):
    lo = df["Low"].values
    return [i for i in range(n, len(df) - n) if lo[i] == min(lo[i - n:i + n + 1])]


def analyse(df, side, zlo, zhi, since, spot):
    """Trả về dict trạng thái của 1 vùng."""
    out = {"touched": False}
    after = df[df.index >= since]
    if after.empty:
        return out
    if side == "BUY":
        hit = after.index[after["Low"] <= zhi]
    else:
        hit = after.index[after["High"] >= zlo]
    spot_in = spot is not None and zlo - 1 <= spot <= zhi + 1
    if len(hit) == 0 and not spot_in:
        return out
    out["touched"] = True
    if len(hit) == 0:
        return out
    t0 = df.index.get_loc(hit[0])
    sub = df.iloc[t0:]
    atr = float((df["High"] - df["Low"]).rolling(14).mean().iloc[-1])
    buf = max(1.5, 0.1 * atr)
    # vùng bị phá: 2 nến M5 liên tiếp đóng cửa ngoài vùng (1 nến = chỉ là quét thanh khoản)
    out_side = (sub["Close"] < zlo - buf) if side == "BUY" else (sub["Close"] > zhi + buf)
    two = out_side & out_side.shift(1, fill_value=False)
    broken = sub.index[two.values]
    # cực trị sau khi chạm
    ext_pos = t0 + (int(sub["Low"].values.argmin()) if side == "BUY" else int(sub["High"].values.argmax()))
    ext_bar = df.iloc[ext_pos]
    # mức CHoCH = swing đối diện gần nhất trước cực trị
    piv = pivot_highs(df.iloc[: ext_pos + 1]) if side == "BUY" else pivot_lows(df.iloc[: ext_pos + 1])
    piv = [p for p in piv if p >= t0 - 24 and p < ext_pos]
    if piv:
        lvl_pos = piv[-1]
        lvl = float(df["High"].iloc[lvl_pos] if side == "BUY" else df["Low"].iloc[lvl_pos])
    else:
        win = df.iloc[max(0, t0 - 6): ext_pos + 1]
        lvl = float(win["High"].max() if side == "BUY" else win["Low"].min())
    post = df.iloc[ext_pos + 1:]
    ch = post.index[post["Close"] > lvl] if side == "BUY" else post.index[post["Close"] < lvl]
    if len(broken) and (len(ch) == 0 or broken[0] < ch[0]):
        out["broken"] = vn(broken[0])
        return out
    out["choch_level"] = lvl
    if len(ch) == 0:
        return out
    c_pos = df.index.get_loc(ch[0])
    # vùng flip (decisional): nến ngược chiều cuối cùng trước cú phá
    flip = None
    for i in range(c_pos - 1, ext_pos - 1, -1):
        b = df.iloc[i]
        if (side == "BUY" and b["Close"] < b["Open"]) or (side == "SELL" and b["Close"] > b["Open"]):
            flip = (float(b["Low"]), float(b["High"]))
            break
    if flip is None:
        flip = (float(ext_bar["Low"]), float(ext_bar["High"]))
    if side == "BUY":
        extreme = (float(ext_bar["Low"]), float(max(ext_bar["Open"], ext_bar["Close"])))
        sl = float(ext_bar["Low"]) - buf
        tp = float(df["High"].iloc[max(0, t0 - 48): t0 + 1].max())
        entry = flip[1]
    else:
        extreme = (float(min(ext_bar["Open"], ext_bar["Close"])), float(ext_bar["High"]))
        sl = float(ext_bar["High"]) + buf
        tp = float(df["Low"].iloc[max(0, t0 - 48): t0 + 1].min())
        entry = flip[0]
    risk = abs(entry - sl)
    out.update(choch=vn(ch[0]), flip=flip, extreme=extreme, sl=sl, tp=tp, entry=entry,
               rr=(abs(tp - entry) / risk) if risk > 0 else 0)
    return out


def main():
    chat = json.loads(get(f"{API}/getChat?chat_id={CHAT}"))["result"]
    pin = chat.get("pinned_message") or {}
    text, pin_id, pin_date = pin.get("text", ""), pin.get("message_id"), pin.get("date", 0)
    m = re.search(r"ZONES XAU:\s*(.+)", text)
    if not m or time.time() - pin_date > 20 * 3600:
        print("Không có vùng XAU còn hiệu lực")
        return
    zones = [(s.upper(), min(float(a), float(b)), max(float(a), float(b)))
             for s, a, b in re.findall(r"(BUY|SELL)\s+([\d.]+)\s*-\s*([\d.]+)", m.group(1), re.I)]

    try:
        meta = json.load(open("data/meta.json"))
        off = float(meta.get("gold_offset_future_minus_spot", 12.0))
    except Exception:  # noqa: BLE001
        off = 12.0
    if not 6 <= off <= 14:
        off = 12.0

    spot = None
    try:
        spot = float(json.loads(get("https://api.gold-api.com/price/XAU"))["price"])
    except Exception as e:  # noqa: BLE001
        print("gold-api lỗi:", e)
    df = load_bars(off)
    price = spot if spot is not None else float(df["Close"].iloc[-1])
    last_bar = vn(df.index[-1])
    since = pd.Timestamp(pin_date, unit="s", tz="UTC") - pd.Timedelta(minutes=5)

    try:
        state = json.load(open(STATE))
    except Exception:  # noqa: BLE001
        state = {}
    if state.get("pin_id") != pin_id or "z" not in state:
        state = {"pin_id": pin_id, "z": {}}
    changed = False

    for side, zlo, zhi in zones:
        key = f"{side} {zlo:g}-{zhi:g}"
        st = state["z"].setdefault(key, {})
        if st.get("done"):
            continue
        r = analyse(df, side, zlo, zhi, since, spot)
        icon = "🟢" if side == "BUY" else "🔴"
        zone_txt = f"{side} {px(zlo)}–{px(zhi)}"

        if r.get("touched") and not st.get("touch"):
            lvl = r.get("choch_level")
            send(f"🔔 <b>XAU chạm vùng {zone_txt}</b>\n"
                 f"Giá ~{px(price)} (ước tính, nến cuối {last_bar})\n"
                 f"→ Mở M5 chờ quét LQ + CHoCH"
                 + (f" qua <b>{px(lvl)}</b>" if lvl else "") + "\nChưa có CHoCH = CHƯA vào.")
            st["touch"] = True
            changed = True

        if r.get("broken"):
            send(f"❌ <b>Vùng {zone_txt} đã bị phá</b> (nến {r['broken']})\nBỏ vùng này, không vào.")
            st["done"] = True
            changed = True
            continue

        if r.get("choch"):
            in_flip = (side == "BUY" and price <= r["flip"][1] + 0.5 and price > r["sl"]) or \
                      (side == "SELL" and price >= r["flip"][0] - 0.5 and price < r["sl"])
            if in_flip:
                action = f"VÀO LUÔN được (giá {px(price)} đang trong vùng flip)"
            else:
                action = f"ĐẶT LIMIT {side} tại {px(r['entry'])}"
            rr_note = "" if r["rr"] >= 3 else "\n⚠️ RR dưới 1:3 → cân nhắc chỉ đặt limit sâu (extreme) hoặc bỏ"
            send(f"{icon} <b>XAU – CHoCH M5 trong vùng {zone_txt}</b>\n"
                 f"Nến xác nhận {r['choch']} | dữ liệu trễ ~10–15p\n"
                 f"👉 <b>{action}</b>\n"
                 f"<pre>\n"
                 f"Mục        | Giá\n"
                 f"-----------+-------------\n"
                 f"Giá hiện   | {px(price)}\n"
                 f"Limit flip | {px(r['flip'][0])}-{px(r['flip'][1])}\n"
                 f"Limit sâu  | {px(r['extreme'][0])}-{px(r['extreme'][1])}\n"
                 f"SL         | {px(r['sl'])}\n"
                 f"TP         | {px(r['tp'])}\n"
                 f"RR (flip)  | 1:{r['rr']:.1f}\n"
                 f"</pre>"
                 f"{rr_note}\n"
                 f"Nhìn lại chart M5 trước khi bấm. Quyết định là của mày.")
            st["done"] = True
            changed = True

    print(f"Giá {price:.1f} | nến cuối {last_bar} | offset {off} | vùng {zones} | state {state}")
    if changed:
        json.dump(state, open(STATE, "w"))


if __name__ == "__main__":
    main()
