"""Canh giá vàng: chạm vùng chờ (lấy từ tin nhắn được ghim trong Telegram) thì báo.
Dòng vùng trong tin ghim có dạng:
ZONES XAU: BUY 4100-4120 | BUY 4062-4067 | SELL 4150-4160
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT = os.environ["TELEGRAM_CHAT_ID"]
STATE = "data/alert_state.json"
API = f"https://api.telegram.org/bot{TOKEN}"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode()


def send(text):
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": text}).encode()
    urllib.request.urlopen(f"{API}/sendMessage", data=data, timeout=30)


# 1) Lấy vùng từ tin được ghim
chat = json.loads(get(f"{API}/getChat?chat_id={CHAT}"))["result"]
pin = chat.get("pinned_message") or {}
text, pin_id, pin_date = pin.get("text", ""), pin.get("message_id"), pin.get("date", 0)
m = re.search(r"ZONES XAU:\s*(.+)", text)
if not m or time.time() - pin_date > 20 * 3600:
    print("Không có vùng XAU còn hiệu lực trong tin ghim")
    raise SystemExit
zones = [(s.upper(), float(a), float(b)) for s, a, b in re.findall(r"(BUY|SELL)\s+([\d.]+)\s*-\s*([\d.]+)", m.group(1), re.I)]

# 2) Giá hiện tại + đỉnh/đáy 20 phút gần nhất (quy về spot)
lo = hi = price = None
try:
    price = float(json.loads(get("https://api.gold-api.com/price/XAU"))["price"])
    lo = hi = price
except Exception as e:  # noqa: BLE001
    print("gold-api lỗi:", e)
try:
    import yfinance as yf

    meta = json.load(open("data/meta.json"))
    off = float(meta.get("gold_offset_future_minus_spot", 9.0))
    if not 0 < off < 40:
        off = 9.0
    df = yf.download("GC=F", interval="5m", period="1d", progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.get_level_values(0)
    recent = df.iloc[-4:]
    r_lo, r_hi = float(recent["Low"].min()) - off, float(recent["High"].max()) - off
    lo = r_lo if lo is None else min(lo, r_lo)
    hi = r_hi if hi is None else max(hi, r_hi)
    if price is None:
        price = float(df["Close"].iloc[-1]) - off
except Exception as e:  # noqa: BLE001
    print("yfinance lỗi:", e)
if price is None:
    raise SystemExit("Không lấy được giá")

# 3) So vùng, mỗi vùng chỉ báo 1 lần cho mỗi tin ghim
try:
    state = json.load(open(STATE))
except Exception:  # noqa: BLE001
    state = {}
if state.get("pin_id") != pin_id:
    state = {"pin_id": pin_id, "sent": []}

changed = False
for side, a, b in zones:
    zlo, zhi = min(a, b), max(a, b)
    key = f"{side} {zlo:g}-{zhi:g}"
    if key in state["sent"]:
        continue
    if lo <= zhi and hi >= zlo:
        send(
            f"🔔 XAU chạm vùng {side} {zlo:,.0f}–{zhi:,.0f} (giá ~{price:,.1f}, ước tính)\n"
            f"→ Mở M5 đợi: quét LQ → CHoCH → limit vùng flip\n"
            f"Không có CHoCH = KHÔNG vào. Nhớ check tin đỏ."
        )
        state["sent"].append(key)
        changed = True

print(f"Giá {price:.1f} | khoảng {lo:.1f}–{hi:.1f} | vùng {zones} | đã báo {state['sent']}")
if changed:
    json.dump(state, open(STATE, "w"))
