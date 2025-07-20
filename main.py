import os
import time
import math
import numpy as np
from binance.client import Client
from binance.enums import *
from dotenv import load_dotenv
from keep_alive import keep_alive  # ✅ Import keep_alive

# Load API keys
load_dotenv()
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
client = Client(api_key, api_secret)

# Config
symbol_list = ['BTCUSDT', 'ETHUSDT']
leverage = 20
risk_per_trade = 1.5
max_daily_loss = 4.5
max_trades_per_day = 5
cooldown_minutes = 5
rsi_period = 14
rsi_oversold = 30
rsi_overbought = 70

# State
daily_trades = 0
daily_loss = 0
consecutive_losses = 0

# Set leverage
for symbol in symbol_list:
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
    except:
        pass

def get_price(symbol):
    try:
        return float(client.futures_symbol_ticker(symbol=symbol)['price'])
    except:
        return None

def get_balance():
    try:
        for asset in client.futures_account_balance():
            if asset['asset'] == 'USDT':
                return float(asset['balance'])
    except:
        return 0

def get_klines(symbol, interval='1m', limit=100):
    return client.futures_klines(symbol=symbol, interval=interval, limit=limit)

def calculate_rsi(closes, period=14):
    deltas = np.diff(closes)
    ups = np.where(deltas > 0, deltas, 0)
    downs = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(ups[-period:])
    avg_loss = np.mean(downs[-period:])
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def get_signal(symbol):
    klines = get_klines(symbol)
    closes = [float(k[4]) for k in klines]
    rsi = calculate_rsi(np.array(closes), rsi_period)
    last_close = closes[-1]
    prev_close = closes[-2]

    if rsi < rsi_oversold and last_close > prev_close:
        return 'buy'
    elif rsi > rsi_overbought and last_close < prev_close:
        return 'sell'
    return 'hold'

def calculate_qty(symbol, entry_price):
    try:
        exchange_info = client.futures_exchange_info()
        for s in exchange_info['symbols']:
            if s['symbol'] == symbol:
                step_size = float([f for f in s['filters'] if f['filterType'] == 'LOT_SIZE'][0]['stepSize'])
                precision = int(round(-math.log(step_size, 10)))
                break
        else:
            print(f"[⚠️] Couldn't find precision for {symbol}")
            return 0

        qty = (risk_per_trade * leverage) / entry_price
        qty = round(qty, precision)

        if qty * entry_price < 5:
            print(f"[⚠️] Notional too low for {symbol}. Qty: {qty}, Value: {qty * entry_price:.2f}")
            return 0

        return qty
    except Exception as e:
        print(f"[❌] Error calculating quantity: {e}")
        return 0

def place_bracket_order(symbol, side, qty, entry_price):
    global daily_trades, daily_loss, consecutive_losses

    sl_price = round(entry_price * (0.99 if side == 'buy' else 1.01), 2)
    tp_price = round(entry_price * (1.02 if side == 'buy' else 0.98), 2)

    try:
        # Entry
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY if side == 'buy' else SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=qty
        )

        # Stop Loss
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side == 'buy' else SIDE_BUY,
            type=ORDER_TYPE_STOP_MARKET,
            stopPrice=sl_price,
            timeInForce='GTC',
            closePosition=True
        )

        # Take Profit
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side == 'buy' else SIDE_BUY,
            type=ORDER_TYPE_LIMIT,
            price=tp_price,
            timeInForce='GTC',
            closePosition=True
        )

        print(f"[✅] {side.upper()} order placed on {symbol} | Qty: {qty} | SL: {sl_price} | TP: {tp_price}")
        daily_trades += 1
    except Exception as e:
        print(f"[❌] Error placing trade for {symbol}: {e}")

def run_bot():
    global daily_trades, daily_loss, consecutive_losses

    while True:
        if daily_trades >= max_trades_per_day:
            print("[⛔] Max trades reached. Stopping.")
            break
        if daily_loss >= max_daily_loss:
            print("[⛔] Max daily loss reached. Stopping.")
            break
        if consecutive_losses >= 3:
            print("[⛔] 3 consecutive losses. Stopping.")
            break

        balance = get_balance()
        print(f"[💰] Balance: {balance:.2f} USDT")

        for symbol in symbol_list:
            signal = get_signal(symbol)
            price = get_price(symbol)
            print(f"[📈] {symbol} signal: {signal}")

            if signal != 'hold' and price:
                qty = calculate_qty(symbol, price)
                if qty == 0:
                    continue
                place_bracket_order(symbol, signal, qty, price)

        print(f"[⏳] Waiting {cooldown_minutes} minutes...\n")
        time.sleep(cooldown_minutes * 60)

# ✅ Keep Alive + Run Bot
if __name__ == '__main__':
    keep_alive()   # Start Flask server
    run_bot()      # Start bot loop
