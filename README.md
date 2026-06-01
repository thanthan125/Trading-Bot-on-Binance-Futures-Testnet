# Binance Futures Testnet — Trading Bot

A clean, well-structured Python trading bot for the Binance Futures Testnet (USDT-M).

---

## Features

| Feature | Details |
|---|---|
| Order types | MARKET, LIMIT, STOP_MARKET, **TWAP** (bonus) |
| Sides | BUY and SELL |
| CLI modes | Interactive menu **and** direct argparse flags |
| Logging | Dual-channel: JSON file (machine-readable) + coloured console |
| Signing | HMAC-SHA256, shown transparently in DEBUG logs |
| Reliability | Server-time sync, 3× retry with back-off, order status polling |
| Credentials | Env vars → config.json → interactive prompt (priority order) |
| Validation | Fully decoupled validators with actionable error messages |

---

## Project Structure

```
trading_bot/
├── bot/
│   ├── __init__.py
│   ├── client.py          # Binance REST client + HMAC signing
│   ├── orders.py          # Order placement logic (market, limit, stop, TWAP)
│   ├── validators.py      # Input validation (pure functions, no side effects)
│   ├── config.py          # Credential loading (env → file → prompt)
│   └── logging_config.py  # JSON file logger + coloured console logger
├── logs/
│   └── trading_bot.log    # Created automatically on first run
├── cli.py                 # Entry point
├── requirements.txt
├── config.json            # Created by you — never committed (in .gitignore)
└── README.md
```

---

## Setup

### 1. Get Testnet API Keys

1. Go to [testnet.binancefuture.com](https://testnet.binancefuture.com)
2. Log in (or register with any email)
3. Under **Account → API Key**, click **Generate**
4. Copy your API Key and Secret

### 2. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Set Credentials

**Option A — Environment variables (recommended)**
```bash
export BINANCE_API_KEY="your_key_here"
export BINANCE_API_SECRET="your_secret_here"
```

**Option B — config.json** (auto-ignored by git)
```json
{
  "api_key": "your_key_here",
  "api_secret": "your_secret_here"
}
```

**Option C — Interactive prompt**  
Just run the bot with no credentials set — it will ask.

---

## Running the Bot

### Interactive mode (recommended for first use)

```bash
python cli.py
```

You'll see a menu like:

```
╔══════════════════════════════════════════════════════╗
║        BINANCE FUTURES TESTNET  ·  TRADING BOT       ║
╚══════════════════════════════════════════════════════╝

  MAIN MENU
  [1]  Place an order
  [2]  Check account balance
  [3]  View open orders
  [4]  Exit
```

### Direct mode (scriptable)

**Market order — BUY 0.001 BTC immediately at market price:**
```bash
python cli.py --symbol BTCUSDT --side BUY --type MARKET --quantity 0.001
```

**Limit order — SELL 0.001 BTC when price reaches $96,000:**
```bash
python cli.py --symbol BTCUSDT --side SELL --type LIMIT --quantity 0.001 --price 96000
```

**Stop-market order — SELL if price drops to $90,000:**
```bash
python cli.py --symbol BTCUSDT --side SELL --type STOP_MARKET --quantity 0.001 --price 90000
```

**TWAP order — split 0.005 BTC BUY into 5 slices, 30 seconds apart:**
```bash
python cli.py --symbol BTCUSDT --side BUY --type TWAP --quantity 0.005 \
              --twap-slices 5 --twap-interval 30
```

---

## Viewing Logs

All logs are written to `logs/trading_bot.log` in newline-delimited JSON.  
This format works with any log aggregator (Datadog, Loki, etc.), and you can query it with `jq`:

```bash
# Show only errors
cat logs/trading_bot.log | grep '"level": "ERROR"'

# Pretty-print the last order placed
cat logs/trading_bot.log | grep '"message": "Order placed"' | tail -1 | python -m json.tool

# Watch logs in real time
tail -f logs/trading_bot.log
```

---

## How TWAP Works

> **TWAP = Time-Weighted Average Price**

When you place a large order all at once, you move the market against yourself (slippage). TWAP splits the order into smaller equal pieces placed at fixed time intervals.

**Example:** BUY 0.010 BTC with 5 slices, 60s apart:
```
T+0s:   BUY 0.002 BTC  (market order)
T+60s:  BUY 0.002 BTC
T+120s: BUY 0.002 BTC
T+180s: BUY 0.002 BTC
T+240s: BUY 0.002 BTC
```
Result: your average fill price is spread across 4 minutes of price action.

---

## Architecture Decisions

### Why raw `requests` instead of `python-binance`?

The `python-binance` library hides the HMAC signing, timestamp handling, and retry logic. Using raw requests makes every step explicit and debuggable — and demonstrates understanding of the underlying API protocol.

### Why JSON logs?

Plain-text logs can't be parsed programmatically. JSON logs can be shipped to Datadog, Grafana Loki, or queried with `jq` without any extra configuration.

### Why two CLI modes?

- **Interactive mode** — better UX for humans; shows live prices, validates input inline
- **Direct mode** — scriptable; useful in CI, cron jobs, or automated strategies

### Why poll order status after placement?

Binance returns `"status": "NEW"` immediately for limit orders. Polling for a few seconds after placement gives you the *actual* fill status in the CLI output — without it, the user never knows if their market order actually filled.

---

## Assumptions

- Tested against **USDT-M Futures Testnet** only (`https://testnet.binancefuture.com`)
- Quantity precision uses a conservative 3-decimal round-down (`ROUND_DOWN`) to avoid LOT_SIZE filter rejections. For production use, fetch the exact `stepSize` from `/fapi/v1/exchangeInfo`.
- TWAP uses MARKET orders per slice (not limit orders), which is the standard approach for simple TWAP execution.
- `recvWindow` defaults to 5000ms; increase to 10000 on slow connections.

---

## Requirements

- Python 3.10+
- `requests >= 2.31.0`
- No other dependencies
