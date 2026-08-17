import datetime
import threading
import time
import pandas as pd
import requests
from flask import Flask

# ==========================================
# ⚙️ 1. CONFIGURATIONS & TIMEZONE (UTC+7)
# ==========================================
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1538096079202160670/x-zE6zkW2nWT0um6710IwtmP91D8rL1vpHLEoXpyrykpLBcskx_LLs4fx8cOfFXj98M1"

TZ_LOCAL = datetime.timezone(datetime.timedelta(hours=7))

PAIRS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "NEARUSDT",
    "DOTUSDT",
]

app = Flask(__name__)


@app.route("/")
def home():
    return "High-Confluence Bot is running!"


def run_flask():
    app.run(host="0.0.0.0", port=8080)


def get_binance_data(symbol, interval="1m", limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            df = pd.DataFrame(
                data,
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "close_time",
                    "quote_asset_volume",
                    "number_of_trades",
                    "taker_buy_base_asset_volume",
                    "taker_buy_quote_asset_volume",
                    "ignore",
                ],
            )
            df["close"] = df["close"].astype(float)
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


def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def analyze_pair_strict(symbol):
    # 1. ดึงข้อมูล 15 นาที เพื่อดู "เทรนด์ใหญ่"
    df_15m = get_binance_data(symbol, interval="15m", limit=50)
    if df_15m is None or len(df_15m) < 30:
        return None

    df_15m["EMA20"] = calculate_ema(df_15m["close"], 20)
    df_15m["EMA50"] = calculate_ema(df_15m["close"], 50)
    trend_15m = (
        "UP"
        if df_15m.iloc[-1]["EMA20"] > df_15m.iloc[-1]["EMA50"]
        else "DOWN"
    )

    # 2. ดึงข้อมูล 1 นาที เพื่อหา "จุดเข้าเทรด"
    df_1m = get_binance_data(symbol, interval="1m", limit=50)
    if df_1m is None or len(df_1m) < 30:
        return None

    df_1m["RSI"] = calculate_rsi(df_1m["close"], 14)
    df_1m["EMA20"] = calculate_ema(df_1m["close"], 20)

    latest_1m = df_1m.iloc[-1]
    price = latest_1m["close"]
    rsi_1m = round(latest_1m["RSI"], 2)
    ema20_1m = latest_1m["EMA20"]

    signal = None

    # เงื่อนไข BUY: เทรนด์ใหญ่เป็นขาขึ้น + กราฟ 1m ย่อตัวลงมา RSI < 35 (Oversold) + ราคาเริ่มยืนเหนือ EMA20
    if trend_15m == "UP" and rsi_1m <= 35 and price > ema20_1m:
        signal = "🟢 HIGH-CONFIRM BUY"

    # เงื่อนไข SELL: เทรนด์ใหญ่เป็นขาลง + กราฟ 1m เด้งขึ้นไป RSI > 65 (Overbought) + ราคาเริ่มหลุด EMA20
    elif trend_15m == "DOWN" and rsi_1m >= 65 and price < ema20_1m:
        signal = "🔴 HIGH-CONFIRM SELL"

    if signal:
        formatted_pair = symbol.replace("USDT", "USDm")
        current_time = datetime.datetime.now(TZ_LOCAL).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        msg = (
            f"🎯 **[Strict Signal Verified]**\n"
            f"⏰ Time: {current_time}\n"
            f"📊 Pair: {formatted_pair}\n"
            f"🚀 Signal: {signal}\n"
            f"🌊 15m Trend: {trend_15m}\n"
            f"📈 1m RSI: {rsi_1m:.2f}\n"
            f"📉 Price: {price:.2f}"
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
    print("🤖 High-Confluence Bot Started (Strict Filters Active)...")
    last_processed_min = -1

    while True:
        now = datetime.datetime.now(TZ_LOCAL)

        if now.minute % 2 == 0 and now.minute != last_processed_min:
            last_processed_min = now.minute

            for symbol in PAIRS:
                try:
                    msg = analyze_pair_strict(symbol)
                    if msg:
                        send_discord_message(msg)
                        time.sleep(1.5)
                except Exception as e:
                    print(f"Error processing {symbol}: {e}")

        time.sleep(5)


if __name__ == "__main__":
    server_thread = threading.Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

    bot_loop()
