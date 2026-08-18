import datetime
import threading
import time
import pandas as pd
import requests
from flask import Flask

# ==========================================
# ⚙️ 1. CONFIGURATIONS & TIMEZONE
# ==========================================
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1538096079202160670/x-zE6zkW2nWT0um6710IwtmP91D8rL1vpHLEoXpyrykpLBcskx_LLs4fx8cOfFXj98M1"

TZ_LOCAL = datetime.timezone(datetime.timedelta(hours=7))

# เลือกเฉพาะเหรียญที่มี Volume สูง เพื่อให้กราฟตรงกับ BXTrade มากที่สุด
PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

app = Flask(__name__)


@app.route("/")
def home():
    return "BXTrade 30s High-Precision Bot is running!"


def run_flask():
    app.run(host="0.0.0.0", port=8080)


def get_binance_data(symbol, interval="1m", limit=30):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            df = pd.DataFrame(
                res.json(),
                columns=[
                    "time",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "close_time",
                    "qav",
                    "num_trades",
                    "tb_base",
                    "tb_quote",
                    "ignore",
                ],
            )
            df["close"] = df["close"].astype(float)
            df["open"] = df["open"].astype(float)
            df["volume"] = df["volume"].astype(float)
            return df
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
    return None


def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def analyze_bxtrade_30s(symbol):
    # 1. เช็กเทรนด์คุมทิศทาง 5m
    df_5m = get_binance_data(symbol, interval="5m", limit=30)
    # 2. เช็กจุดกลับตัวสั้น 1m
    df_1m = get_binance_data(symbol, interval="1m", limit=30)

    if df_5m is None or df_1m is None or len(df_1m) < 20:
        return None

    # คำนวณ EMA กรองเทรนด์ใหญ่
    df_5m["EMA20"] = df_5m["close"].ewm(span=20, adjust=False).mean()
    df_5m["EMA50"] = df_5m["close"].ewm(span=50, adjust=False).mean()
    trend_5m = (
        "UP" if df_5m.iloc[-1]["EMA20"] > df_5m.iloc[-1]["EMA50"] else "DOWN"
    )

    # คำนวณ RSI & Momentum
    df_1m["RSI"] = calculate_rsi(df_1m["close"], 14)
    df_1m["EMA10"] = df_1m["close"].ewm(span=10, adjust=False).mean()

    curr = df_1m.iloc[-1]
    prev = df_1m.iloc[-2]

    price = curr["close"]
    rsi_curr = curr["RSI"]
    rsi_prev = prev["RSI"]

    signal = None

    # เงื่อนไข CALL (BUY 30s): เทรนด์ 5m ขึ้น + RSI ย่อตัวแล้วตัดกลับขึ้น + ราคายืนเหนือ EMA10
    if (
        trend_5m == "UP"
        and rsi_prev < 42
        and rsi_curr >= 42
        and price > curr["EMA10"]
    ):
        signal = "🟢 CALL (กดซื้อขึ้น 30 วิ)"

    # เงื่อนไข PUT (SELL 30s): เทรนด์ 5m ลง + RSI เด้งแล้วตัดกลับลง + ราคาหลุดใต้ EMA10
    elif (
        trend_5m == "DOWN"
        and rsi_prev > 58
        and rsi_curr <= 58
        and price < curr["EMA10"]
    ):
        signal = "🔴 PUT (กดซื้อลง 30 วิ)"

    if signal:
        now = datetime.datetime.now(TZ_LOCAL)
        curr_time = now.strftime("%Y-%m-%d %H:%M:%S")

        # คำนวณเวลานับถอยหลังให้ส่งเตือนล่วงหน้า 6-8 วินาที
        sec = now.second
        rem_sec = 30 - (sec % 30)

        msg = (
            f"⚡ **[BXTrade 30s Signal Verified]**\n"
            f"⏰ เวลาเตือน: {curr_time}\n"
            f"📊 เหรียญ: {symbol.replace('USDT', '')}\n"
            f"🎯 คำสั่ง: **{signal}**\n"
            f"🌊 เทรนด์หลัก 5m: {trend_5m}\n"
            f"📉 ราคา Binance: {price:.2f}\n"
            f"⏳ **เตรียมกดออเดอร์ใน BXTrade ในอีก {rem_sec} วินาที (กดก่อนหมดเวลา 6-8 วิ)**"
        )
        return msg
    return None


def send_discord_message(message):
    payload = {"content": message}
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"Error Discord: {e}")


def bot_loop():
    print("🤖 BXTrade 30s High-Precision Bot Active...")
    send_discord_message("🟢 บอท BXTrade 30s เริ่มสแกนกราฟเรียบร้อยแล้ว!")
    last_sent_time = 0

    while True:
        now = datetime.datetime.now(TZ_LOCAL)
        current_timestamp = time.time()

        # เช็กเฉพาะช่วงวินาทีที่ 22-24 หรือ 52-54 เพื่อให้ตรงสเปก "ส่งก่อนหมดเวลาซื้อ 6-8 วินาที"
        sec = now.second
        is_target_second = (22 <= sec <= 24) or (52 <= sec <= 54)

        # ตั้งระยะห่างส่งสัญญาณทุกๆ 15-30 นาที (ไม่ยิงซ้ำติดกันเกินไป)
        if is_target_second and (current_timestamp - last_sent_time > 900):
            for symbol in PAIRS:
                try:
                    msg = analyze_bxtrade_30s(symbol)
                    if msg:
                        send_discord_message(msg)
                        last_sent_time = current_timestamp
                        time.sleep(2)
                        break
                except Exception as e:
                    print(f"Error processing {symbol}: {e}")

        time.sleep(1)


if __name__ == "__main__":
    server_thread = threading.Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

    bot_loop()
