import pyupbit
import pandas_ta as ta
import pandas as pd
pd.set_option('future.no_silent_downcasting', True)

# 🟢 [Pylance 및 로그 방어] Pandas의 미래 버전 호환성 경고(Warning)가 ERROR 로그로 둔갑하는 것을 원천 차단합니다.
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*'d' is deprecated.*")
warnings.filterwarnings("ignore", module="pandas")

import numpy as np
import telegram
import asyncio
import aiosqlite
import time
import json
import os
import re
import sys
import traceback
import requests
import ssl
import certifi
import websockets
from google import genai
from google.genai import types
from datetime import datetime, timedelta
import logging

# 🟢 로그 파일 설정
if getattr(sys, 'frozen', False): base_path = os.path.dirname(sys.executable)
else: base_path = os.path.dirname(os.path.abspath(__file__))

log_dir = os.path.join(base_path, "log")
os.makedirs(log_dir, exist_ok=True)

log_filename = datetime.now().strftime("ats_classic_log_%Y%m%d_%H%M%S.log")
log_filepath = os.path.join(log_dir, log_filename)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler(log_filepath, encoding='utf-8'),
                        logging.StreamHandler(sys.__stderr__)
                    ])
logging.getLogger().handlers[1].setLevel(logging.ERROR)

original_stdout = sys.stdout
original_stderr = sys.stderr

class StreamToLogger:
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.level, line.rstrip())

    def flush(self):
        pass

sys.stdout = StreamToLogger(logging.getLogger(), logging.INFO)
sys.stderr = StreamToLogger(logging.getLogger(), logging.ERROR)

logging.info("ATS_Classic 프로그램 시작")

# --- [0. 시스템 절대 규칙서 및 전역 변수] ---
AI_SYSTEM_INSTRUCTION = """
You are the 'Chief Strategy Officer' of an elite quantitative trading system called 'ATS-Classic'.
[IDENTITY]: You are a 'Mean Reversion & Deep Dip Sniper' (낙폭 과대 저가 매수 전문가). You specialize in catching extreme oversold conditions during market panics.

[ABSOLUTE RULES FOR AI]
1. OUTPUT FORMAT (CRITICAL): You MUST output ONLY valid JSON. 
   - DO NOT wrap the JSON in markdown code blocks.
   - DO NOT output any text outside the JSON object.

2. LANGUAGE RULE: All string values MUST be written in Korean.

3. TRADING PHILOSOPHY (CLASSIC):
   - Buy the Dip: Actively look for RSI oversold (<35), Bollinger Band lower bounds, and Extreme Fear capitulations.
   - Volume Validation (NEW): Pure oversold signals without a volume spike are considered fake. Demand high volume on dips to confirm panic selling is over.
   - Ignore Macro Downtrend: DO NOT reject trades purely because the macro trend (BTC or MTF) is bearish. Downward trends are your hunting ground.
   - Risk/Reward: Target profit must be at least 1.5x the stop loss.
   - Fake Breakout Defense: If orderbook shows a massive sell wall, reject the BUY (decision: "SKIP").

4. HARDCODED SYSTEM OVERRIDES (CRITICAL CONTEXT):
   - Rapid Breakeven Lock: If a trade reaches +1.0% net profit at any point, the Python engine mathematically locks the stop-loss to secure a guaranteed net profit. Do not penalize trades that exit here; it is an intended risk management feature.
   - NET PROFIT RULE (NEW): All performance metrics provided to you (p_rate, profit_krw) ALREADY deduct the 0.1% round-trip exchange fee. A `p_rate` of 0.0% means true absolute breakeven. Do not double-calculate fees in your logic.
   - Time-Decay Stop: If a trade fails to bounce within half of its timeout period and loses momentum, the Python engine will auto-eject early. Recognize this as a "Time-Decay" exit in your SELL_REASON.

5. DYNAMIC PARAMETER RULES:
   - Use ATR-based multipliers (target_atr_multiplier, atr_mult).
   - You have full authority to tune "scoring_modifiers" in OPTIMIZE mode to adapt to market regimes.

6. MODE-SPECIFIC OUTPUT SCHEMAS:
   - [BUY] or [POST_BUY_REPORT]: {"reason": "string", "score": int, "decision": "BUY"|"SKIP", "exit_plan": {...}}
   - [SELL_REASON]: {"rating": int, "status": "string", "reason": "string", "improvement": "string"}
   - [OPTIMIZE]: {"reason": "string", "exit_plan_guideline": "string", "strategy": {...}}

7. HALLUCINATION PREVENTION:
   - STRICT KEY RULE: NEVER invent new keys for scoring_modifiers. Use ONLY explicitly allowed keys.

8. PARAMETER DICTIONARY:
   - Tier Params MUST contain EXACTLY: {"target_atr_multiplier", "stop_loss", "atr_mult", "timeout_candles", "adaptive_breakeven_buffer", "adx_strong_trend_threshold"}. NEVER omit keys.

9. CONCISENESS RULE:
   - Keep all string explanations extremely brief (1-2 short sentences maximum).
"""

VALID_INDICATORS = [
    "supertrend", "vwap", "volume", "rsi", "bollinger", "macd", "stoch_rsi", 
    "bollinger_bandwidth", "atr_trend", "ssl_channel", 
    "stochastics", "obv", "keltner_channel", "ichimoku",
    "sma_crossover", "bollinger_breakout", "rs","z_score"
]

def get_strategy_score(name: str, prev: dict, curr: dict, price: float) -> float:
    try:
        # Type validation for curr and prev parameters
        if not isinstance(curr, dict) or not isinstance(prev, dict):
            return 0.0
        if name not in VALID_INDICATORS: return 0.0
        
        def calc_dist_score(val, baseline, weight=10.0):
            if baseline <= 0: return 0.0
            dist_pct = ((val - baseline) / baseline) * 100
            return min(100.0, max(0.0, 50.0 + (dist_pct * weight)))

        if name == "vwap": return calc_dist_score(price, curr['vwap'])
        if name == "ssl_channel": return calc_dist_score(price, curr['ssl_up'])
        if name == "sma_crossover": return calc_dist_score(curr.get('sma_short', 0), curr.get('sma_long', 0), 20.0)
        if name == "ichimoku": 
            span_max = max(curr.get('span_a', 0), curr.get('span_b', 0))
            return calc_dist_score(price, span_max)

        if name == "bollinger_breakout":
            if price <= curr['bb_u']: return 0.0
            return min(100.0, 50.0 + (((price - curr['bb_u']) / max(curr['bb_u'], 0.0001)) * 100 * 20))
        if name == "keltner_channel":
            if price <= curr.get('kc_u', 0): return 0.0
            return min(100.0, 50.0 + (((price - curr['kc_u']) / max(curr.get('kc_u', 0.0001), 0.0001)) * 100 * 20))

        if name == "stoch_rsi": 
            diff = curr.get('st_rsi_k', 0) - curr.get('st_rsi_d', 0)
            return min(100.0, max(0.0, 50.0 + (diff * 3)))
        if name == "stochastics": 
            diff = curr.get('stoch_k', 0) - curr.get('stoch_d', 0)
            return min(100.0, max(0.0, 50.0 + (diff * 3)))

        if name == "bollinger_bandwidth":
            diff_pct = ((curr['bb_bw'] - prev['bb_bw']) / max(prev['bb_bw'], 0.0001)) * 100
            return min(100.0, max(0.0, 50.0 + diff_pct * 5))
        if name == "atr_trend":
            diff_pct = ((curr['ATR'] - prev['ATR']) / max(prev['ATR'], 0.0001)) * 100
            return min(100.0, max(0.0, 50.0 + diff_pct * 5))
        if name == "obv":
            diff_pct = ((curr['obv'] - prev['obv']) / max(abs(prev['obv']), 0.0001)) * 100
            return min(100.0, max(0.0, 50.0 + diff_pct * 10))
        if name == "bollinger": 
            bb_range = curr['bb_u'] - curr['bb_l']
            if bb_range <= 0: return 50.0
            pct_b = ((price - curr['bb_l']) / bb_range) * 100
            return min(100.0, max(0.0, 100.0 - pct_b))

        if name == "volume":
            vol_factor = safe_float(STRAT.get('vol_factor'), 1.5)
            vol_sma = safe_float(curr.get('vol_sma'), 0.0001)
            curr_vol = safe_float(curr.get('volume'), 0.0)
            threshold = vol_sma * vol_factor
            return min(100.0, (curr_vol / max(threshold, 0.0001)) * 100)
        if name == "rsi":
            low_threshold = safe_float(STRAT.get('rsi_low_threshold'), 35.0)
            curr_rsi = safe_float(curr.get('rsi'), 50.0)
            return min(100.0, max(0.0, (low_threshold - curr_rsi) * 2 + 50))
        if name == "macd":
            macd_diff = safe_float(curr.get('macd_h_diff'), 0.0)
            macd_diff_sma = safe_float(curr.get('macd_h_diff_sma'), 0.0001)
            if macd_diff > 0:
                if macd_diff >= (macd_diff_sma * 1.5): return 100.0
                return min(99.0, (macd_diff / max(macd_diff_sma * 1.5, 0.0001)) * 100)
            return 0.0
        if name == "rs":
            rs_threshold = safe_float(STRAT.get('rs_threshold'), 0.0)
            curr_rs = safe_float(curr.get('rs'), 0.0)
            return min(100.0, max(0.0, (curr_rs - rs_threshold) * 20 + 50)) if curr_rs > rs_threshold else 0.0
        if name == "z_score":
            z = safe_float(curr.get('z_score'), 0.0)
            if pd.isna(z): return 50.0
            return min(100.0, max(0.0, 50.0 + (z * -20.0)))
        
        return 0.0
    except: return 0.0

# 🟢 [FIX: 슬리피지 수학 공식 교정] 원화(KRW)를 기준으로 몇 개의 코인을 샀는지 부피(Volume)를 역산하여 정확한 VWAP 산출
async def calculate_expected_slippage(ticker, buy_amt_krw):
    """호가창 5호가 뎁스를 확인하여 체결 물량(Volume) 기반으로 예상 슬리피지(%)를 정확히 계산합니다."""
    try:
        ob = await execute_upbit_api(pyupbit.get_orderbook, ticker)
        if not ob or 'orderbook_units' not in ob: return 0.0
        
        units = ob['orderbook_units'][:5]
        current_price = units[0]['ask_price']
        
        total_filled_vol = 0.0
        rem_krw = buy_amt_krw
        
        for u in units:
            ask_p = u['ask_price']
            ask_s = u['ask_size']
            
            # ask_p가 0일 경우 0으로 나누는 오류 방지
            if ask_p <= 0:
                continue # 이 호가창은 무시하고 다음으로 넘어감
                
            avail_krw = ask_p * ask_s
            
            if rem_krw <= avail_krw:
                total_filled_vol += (rem_krw / ask_p)
                rem_krw = 0
                break
            else:
                total_filled_vol += ask_s
                rem_krw -= avail_krw
        
        if total_filled_vol == 0: return 0.0
        
        # 5호가를 다 먹고도 돈이 남으면 최악의 경우를 가정하여 5호가 가격으로 마저 체결된다고 산정. 단, 호가창 최상단 가격보다 낮아질 수는 없음.
        if rem_krw > 0:
            # 남은 금액을 현재 호가창 최하단 가격으로 최대한 매수 시도
            remaining_buy_price = units[-1]['ask_price']
            # 최악의 경우를 가정하되, 현재가보다 낮아지지 않도록 보정
            effective_remaining_price = max(current_price, remaining_buy_price)
            
            # effective_remaining_price가 0일 경우 0으로 나누는 오류 방지
            if effective_remaining_price <= 0:
                return 0.0
                
            total_filled_vol += (rem_krw / effective_remaining_price)
            
        avg_exec_price = buy_amt_krw / total_filled_vol
        
        # current_price가 0일 경우 0으로 나누는 오류 방지
        if current_price <= 0:
            return 0.0
            
        slippage_pct = ((avg_exec_price - current_price) / current_price) * 100
        return slippage_pct
    except Exception as e:
        logging.error(f"슬리피지 계산 오류 ({ticker}): {e}")
        return 0.0

def get_coin_tier_params(ticker: str, curr_data: dict) -> dict:
    try:
        # Type validation for curr_data parameter
        if not isinstance(curr_data, dict):
            return STRAT.get('major_params', {})
        
        close_val = curr_data.get('close')
        atr_val = curr_data.get('ATR')
        
        if close_val is None or atr_val is None or close_val <= 0: 
            return STRAT.get('major_params', {})
        
        volatility_idx = (atr_val / close_val) * 100
        
        if volatility_idx > 3.5: return STRAT.get('high_vol_params', {})
        elif volatility_idx > 1.5: return STRAT.get('mid_vol_params', {})
        else: return STRAT.get('major_params', {})
    except Exception as e:
        logging.error(f"티어 분류 오류 ({ticker}): {e}")
        return STRAT.get('major_params', {}) 

def load_config():
    if getattr(sys, 'frozen', False): base_path = os.path.dirname(sys.executable)
    else: base_path = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_path, "config_classic.json")
    if not os.path.exists(path): print(f"❌ 설정 파일 없음"); sys.exit()
    with open(path, 'r', encoding='utf-8') as f: return json.load(f), path

def save_config(config_data, path):
    try:
        with open(path + ".tmp", 'w', encoding='utf-8') as f: json.dump(config_data, f, indent=4, ensure_ascii=False)
        os.replace(path + ".tmp", path) 
    except: pass

conf, CONFIG_PATH = load_config()
API_CONF, TG_CONF, STRAT = conf['api_keys'], conf['telegram'], conf['strategy']

upbit = pyupbit.Upbit(API_CONF['access_key'], API_CONF['secret_key'])
bot = telegram.Bot(token=TG_CONF['token'])
client = genai.Client(api_key=API_CONF['gemini_api_key'], http_options=types.HttpOptions(api_version='v1beta'))
MODEL_ID = 'gemini-2.5-flash-lite'

GLOBAL_COOLDOWN, last_ai_call_time = 0.5, 0 
last_coin_ai_call, last_sell_time, last_buy_time = {}, {}, {}
trade_data = {}  # 🟢 [추가] 빈 방패를 먼저 세워 에러 원천 차단!
last_global_buy_time = 0  
LATEST_TOP_PASS_SCORE = -999
BOT_START_TIME = time.time()  
last_auto_optimize_time = 0  
consecutive_empty_scans = 0 
REALTIME_PRICES = {}

is_running = True
last_update_id = None
SCAN_IN_PROGRESS = False
SYSTEM_STATUS = "🟢 정상 감시 중"

INDICATOR_CACHE_LOCK = asyncio.Lock()
OHLCV_CACHE_LOCK = asyncio.Lock()

# 🟢 [FIX: API Rate Limit 방어용 MTF 캐싱 도입]
MTF_CACHE = {}
MTF_CACHE_SEC = 300


TRADE_DATA_DIRTY = False  # 메모리 데이터가 변경되었는지 확인하는 플래그

# 👇 [수정 후 코드] 저장하러 가기 "전"에 스위치를 먼저 끕니다!
async def db_flush_task():
    global TRADE_DATA_DIRTY, trade_data
    while True:
        await asyncio.sleep(5.0)  
        if TRADE_DATA_DIRTY:
            # 🟢 1. 다른 놈이 켜기 전에 내가 먼저 스위치를 끕니다.
            TRADE_DATA_DIRTY = False 
            try:
                # 🟢 2. 안심하고 DB에 저장하러 다녀옵니다.
                await save_trade_status_db(trade_data) 
            except Exception as e:
                # 🟢 3. 만약 실패했다면 다시 스위치를 켜서 다음 턴을 노립니다.
                TRADE_DATA_DIRTY = True 
                logging.error(f"DB 일괄 저장 중 에러: {e}")

def robust_clean(data):
    if isinstance(data, dict): return {k: robust_clean(v) for k, v in data.items()}
    elif isinstance(data, list): return [robust_clean(v) for v in data]
    elif isinstance(data, (int, float)): return 0 if pd.isna(data) or np.isinf(data) else round(data, 8)
    else: return data

from typing import Any # 파일 맨 위에 추가하시거나 여기에 넣어도 됩니다.

# 🟢 [Pylance 완벽 방어] Any 타입을 명시하여 Pylance의 오탐을 강제로 잠재웁니다.
def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return float(default)
    try:
        return float(val)
    except (ValueError, TypeError):
        return float(default)

# 👇 [개선 로직] 타임아웃 15초로 연장 및 에러 타입(이름) 출력 기능 추가
async def send_msg(text):
    if not text: return
    text_str = str(text)
    for attempt in range(3):
        try:
            # 🟢 [핵심] 파이썬이 5초 만에 강제로 끊어버리지 못하게 wait_for를 제거합니다.
            # 대신 텔레그램 서버가 충분히 응답할 수 있도록 20초의 여유(timeout)를 줍니다.
            await bot.send_message(
                chat_id=TG_CONF['chat_id'], 
                text=text_str, 
                parse_mode='HTML',
                read_timeout=20.0,
                write_timeout=20.0,
                connect_timeout=20.0
            )
            return  # 🟢 전송에 성공하면 깔끔하게 함수를 종료(루프 탈출)합니다.
        except Exception as e:
            if attempt < 2: 
                await asyncio.sleep(2.0)
            else: 
                # 에러의 진짜 이름(TimeoutError 등)을 로그에 찍도록 개선
                err_name = type(e).__name__
                logging.error(f"❌ TG 전송 실패 [{err_name}]: {e}")

RETRY_INTERVAL_SECONDS = 2 

# 🟢 [Pylance 완벽 방어] API 호출 횟수를 최대 5회로 제한하고, 업비트의 null(None) 데이터를 원천 차단합니다.
async def execute_upbit_api(api_call, *args, **kwargs):
    for attempt in range(5):
        try:
            res = await asyncio.to_thread(api_call, *args, **kwargs)
            
            if getattr(api_call, '__name__', '') == 'get_balances' and isinstance(res, list):
                for b in res:
                    if isinstance(b, dict):
                        b['balance'] = float(b.get('balance', 0.0) if b.get('balance') is not None else 0.0)
                        b['locked'] = float(b.get('locked', 0.0) if b.get('locked') is not None else 0.0)
                        b['avg_buy_price'] = float(b.get('avg_buy_price', 0.0) if b.get('avg_buy_price') is not None else 0.0)
            return res
        except Exception as e:
            err_msg = str(e).lower()
            if "insufficient" in err_msg or "not enough" in err_msg or "400" in err_msg or "not found" in err_msg:
                logging.error(f"❌ [API 영구 거절] 논리적 오류로 재시도 중단: {e}")
                return None
                
            if "too many requests" in err_msg or "429" in err_msg:
                logging.warning(f"⚠️ API 호출 제한(429) 도달! 1.5초 대기 후 재시도...")
                await asyncio.sleep(1.5)
            else:
                logging.error(f"❌ API 네트워크/서버 오류: {e}. {RETRY_INTERVAL_SECONDS}초 후 재시도...")
                await asyncio.sleep(RETRY_INTERVAL_SECONDS)
    
    logging.error(f"🚫 API 호출 5회 연속 실패. 포기합니다: {getattr(api_call, '__name__', 'Unknown API')}")
    return None

# 🟢 비동기 SQLite DB 설정
DB_FILE = "ats_classic.db"

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, ticker TEXT, side TEXT, 
            price REAL, amount REAL, profit_krw REAL, reason TEXT, status TEXT, rating INTEGER, improvement TEXT, pass_score INTEGER)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS trade_status (
            ticker TEXT PRIMARY KEY, data_json TEXT)""")
        try: await db.execute("ALTER TABLE trade_history ADD COLUMN is_reported INTEGER DEFAULT 0")
        except: pass
        await db.commit()

async def save_trade_status_db(trade_data_dict):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM trade_status") 
        for ticker, data in trade_data_dict.items():
            try:
                def sanitize(obj):
                    if isinstance(obj, dict): return {k: sanitize(v) for k, v in obj.items()}
                    if isinstance(obj, list): return [sanitize(v) for v in obj]
                    if isinstance(obj, pd.Series): return sanitize(obj.to_dict())
                    if isinstance(obj, pd.DataFrame): return sanitize(obj.to_dict(orient='list'))
                    if isinstance(obj, np.generic): return obj.item()
                    if isinstance(obj, (int, float, str, bool)) or obj is None: return obj
                    if isinstance(obj, datetime): return obj.strftime('%Y-%m-%d %H:%M:%S')
                    try: json.dumps(obj); return obj
                    except: return str(obj)

                clean = sanitize(data)
                await db.execute("INSERT INTO trade_status (ticker, data_json) VALUES (?, ?)", (ticker, json.dumps(clean, ensure_ascii=False)))
            except Exception as e:
                logging.error(f"DB 저장 오류 ({ticker}): {e}")
        await db.commit()

async def load_trade_status_db():
    trade_data_dict = {}
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT ticker, data_json FROM trade_status") as cursor:
            async for row in cursor:
                try: trade_data_dict[row[0]] = json.loads(row[1])
                except: pass
    return trade_data_dict

# 🟢 [Pylance 방어] profit_krw의 기본값을 0.0(float)으로 명시하여 타입 에러를 해결합니다.
async def record_trade_db(ticker, side, price, amount, profit_krw=0.0, reason="", status="UNKNOWN", rating=0, improvement="", pass_score=0):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""INSERT INTO trade_history 
            (timestamp, ticker, side, price, amount, profit_krw, reason, status, rating, improvement, pass_score) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
            (timestamp, ticker, side, price, amount, profit_krw, reason, status, rating, improvement, pass_score))
        await db.commit()

async def get_performance_stats_db():
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row 
        async with db.execute("SELECT ticker, side, price, profit_krw, reason, status, rating, improvement FROM trade_history WHERE side='SELL' ORDER BY id DESC") as cursor:
            rows = await cursor.fetchall()
            rows = list(rows) # Explicitly convert to list to ensure len() is supported
            
    total_cnt = len(rows)
    history = [dict(row) for row in rows]
    wins = [t for t in history if t['profit_krw'] > 0]
    losses = [t for t in history if t['profit_krw'] <= 0]
    win_rate = (len(wins) / total_cnt * 100) if total_cnt >= 10 and total_cnt > 0 else 50.0
    total_profit = sum(t['profit_krw'] for t in history)
    return win_rate, total_cnt, len(wins), total_profit, wins, losses

async def update_top_volume_tickers():
    global STRAT
    try:
        tickers = pyupbit.get_tickers(fiat="KRW")
        if isinstance(tickers, tuple): tickers = tickers[0]
        url = f"https://api.upbit.com/v1/ticker?markets={','.join(tickers)}"
        res = await execute_upbit_api(requests.get, url, timeout=5)
        
        # Type validation for API response
        if not isinstance(res, requests.Response) or res.status_code != 200:
            return STRAT.get('tickers', [])
        
        json_response = res.json()
        if not isinstance(json_response, list):
            return STRAT.get('tickers', [])
        
        sorted_data = sorted(json_response, key=lambda x: x.get('acc_trade_price_24h', 0), reverse=True)
        exclude = ['KRW-USDT', 'KRW-USDC', 'KRW-TUSD', 'KRW-DAI']
        top_tickers = [x['market'] for x in sorted_data if isinstance(x, dict) and x.get('market') not in exclude][:30]
        
        balances = await execute_upbit_api(upbit.get_balances)
        if isinstance(balances, list):
            held = [f"KRW-{b['currency']}" for b in balances if isinstance(b, dict) and b.get('currency') != "KRW" and (float(b.get('balance', 0)) + float(b.get('locked', 0))) * float(b.get('avg_buy_price', 0)) >= 5000]
            for h in held:
                if h in trade_data and h not in top_tickers: 
                    top_tickers.append(h)

        STRAT['tickers'] = top_tickers
        conf['strategy'] = STRAT
        save_config(conf, CONFIG_PATH)
        return top_tickers
    except Exception as e:
        logging.error(f"❌ update_top_volume_tickers 오류: {e}")
        return STRAT.get('tickers', [])

FGI_CACHE = {"data": {"fear_and_greed": "50 (Neutral)"}, "timestamp": 0}

async def get_market_regime():
    global FGI_CACHE
    # 🟢 1. 캐싱 도입: 1시간(3600초) 동안은 외부 API를 찌르지 않고 기억해둔 값을 사용 (디도스 방지)
    if time.time() - FGI_CACHE['timestamp'] < 3600:
        return FGI_CACHE['data']

    try:
        # 🟢 2. 무한 재시도 늪(execute_upbit_api) 제거: 업비트가 아닌 외부 사이트이므로 직통으로 찌르고 실패하면 깔끔하게 포기
        fgi_res = await asyncio.to_thread(requests.get, "https://api.alternative.me/fng/", timeout=5)
        
        # Type validation for nested dict/list access
        if not isinstance(fgi_res, requests.Response) or fgi_res.status_code != 200:
            return FGI_CACHE['data']
        
        fgi_data = fgi_res.json()
        if not isinstance(fgi_data, dict):
            return FGI_CACHE['data']
        
        fgi_data_list = fgi_data.get('data')
        if not isinstance(fgi_data_list, list) or len(fgi_data_list) == 0:
            return FGI_CACHE['data']
        
        first_entry = fgi_data_list[0]
        if not isinstance(first_entry, dict):
            return FGI_CACHE['data']
        
        fgi_value = first_entry.get('value')
        fgi_status = first_entry.get('value_classification')
        
        if fgi_value is None or fgi_status is None:
            return FGI_CACHE['data']
        
        FGI_CACHE['data'] = {"fear_and_greed": f"{fgi_value} ({fgi_status})"}
        FGI_CACHE['timestamp'] = time.time()
        return FGI_CACHE['data']
    except Exception as e:
        # 에러 발생 시 기존에 캐싱된 값을 반환하여 봇이 절대 멈추지 않도록 방어
        logging.error(f"⚠️ FGI 지수 갱신 실패 (기존 값 유지): {e}")
        return FGI_CACHE['data']

# 👇 [새로 추가할 코드] 실시간 웹소켓 가격 수신 엔진
async def websocket_ticker_task():
    global REALTIME_PRICES, STRAT, trade_data
    uri = "wss://api.upbit.com/websocket/v1"

    # 🟢 [추가] certifi를 이용해 안전한 SSL/TLS 컨텍스트 생성
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    while True:
        try:
            # 🟢 [수정] websockets.connect에 ssl=ssl_context 파라미터 추가!
            async with websockets.connect(uri, ping_interval=60, ping_timeout=30, ssl=ssl_context) as websocket:
                logging.info("🌐 업비트 실시간 웹소켓 연결 성공!")

                # 현재 감시해야 할 종목 리스트 (보유종목 + 스캔대상 + BTC)
                current_tickers = list(set(STRAT.get('tickers', []) + ["KRW-BTC"] + list(trade_data.keys())))

                # 업비트 웹소켓 구독 요청 (isOnlyRealtime=True 로 설정해 트래픽 최소화)
                subscribe_fmt = [
                    {"ticket": "ats_classic_ticker"},
                    {"type": "ticker", "codes": current_tickers, "isOnlyRealtime": True}
                ]
                await websocket.send(json.dumps(subscribe_fmt))
                last_subscribed_tickers = set(current_tickers)

                while True:
                    # 1. 중간에 코인이 매수/매도되거나 스캔 대상이 바뀌면 동적으로 웹소켓 '재구독' 처리
                    new_tickers = set(STRAT.get('tickers', []) + ["KRW-BTC"] + list(trade_data.keys()))
                    if new_tickers != last_subscribed_tickers:
                        subscribe_fmt = [
                            {"ticket": "ats_classic_ticker"},
                            {"type": "ticker", "codes": list(new_tickers), "isOnlyRealtime": True}
                        ]
                        await websocket.send(json.dumps(subscribe_fmt))
                        last_subscribed_tickers = new_tickers
                        logging.info(f"🔄 웹소켓 감시 종목 동적 갱신 (총 {len(new_tickers)}개)")

                    # 2. 데이터 수신 (Timeout을 짧게 주어 루프가 멈추지 않고 종목 변경을 체크할 수 있게 함)
                    try:
                        raw_data = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        if isinstance(raw_data, bytes):
                            data = json.loads(raw_data.decode('utf-8'))
                        elif isinstance(raw_data, str):
                            data = json.loads(raw_data)
                        else:
                            data = raw_data

                        # dict 타입 확인 후 키 접근 (타입 체커 대응)
                        if isinstance(data, dict) and 'code' in data and 'trade_price' in data:
                            REALTIME_PRICES[str(data['code'])] = float(data['trade_price'])
                    except asyncio.TimeoutError:
                        continue # 1초 동안 시장에 거래가 없으면 다음 루프로 넘어가서 종목 변경 유무만 체크

        except Exception as e:
            logging.error(f"⚠️ 웹소켓 연결 끊김 ({e}). 3초 후 재연결 자동 시도...")
            await asyncio.sleep(3.0)
            

# 👇 [새로 추가할 함수] 순수 CPU 연산(pandas_ta)을 전담할 백그라운드 스레드용 함수
from typing import Optional, Tuple

def _calculate_ta_indicators(df: pd.DataFrame, btc_df: Optional[pd.DataFrame], strat_params: dict) -> Tuple[Optional[pd.Series], Optional[pd.Series]]:
    try:
        # Type validation for all parameters
        if not isinstance(df, pd.DataFrame) or df is None or len(df) < 75:
            return None, None
        if not isinstance(strat_params, dict):
            strat_params = {}
        if btc_df is not None and not isinstance(btc_df, pd.DataFrame):
            btc_df = None
        
        df['ATR'] = df.ta.atr(length=strat_params.get('atr_len', 14))
        df['ATR'] = df['ATR'].fillna(0).replace([np.inf, -np.inf], 0)
        
        st = df.ta.supertrend(length=strat_params.get('st_len', 20), multiplier=strat_params.get('st_mult', 3.0))
        if st is None or (isinstance(st, pd.DataFrame) and st.empty): 
            return None, None
        df['ST_DIR'] = st[st.columns[1]]
        df['vwap'] = df.ta.vwap()
        df['vol_sma'] = df['volume'].rolling(window=20).mean()
        df['obv'] = df.ta.obv()
        df['rsi'] = df.ta.rsi(length=strat_params.get('rsi_len', 14))
        
        st_rsi = df.ta.stochrsi(length=strat_params.get('stoch_rsi_len', 14), k=strat_params.get('stoch_rsi_k_len', 3), d=strat_params.get('stoch_rsi_d_len', 3))
        if st_rsi is not None and isinstance(st_rsi, pd.DataFrame):
            df['st_rsi_k'], df['st_rsi_d'] = st_rsi.iloc[:, 0], st_rsi.iloc[:, 1]
        else:
            df['st_rsi_k'], df['st_rsi_d'] = 50, 50
        
        stoch = df.ta.stoch(k=strat_params.get('stochastics_k_len', 14), d=strat_params.get('stochastics_d_len', 3))
        if stoch is not None and isinstance(stoch, pd.DataFrame):
            df['stoch_k'], df['stoch_d'] = stoch.iloc[:, 0], stoch.iloc[:, 1]
        
        macd = df.ta.macd(fast=strat_params.get('macd_fast_len', 12), slow=strat_params.get('macd_slow_len', 26), signal=strat_params.get('macd_signal_len', 9))
        if macd is None or (isinstance(macd, pd.DataFrame) and macd.empty): 
            return None, None
        df['macd_h'] = macd[macd.columns[1]]
        df['macd_h_diff'] = df['macd_h'].diff()
        df['macd_h_diff_sma'] = df['macd_h_diff'].abs().rolling(window=10).mean()
        
        adx_df = df.ta.adx(length=strat_params.get('adx_len', 14))
        if adx_df is not None and isinstance(adx_df, pd.DataFrame):
            df['adx'] = adx_df.iloc[:, 0]
        
        bb = df.ta.bbands(length=strat_params.get('bollinger_len', 20), std=strat_params.get('bollinger_std_dev', 2))
        if bb is not None and isinstance(bb, pd.DataFrame):
            df['bb_l'], df['bb_u'], df['bb_bw'] = bb.iloc[:, 0], bb.iloc[:, 2], bb.iloc[:, 3]
        
        kc = df.ta.kc(length=strat_params.get('keltner_channel_len', 20), scalar=strat_params.get('keltner_channel_atr_mult', 1.5))
        if kc is not None and isinstance(kc, pd.DataFrame):
            df['kc_u'] = kc.iloc[:, 2]
        
        # 4. 일목균형표(Ichimoku) 방어 및 정수(int) 강제 변환
        # 🟢 [Pylance 및 런타임 방어] JSON에서 float(9.0)이나 str("9")로 넘어와도 무조건 int(9)로 깎아서 넣습니다.
        t_len = int(float(strat_params.get('ichimoku_conversion_len', 9)))
        k_len = int(float(strat_params.get('ichimoku_base_len', 26)))
        s_len = int(float(strat_params.get('ichimoku_lead_span_b_len', 52)))
        
        ichi_result = df.ta.ichimoku(tenkan=t_len, kijun=k_len, senkou=s_len)
        
        if ichi_result is not None:
            ichi = ichi_result[0] if isinstance(ichi_result, tuple) else ichi_result
            if isinstance(ichi, pd.DataFrame):
                df['span_a'], df['span_b'] = ichi.iloc[:, 2], ichi.iloc[:, 3]
            else:
                df['span_a'], df['span_b'] = df['close'], df['close']
        else:
            df['span_a'], df['span_b'] = df['close'], df['close']
        
        ssl_len = strat_params.get('ssl_len', 70)
        sma_h, sma_l = df.ta.sma(close=df['high'], length=ssl_len), df.ta.sma(close=df['low'], length=ssl_len)
        df['c'] = np.where(df['close'] > sma_h, 1, np.where(df['close'] < sma_l, -1, 0))
        df['d'] = df['c'].replace(0, np.nan).ffill().fillna(1)
        df['ssl_up'], df['ssl_down'] = np.where(df['d'] == 1, sma_h, sma_l), np.where(df['d'] == 1, sma_l, sma_h)
        
        df['sma_short'] = df.ta.sma(length=strat_params.get('sma_short_len', 5))
        df['sma_long'] = df.ta.sma(length=strat_params.get('sma_long_len', 20))
        df['ema_10'] = df.ta.ema(length=10)
        
        df['sma_50'] = df.ta.sma(length=50)
        df['std_50'] = df['close'].rolling(window=50).std()
        df['z_score'] = (df['close'] - df['sma_50']) / (df['std_50'] + 0.0001)

        if btc_df is not None and isinstance(btc_df, pd.DataFrame) and not btc_df.empty:
            df['rs'] = ((df['close'].pct_change() - btc_df['close'].pct_change()) * 100).fillna(0)
        else: 
            df['rs'] = 0

        return df.iloc[-2], df.iloc[-1]
    except Exception as e:
        logging.error(f"TA 연산 중 스레드 오류: {e}")
        return None, None

INDICATOR_CACHE, INDICATOR_CACHE_SEC = {}, 60
OHLCV_CACHE = {} 
BALANCE_CACHE, BALANCE_CACHE_SEC = {"data": None, "timestamp": 0}, 10

async def get_indicators(ticker):
    global INDICATOR_CACHE, OHLCV_CACHE
    now = time.time()
    async with INDICATOR_CACHE_LOCK:
        if ticker in INDICATOR_CACHE and (now - INDICATOR_CACHE[ticker][0] < INDICATOR_CACHE_SEC):
            return INDICATOR_CACHE[ticker][1], INDICATOR_CACHE[ticker][2]
    try:
        await asyncio.sleep(0.25) # 🟢 [FIX: API 보호용 미세 딜레이]
        async with OHLCV_CACHE_LOCK:
            cached = OHLCV_CACHE.get(ticker)
        if cached is None:
            df = await execute_upbit_api(pyupbit.get_ohlcv, ticker, interval=STRAT.get('interval', 'minute15'), count=200)
            if df is None or df.empty: return None, None
            async with OHLCV_CACHE_LOCK: OHLCV_CACHE[ticker] = df
        else:
            new_df = await execute_upbit_api(pyupbit.get_ohlcv, ticker, interval=STRAT.get('interval', 'minute15'), count=3)
            if new_df is not None and not new_df.empty:
                df = pd.concat([cached, new_df])
                df = df[~df.index.duplicated(keep='last')]
                df.sort_index(inplace=True)
                async with OHLCV_CACHE_LOCK: OHLCV_CACHE[ticker] = df.tail(200)
            async with OHLCV_CACHE_LOCK: df = OHLCV_CACHE[ticker]

        async with OHLCV_CACHE_LOCK: 
            btc_df = OHLCV_CACHE.get("KRW-BTC")
        
        # Type validation: ensure df and btc_df are DataFrames before operations
        if not isinstance(df, pd.DataFrame) or df.empty:
            return None, None
        if btc_df is not None and not isinstance(btc_df, pd.DataFrame):
            btc_df = None
            
        # 스레드 충돌을 막기 위해 데이터프레임의 복사본(copy)을 떠서 넘깁니다.
        df_copy = df.copy(deep=True)
        btc_copy = btc_df.copy(deep=True) if btc_df is not None else None
        
        # ✨ 마법의 한 줄: CPU를 혹사시키는 계산 작업을 별도의 백그라운드 스레드로 던집니다.
        prev_data, curr_data = await asyncio.to_thread(_calculate_ta_indicators, df_copy, btc_copy, STRAT)
        
        if prev_data is None or curr_data is None:
            return None, None
            
        INDICATOR_CACHE[ticker] = (now, prev_data, curr_data)
        return prev_data, curr_data
        
    except Exception as e: 
        logging.error(f"지표 계산 실패 ({ticker}): {e}")
        return None, None

# 🟢 [FIX: 거시 트렌드 스캔 시 API 병목(Rate Limit)을 막기 위한 MTF 캐싱]
async def get_mtf_trend(ticker):
    global MTF_CACHE
    now = time.time()
    if ticker in MTF_CACHE and (now - MTF_CACHE[ticker]['time'] < MTF_CACHE_SEC):
        return MTF_CACHE[ticker]['trend']

    try:
        await asyncio.sleep(0.05)
        df_1h = await execute_upbit_api(pyupbit.get_ohlcv, ticker, interval="minute60", count=30)
        df_4h = await execute_upbit_api(pyupbit.get_ohlcv, ticker, interval="minute240", count=30)
        
        if df_1h is None or df_1h.empty or df_4h is None or df_4h.empty: return "알수없음"

        ema20_1h = df_1h.ta.ema(length=20).iloc[-1]
        macd_4h = df_4h.ta.macd(fast=12, slow=26, signal=9)
        macd_hist_4h = macd_4h[macd_4h.columns[1]].iloc[-1] if macd_4h is not None else 0

        trend_1h = "상승(EMA20 위)" if df_1h['close'].iloc[-1] > ema20_1h else "하락/횡보"
        trend_4h = "강세(MACD>0)" if macd_hist_4h > 0 else "약세(MACD<0)"
        
        result = f"4H {trend_4h} / 1H {trend_1h}"
        MTF_CACHE[ticker] = {'time': now, 'trend': result}
        return result
    except Exception as e:
        logging.error(f"MTF 분석 실패 ({ticker}): {e}")
        return "알수없음"

BTC_SHORT_CACHE = {"data": {"trend": "알수없음", "volatility_pct": 0.0, "is_risky": False}, "timestamp": 0}

async def get_btc_short_term_data():
    global BTC_SHORT_CACHE
    if time.time() - BTC_SHORT_CACHE['timestamp'] < 15: return BTC_SHORT_CACHE['data']
        
    try:
        df_btc = await execute_upbit_api(pyupbit.get_ohlcv, "KRW-BTC", interval="minute15", count=200)
        if df_btc is None or df_btc.empty: return BTC_SHORT_CACHE['data']

        async with OHLCV_CACHE_LOCK: OHLCV_CACHE["KRW-BTC"] = df_btc

        avg_range = (df_btc['high'].iloc[-3:] - df_btc['low'].iloc[-3:]).mean()
        current_price = df_btc['close'].iloc[-1]
        volatility_pct = (avg_range / current_price) * 100 if current_price > 0 else 0.0

        if df_btc['close'].iloc[-1] > df_btc['close'].iloc[-2] and df_btc['close'].iloc[-2] > df_btc['close'].iloc[-3]: trend = "단기 상승"
        elif df_btc['close'].iloc[-1] < df_btc['close'].iloc[-2] and df_btc['close'].iloc[-2] < df_btc['close'].iloc[-3]: trend = "단기 하락"
        else: trend = "혼조세"
        
        btc_vol_threshold = STRAT.get('btc_short_term_vol_threshold', 0.5) 
        is_risky = (volatility_pct >= btc_vol_threshold) and ("하락" in trend)

        BTC_SHORT_CACHE['data'] = {"trend": trend, "volatility_pct": round(volatility_pct, 2), "is_risky": is_risky}
        BTC_SHORT_CACHE['timestamp'] = time.time()
        return BTC_SHORT_CACHE['data']
    except Exception as e:
        logging.error(f"Error occurred while fetching BTC short-term data: {e}")
        return BTC_SHORT_CACHE['data']

def check_correlation_risk(new_ticker, held_tickers):
    if not held_tickers: return False
    try:
        new_df = OHLCV_CACHE.get(new_ticker)
        if new_df is None or len(new_df) < 20: return False
        
        for h_ticker in held_tickers:
            h_df = OHLCV_CACHE.get(h_ticker)
            if h_df is not None and len(h_df) >= 20:
                corr = new_df['close'].tail(20).reset_index(drop=True).corr(h_df['close'].tail(20).reset_index(drop=True))
                if corr >= 0.85: return True 
        return False
    except: return False

def is_highly_correlated(t1, t2):
    try:
        df1 = OHLCV_CACHE.get(t1)
        df2 = OHLCV_CACHE.get(t2)
        if df1 is not None and df2 is not None and len(df1) >= 20 and len(df2) >= 20:
            corr = df1['close'].tail(20).reset_index(drop=True).corr(df2['close'].tail(20).reset_index(drop=True))
            return corr >= 0.85
        return False
    except: return False

# --- [4. AI 분석 엔진] ---
async def ai_analyze(ticker, data, mode="BUY", no_trade_hours=0.0, win_rate=50.0, recent_wins=None, mtf_trend="알수없음", buy_price=0.0, market_regime=None, ignore_cooldown=False):
    global last_ai_call_time, last_coin_ai_call
    if mode == "BUY" and not ignore_cooldown and (time.time() - last_coin_ai_call.get(ticker, 0)) < 300: return None
    clean_data = robust_clean(data)

    if mode in ("BUY", "POST_BUY_REPORT"):
        if (time.time() - last_coin_ai_call.get(ticker, 0)) < 300: return None
    
    if mode == "OPTIMIZE":
        forbidden_keys = ['tickers', 'max_concurrent_trades', 'interval', 'report_interval_seconds', 'history_win_count', 'history_loss_count', 'exit_plan_guideline']
        allowed_keys = [k for k in STRAT.keys() if k not in forbidden_keys]
        s_count = STRAT.get('success_reference_count', 8)
        f_count = STRAT.get('failure_reference_count', 8)
        
        if 'indicator_weights' not in allowed_keys: allowed_keys.append('indicator_weights')
        if 'scoring_modifiers' not in allowed_keys: allowed_keys.append('scoring_modifiers')
        if 'btc_short_term_vol_threshold' not in allowed_keys: allowed_keys.append('btc_short_term_vol_threshold')
        if 'sleep_depth_threshold' not in allowed_keys: allowed_keys.append('sleep_depth_threshold')
        if 'risk_per_trade' not in allowed_keys: allowed_keys.append('risk_per_trade')
        if 'high_vol_params' not in allowed_keys: allowed_keys.append('high_vol_params')
        if 'mid_vol_params' not in allowed_keys: allowed_keys.append('mid_vol_params')
        if 'major_params' not in allowed_keys: allowed_keys.append('major_params')
        if 'success_reference_count' not in allowed_keys: allowed_keys.append('success_reference_count')
        if 'failure_reference_count' not in allowed_keys: allowed_keys.append('failure_reference_count')


        filtered_strat = {k: STRAT[k] for k in allowed_keys if k in STRAT}

        prompt = f"""
        [C_OPTIMIZE]
        Strategy: Deep Dip / Oversold Mean Reversion (낙폭 과대 역추세 매매)
        WinRate: {win_rate:.1f}% | Regime: {market_regime}
        Current Strategy: {filtered_strat}
        Allowed Keys: {allowed_keys}
        [IMPORTANT RANGES]
        - pass_score_threshold: MUST be between 75 and 85
        - guard_score_threshold: MUST be between 50 and 60
        - sell_score_threshold: MUST be between 30 and 40
        - bonus_mtf_panic_dip: MUST be between 5 and 30
        - bonus_btc_panic_dip: MUST be between 5 and 20
        - deep_scan_interval: MUST be between 900 and 1800
        - success_reference_count, failure_reference_count: MUST be between 5 and 15 (Use smaller values for fast-changing volatile markets, larger for stable regimes)
        
        CRITICAL RULE: You MUST include 'z_score' in BOTH 'trend_active_logic' and 'range_active_logic'. It is the core statistical indicator. Do not drop it.
        
        Success History: {recent_wins[-s_count:] if isinstance(recent_wins, list) else "None"}
        Failure History: {clean_data[-f_count:] if isinstance(clean_data, list) else "None"}
        Mission:
        1. Swap or update indicators in 'trend_active_logic' and 'range_active_logic' to match the current market regime (e.g., Use more oscillators in ranging markets).
        2. Tune indicator_weights, scoring_modifiers, Tier-params, and the FGI V-Curve parameters.
        3. You MUST keep thresholds and bonuses strictly within the [IMPORTANT RANGES].
        Provide ONLY valid JSON.
        """
        
    elif mode == "SELL_REASON":
        prompt = f"""
        [C_SELL_REASON]
        Ticker: {ticker} | Profit: {clean_data.get('p_rate') if isinstance(clean_data, dict) else 'N/A'}% | BTC Change: {clean_data.get('btc_change') if isinstance(clean_data, dict) else 'N/A'}%
        Strategy: Deep Dip / Oversold Mean Reversion (낙폭 과대 역추세 매매).
        Buy Indicators: {clean_data.get('buy_ind') if isinstance(clean_data, dict) else 'N/A'}
        Sell Indicators: {clean_data.get('sell_ind') if isinstance(clean_data, dict) else 'N/A'}
        Actual Sell Reason: {clean_data.get('actual_sell_reason') if isinstance(clean_data, dict) else 'N/A'}
        Mission: Rate the trade performance (0-100) based on our Mean Reversion strategy, and suggest improvements in Korean. Provide JSON.
        CRITICAL: Do NOT simply copy the score mentioned in 'Actual Sell Reason'. Calculate your OWN independent performance rating (0-100) based on the overall trade execution and P/L!
        """
        
    elif mode == "BUY": 
        guideline = STRAT.get('exit_plan_guideline', 'Follow Tier Params.')
        warning_msg = f"🚨 WARNING: {clean_data['warning']}" if (isinstance(clean_data, dict) and clean_data.get('warning')) else ""
        
        prompt = f"""
        [C_BUY]
        Ticker: {ticker} | MTF: {mtf_trend} | Regime: {market_regime}
        Indicators: {clean_data}
        Orderbook Ratio: {clean_data.get('orderbook_imbalance_ratio', 'N/A') if isinstance(clean_data, dict) else 'N/A'}
        Daily Resistance: {clean_data.get('daily_resistance', 'N/A') if isinstance(clean_data, dict) else 'N/A'}원 (Current: {clean_data.get('close', 0) if isinstance(clean_data, dict) else 0:,.0f}원)
        Python Score: {clean_data.get('python_pass_score', 'N/A') if isinstance(clean_data, dict) else 'N/A'}
        Guideline: {guideline}
        {warning_msg}
        Strategy: Deep Dip / Oversold Mean Reversion (낙폭 과대 역추세 매매). 
        Mission: You are the FINAL GATEKEEPER. Evaluate risk/reward and provide JSON. Look for oversold conditions with a strong probability of a technical bounce.
        CRITICAL: Calculate your OWN independent AI Confidence Score (0-100). Do NOT simply copy the Python Score! Weigh the risks against the upside potential. Minor flaws (e.g., slight macro downtrend, imperfect orderbook) are acceptable if the oversold panic is extreme enough. Output "BUY" if the setup offers a favorable risk/reward ratio (AI Score >= 70). Output "SKIP" only if it's a clear value trap or endless falling knife.
        """
        
    elif mode == "POST_BUY_REPORT": 
        warning_msg = f"🚨 WARNING: {clean_data['warning']}" if (isinstance(clean_data, dict) and clean_data.get('warning')) else ""
        
        prompt = f"""
        [C_POST_BUY_REPORT]
        Ticker: {ticker} | MTF: {mtf_trend} | Entry Price: {buy_price:,.0f}원
        Indicators: {clean_data}
        {warning_msg}
        Situation: Python Sniper-mode preemptive purchase based on 'Deep Dip / Oversold Mean Reversion' (낙폭 과대 역추세 매매).
        Mission: Re-verify entry quality. Focus on oversold extremes, Bollinger Band deviations, and bounce probability. 
        CRITICAL: Calculate your OWN independent AI Confidence Score (0-100). Do not blindly reject just because it's a downtrend. If it's a endless falling knife with NO bounce potential, decision is SKIP (emergency exit). Otherwise, decision is BUY. Provide JSON.
        """
    else: return None

    if not prompt.strip(): return None 

    for attempt in range(3):
        try:
            if attempt == 0 and mode != "POST_BUY_REPORT":
                elapsed = time.time() - last_ai_call_time
                if elapsed < GLOBAL_COOLDOWN: await asyncio.sleep(GLOBAL_COOLDOWN - elapsed)
            last_ai_call_time = time.time()
            if mode in ("BUY", "POST_BUY_REPORT"): last_coin_ai_call[ticker] = last_ai_call_time

            res = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content, 
                    model=MODEL_ID, 
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=types.Content(parts=[types.Part(text=AI_SYSTEM_INSTRUCTION)]),
                        temperature=0.1,
                        response_mime_type="application/json"
                    )
                ), 
                timeout=25.0
            )

            try: res_text = res.text
            except ValueError: raise Exception("AI 응답 없음")
            
            if res_text is None: raise Exception("AI 응답 내용 없음")
            
            res_text = re.sub(r'```json\s*', '', res_text)
            res_text = re.sub(r'```\s*', '', res_text)
            
            start = res_text.find('{')
            if start == -1: raise Exception("JSON 형식 못찾음")
            
            depth, end = 0, start
            for i in range(start, len(res_text)):
                if res_text[i] == '{': depth += 1
                elif res_text[i] == '}': depth -= 1
                if depth == 0: end = i; break
            
            if end <= start: raise Exception("불완전 JSON")
            
            raw_json = res_text[start:end+1]
            raw_json = re.sub(r'\\(?![\/"\\bfnrt])', '', raw_json)
            
            res_json = json.loads(raw_json, strict=False)

            if mode == "OPTIMIZE": return res_json
            if mode == "SELL_REASON":
                if not isinstance(res_json, dict): raise Exception("응답이 딕셔너리가 아닙니다.")
                return {
                    "rating": int(res_json.get('rating', 50)),
                    "status": str(res_json.get('status', 'UNKNOWN')).upper(),
                    "reason": str(res_json.get('reason', res_json.get('message', '분석 결과 없음'))),
                    "improvement": str(res_json.get('improvement', '없음'))
                }

            if mode in ("POST_BUY_REPORT", "BUY"):
                score = int(res_json.get('score', 50 if mode == "POST_BUY_REPORT" else 0))
                decision = str(res_json.get('decision', 'SKIP')).upper()
                if mode == "POST_BUY_REPORT" and decision not in ('BUY', 'SKIP'): decision = 'BUY' if score >= 50 else 'SKIP'
                if mode == "BUY" and decision not in ('BUY', 'SKIP'): decision = 'SKIP'
                
                raw_plan = res_json.get('exit_plan', {})
                exit_plan = {
                    "target_atr_multiplier": max(1.0, min(10.0, float(raw_plan.get('target_atr_multiplier', 3.5)))),
                    "stop_loss": max(-5.0, min(-1.5, float(raw_plan.get('stop_loss', -2.0)))), # 최소 -1.5%의 숨통을 틔워줍니다.
                    "atr_mult": max(0.5, min(4.0, float(raw_plan.get('atr_mult', 1.5)))),
                    "timeout": max(2, min(30, int(raw_plan.get('timeout', 8))))
                }
                return {"score": score, "decision": decision, "reason": str(res_json.get('reason', 'N/A')), "exit_plan": exit_plan}
                
        except Exception as e:
            retry_interval = (attempt + 1) * 1.0 
            if attempt < 2: await asyncio.sleep(retry_interval); continue 
            
    if mode == "OPTIMIZE": return None
    if mode == "SELL_REASON": return {"rating": 50, "status": "UNKNOWN", "message": "AI 응답 불가"}
    
    if mode == "BUY": 
        return {"score": 0, "decision": "SKIP", "reason": "🚨 [비상 엔진] API 응답 불가로 안전을 위해 매수 스킵.", "exit_plan": {}}
        
    return {
        "score": 80, 
        "decision": "BUY", 
        "reason": "[비상 엔진] 자동 관리 모드 전환.", 
        "exit_plan": {
            "target_atr_multiplier": 5.5, 
            "stop_loss": -3.5, 
            "atr_mult": 2.0, 
            "timeout": 24
        }
    }

async def ai_self_optimize(trigger="manual"):
    global STRAT, last_auto_optimize_time
    
    if trigger in ("auto", "daily"):
        remaining_cooldown = 3600 - (time.time() - last_auto_optimize_time)
        if remaining_cooldown > 0: return
    
    if trigger == "manual": await send_msg("🧬 <b>마스터 전략(가중치) 수동 최적화 가동 ...</b>")
    elif trigger == "daily": await send_msg("🌅 <b>오전 9시 일일 결산 빅데이터 최적화 가동 ...</b>")
    elif trigger == "auto": await send_msg("🚨 <b>자동 트리거 최적화 가동</b>")
    
    win_rate, _, _, _, recent_wins, recent_losses = await get_performance_stats_db()
    regime = await get_market_regime() 
    
    res = await ai_analyze(
        "ALL", 
        recent_losses, 
        mode="OPTIMIZE", 
        win_rate=win_rate, 
        recent_wins=recent_wins, 
        no_trade_hours=24.0, 
        market_regime=regime
    )
    
    changes = []
    if res and 'strategy' in res:
        new_data = res['strategy']
        
        def enforce_indicator_count(logic_list, default_logic):
            valid_list = [x for x in logic_list if x in VALID_INDICATORS]
            if len(valid_list) < 5:
                for d in default_logic:
                    if d not in valid_list:
                        valid_list.append(d)
                        if len(valid_list) >= 5: break
            return valid_list[:7]

        if 'trend_active_logic' in new_data: 
            default_trend = ['supertrend', 'macd', 'volume', 'bollinger', 'obv','z_score']
            valid_trend = enforce_indicator_count(new_data['trend_active_logic'], default_trend)
            old_trend = STRAT.get('trend_active_logic', [])
            
            # 🟢 구성물 집합(set)이 완전히 다를 때만 업데이트를 진행합니다.
            if set(old_trend) != set(valid_trend):
                added = [x for x in valid_trend if x not in old_trend]
                removed = [x for x in old_trend if x not in valid_trend]
                msg_parts = []
                if added: msg_parts.append(f"추가[{', '.join(added)}]")
                if removed: msg_parts.append(f"제외[{', '.join(removed)}]")
                if msg_parts: changes.append(f"• 🚀 <b>강추세 지표</b>: {' / '.join(msg_parts)}")
                STRAT['trend_active_logic'] = valid_trend
                
        if 'range_active_logic' in new_data: 
            default_range = ['rsi', 'stochastics', 'vwap', 'ssl_channel', 'atr_trend']
            valid_range = enforce_indicator_count(new_data['range_active_logic'], default_range)
            old_range = STRAT.get('range_active_logic', [])
            if set(old_range) != set(valid_range):
                added = [x for x in valid_range if x not in old_range]
                removed = [x for x in old_range if x not in valid_range]
                msg_parts = []
                if added: msg_parts.append(f"추가[{', '.join(added)}]")
                if removed: msg_parts.append(f"제외[{', '.join(removed)}]")
                if msg_parts: changes.append(f"• 🌊 <b>횡보장 지표</b>: {' / '.join(msg_parts)}")
                STRAT['range_active_logic'] = valid_range

        if 'indicator_weights' in new_data:
            current_weights = STRAT.get('indicator_weights', {})
            raw_new_weights = new_data['indicator_weights']
            active_indicators = set(STRAT.get('trend_active_logic', []) + STRAT.get('range_active_logic', []))
            clamped_weights = {}
            for ind in active_indicators:
                val = raw_new_weights.get(ind, current_weights.get(ind, 1.0))
                clamped_weights[ind] = max(0.5, min(2.0, float(val)))
            if current_weights != clamped_weights:
                weight_changes = []
                for k, v in clamped_weights.items():
                    old_v = current_weights.get(k, 1.0) 
                    if old_v != v: weight_changes.append(f"{k}({old_v}→{v})")
                if weight_changes: changes.append(f"• ⚖️ <b>가중치 조정</b>: {', '.join(weight_changes)}")
                STRAT['indicator_weights'] = clamped_weights
                
        if 'scoring_modifiers' in new_data:
            current_mods = STRAT.get('scoring_modifiers', {})
            raw_mods = new_data['scoring_modifiers']
            clamped_mods = {}
            mod_changes = []
            
            valid_classic_mods = [
                'bonus_golden_combo', 'bonus_mtf_panic_dip', 'bonus_btc_panic_dip',
                'bonus_st_oversold_bounce', 'penalty_st_downtrend', 'penalty_rs_weakness'
            ]
            
            for mk in valid_classic_mods:
                val = raw_mods.get(mk, current_mods.get(mk))
                if val is None: continue
                
                try: mv = int(val)
                except: mv = current_mods.get(mk, 0)
                
                if mk == 'bonus_golden_combo': clamped_mods[mk] = max(20, min(50, mv))
                elif mk == 'bonus_mtf_panic_dip': clamped_mods[mk] = max(5, min(30, mv)) 
                elif mk == 'bonus_btc_panic_dip': clamped_mods[mk] = max(5, min(20, mv)) 
                elif mk == 'bonus_st_oversold_bounce': clamped_mods[mk] = max(5, min(20, mv))
                elif mk == 'penalty_st_downtrend': clamped_mods[mk] = max(-30, min(-5, mv))
                elif mk == 'penalty_rs_weakness': clamped_mods[mk] = max(-40, min(-10, mv))
                
                old_mv = current_mods.get(mk, "N/A")
                if old_mv != clamped_mods[mk]:
                    mod_changes.append(f"{mk}({old_mv}→{clamped_mods[mk]})")
                    
            if mod_changes:
                changes.append(f"• 🧮 <b>점수 가감 스위치 조정</b>: {', '.join(mod_changes)}")
                STRAT['scoring_modifiers'] = clamped_mods

        new_guideline = res.get('exit_plan_guideline')
        if new_guideline and STRAT.get('exit_plan_guideline') != new_guideline:
            changes.append(f"• 📜 작전 지침: <b>{str(new_guideline).replace('<', '&lt;').replace('>', '&gt;')}</b>")
            STRAT['exit_plan_guideline'] = new_guideline

        tier_keys = ['high_vol_params', 'mid_vol_params', 'major_params']
        tier_updated = False
        
        for tk in tier_keys:
            if tk in new_data:
                old_p = STRAT.get(tk, {})
                new_p = new_data[tk]
                
                if isinstance(new_p, dict):
                    updated_p = {
                        "target_atr_multiplier": float(new_p.get("target_atr_multiplier", old_p.get("target_atr_multiplier", 3.0))),
                        "stop_loss": float(new_p.get("stop_loss", old_p.get("stop_loss", -2.0))),
                        "atr_mult": float(new_p.get("atr_mult", old_p.get("atr_mult", 2.0))),
                        "timeout_candles": int(new_p.get("timeout_candles", old_p.get("timeout_candles", 5))),
                        "adaptive_breakeven_buffer": max(0.001, min(0.005, float(new_p.get("adaptive_breakeven_buffer", old_p.get("adaptive_breakeven_buffer", 0.003))))),
                        "adx_strong_trend_threshold": float(new_p.get("adx_strong_trend_threshold", old_p.get("adx_strong_trend_threshold", 25.0)))
                    }
                    if old_p != updated_p:
                        STRAT[tk] = updated_p
                        tier_updated = True

        if tier_updated:
            table_str = "• 📊 <b>티어 파라미터 (Params)</b>\n"
            table_str += "<pre>Tier |  SL  | TAM |  ABB  | ASTH | ADX\n"
            table_str += "----------------------------------------\n"
            for tk, name in zip(tier_keys, ['High ', 'Mid  ', 'Major']):
                p = STRAT.get(tk, {})
                sl = p.get('stop_loss', 0)
                tam = p.get('target_atr_multiplier', 0)
                abb = p.get('adaptive_breakeven_buffer', 0)
                asth = p.get('atr_mult', 0)
                adx = p.get('adx_strong_trend_threshold', 25)
                table_str += f"{name}|{sl:>5.1f} |{tam:>4.1f} | {abb:.3f} | {asth:>4.1f} | {adx:>3.0f}\n"
            table_str += "</pre>"
            changes.append(table_str)

        ignore_list = ['trend_active_logic', 'range_active_logic', 'active_logic', 'exit_plan_guideline', 'indicator_weights', 'scoring_modifiers', 'high_vol_params', 'mid_vol_params', 'major_params', 'tickers', 'max_concurrent_trades', 'interval', 'report_interval_seconds', 'deep_scan_interval']
        
        for k, v in new_data.items():
            if k in STRAT and k not in ignore_list:
                try:
                    if 'mult' in k or 'dev' in k: v = max(0.5, min(5.0, float(v)))
                    elif 'len' in k: v = max(3, min(200, int(v)))
                    elif k == 'fgi_v_curve_bottom': v = max(40.0, min(80.0, float(v)))
                    elif k == 'fgi_v_curve_max': v = max(2.0, min(5.0, float(v)))
                    elif k == 'fgi_v_curve_min': v = max(0.1, min(1.0, float(v)))
                    elif k == 'fgi_v_curve_greed_max': v = max(1.0, min(2.5, float(v)))
                    elif k == 'deep_scan_interval': v = max(900, min(1800, int(v)))
                    elif k == 'pass_score_threshold': v = max(70, min(80, int(v)))  
                    elif k == 'guard_score_threshold': v = max(50, min(60, int(v))) 
                    elif k == 'sell_score_threshold': v = max(30, min(40, int(v)))  
                    elif k == 'rsi_low_threshold': v = max(25.0, min(45.0, float(v)))
                    elif k == 'rsi_high_threshold': v = max(55.0, min(80.0, float(v)))
                    elif k == 'btc_short_term_vol_threshold': v = max(0.5, min(2.0, float(v)))
                    elif k == 'sleep_depth_threshold': v = max(0, min(1000000000, int(v)))
                    elif k == 'success_reference_count': v = max(5, min(15, int(v)))
                    elif k == 'failure_reference_count': v = max(5, min(15, int(v)))
                except: continue 
                if STRAT[k] != v: 
                    changes.append(f"• {k}: {STRAT[k]} → <b>{v}</b>")
                    STRAT[k] = v
                
        conf['strategy'] = STRAT; save_config(conf, CONFIG_PATH)
        ai_reason = str(res.get('reason', 'N/A')).replace('<', '&lt;').replace('>', '&gt;')
        if changes: await send_msg(f"✨ <b>클래식 전략 진화 완료 </b>\n\n" + "\n".join(changes) + f"\n\n💡 <b>AI:</b>\n{ai_reason}")
        else: await send_msg("🧬 <b>최적화 유지</b> (변경 없음)") 
        if trigger in ("auto", "daily"): last_auto_optimize_time = time.time()
    else: await send_msg("🧬 <b>최적화 실패 또는 AI 응답 없음</b>") 

# 👇 [개선 로직] 3번 실패 시 잔여 물량 강제 시장가 청산 로직 탑재
async def execute_smart_sell(ticker, qty, current_price, urgency="NORMAL"):
    if urgency == "HIGH" or (qty * current_price) < 6000:
        await execute_upbit_api(upbit.sell_market_order, ticker, qty)
        return
        
    remaining_qty = qty
    for i in range(3): 
        if remaining_qty * current_price < 6000:
            await execute_upbit_api(upbit.sell_market_order, ticker, remaining_qty); break
        orderbook = await execute_upbit_api(pyupbit.get_orderbook, ticker)
        if not orderbook: break
        best_bid = orderbook['orderbook_units'][0]['bid_price'] 
        res = await execute_upbit_api(upbit.sell_limit_order, ticker, best_bid, remaining_qty)
        if not res or 'uuid' not in res:
            await execute_upbit_api(upbit.sell_market_order, ticker, remaining_qty); break
            
        uuid = res['uuid']
        await asyncio.sleep(1.5) 
        
        order_info = await execute_upbit_api(upbit.get_order, uuid)
        if order_info and isinstance(order_info, dict):
            if order_info.get('state') == 'wait':
                await execute_upbit_api(upbit.cancel_order, uuid)
                await asyncio.sleep(0.5) 
                
                # 🟢 취소 후 최종 체결량 확실히 업데이트
                final_order = await execute_upbit_api(upbit.get_order, uuid)
                exec_vol = float(final_order.get('executed_volume', 0)) if final_order else 0
                remaining_qty -= exec_vol
            else:
                break # 완전히 체결됨
        else: break 

    # 💣 [핵심 방어] 루프가 끝났는데도 안 팔린 잔여 물량이 있다면 무조건 시장가로 던져서 고아 코인(Orphan) 방지!
    if remaining_qty > 0:
        balances = await execute_upbit_api(upbit.get_balances)
        if isinstance(balances, list):
            coin_currency = ticker.split('-')[1]
            coin_info = next((b for b in balances if b['currency'] == coin_currency), None)
            if coin_info:
                actual_rem = float(coin_info['balance']) + float(coin_info['locked'])
                if actual_rem * current_price >= 5000:
                    await execute_upbit_api(upbit.sell_market_order, ticker, actual_rem)

async def execute_smart_buy(ticker, buy_amt, limit_price_threshold):
    orderbook = await execute_upbit_api(pyupbit.get_orderbook, ticker)
    if not orderbook: return False
    total_bid, total_ask = orderbook['total_bid_size'], orderbook['total_ask_size']
    if total_bid == 0 or total_ask == 0: return False
    
    imbalance_ratio = total_ask / total_bid
    if imbalance_ratio > 5.0 or imbalance_ratio < 0.2:
        await send_msg(f"⚠️ <b>휩소 필터링</b>: {ticker} 호가창 불균형")
        return False

    remaining_amt = buy_amt
    for attempt in range(3):
        if remaining_amt < 6000: break
        ob = await execute_upbit_api(pyupbit.get_orderbook, ticker)
        if not ob: break
        best_ask = ob['orderbook_units'][0]['ask_price']
        if best_ask > limit_price_threshold: break
        buy_qty = remaining_amt / best_ask
        res = await execute_upbit_api(upbit.buy_limit_order, ticker, best_ask, buy_qty)
        if not res or 'uuid' not in res: break
        uuid = res['uuid']
        await asyncio.sleep(1.0) 
        order_info = await execute_upbit_api(upbit.get_order, uuid)
        if order_info and order_info.get('state') == 'wait':
            await execute_upbit_api(upbit.cancel_order, uuid)
            await asyncio.sleep(0.5)
            exec_vol = float(order_info.get('executed_volume', 0))
            remaining_amt -= (exec_vol * best_ask)
        else:
            remaining_amt = 0; break
    return True if (buy_amt - remaining_amt) >= 6000 else False

async def background_ai_post_report(ticker, curr_data, mtf, buy_price, pass_score):
    global trade_data
    await asyncio.sleep(1.0) 
    regime = await get_market_regime()
    wr, _, _, _, _, _ = await get_performance_stats_db()
    
    curr_data_dict = curr_data if isinstance(curr_data, dict) else curr_data.to_dict()
    ai_res = await ai_analyze(ticker, curr_data_dict, mode="POST_BUY_REPORT", mtf_trend=mtf, buy_price=buy_price, market_regime=regime, win_rate=wr)
    if not isinstance(ai_res, dict): ai_res = ai_res or {}

    if ticker in trade_data:
        t = trade_data[ticker]
        safe_reason = str(ai_res.get('reason', '')).replace('<', '&lt;').replace('>', '&gt;')
        score = ai_res.get('score', 50)
        decision = ai_res.get('decision', 'SKIP')
        
        if decision == 'SKIP' or score < 50:
            await send_msg(f"🚨 <b>AI 긴급 철수 발령</b>: {ticker} 위험 감지!\n👉 <b>최소 손실 탈출 모드로 전환합니다!</b>")
            t['exit_plan'] = {'target_atr_multiplier': 1.0, 'stop_loss': -0.7, 'atr_mult': 0.5, 'timeout': 2}
        else:
            t['exit_plan'] = ai_res.get('exit_plan', {})
            await send_msg(f"📝 <b>AI 사후 결재 (스나이퍼)</b>: {ticker} (파이썬:{pass_score}점 ➡️ AI:{score}점)\n- 작전: {t['exit_plan']}\n- 코멘트: {safe_reason}")
            
        t['buy_reason'] = f"[스나이퍼 선제공격] {safe_reason}"
        TRADE_DATA_DIRTY = True

# --- [5. 공통 스캔 모듈] ---
async def process_buy_order(ticker, score, reason, curr_data, total_asset, cash, held_count, exit_plan, buy_mode="COUNCIL", pass_score=0):
    global last_buy_time, trade_data
    
    max_trades = STRAT.get('max_concurrent_trades', 5) 
    if held_count >= max_trades: return False

    risk_pct = STRAT.get('risk_per_trade', 2.0) / 100.0
    atr_pct = (curr_data['ATR'] / curr_data['close']) if curr_data['close'] > 0 else 0.01
    atr_pct = max(0.005, atr_pct) 
    
    risk_parity_amt = (total_asset * risk_pct) / atr_pct
    max_slot_amt = (total_asset / max_trades) * 1.2

    
    buy_amt = min(risk_parity_amt, max_slot_amt, cash * 0.99)
    if (cash * 0.99) - buy_amt < 6000: buy_amt = cash * 0.99
        
    if buy_amt >= 6000: 
        expected_slippage = await calculate_expected_slippage(ticker, buy_amt)
        if expected_slippage > STRAT.get('max_slippage_pct', 0.3):
            score -= STRAT.get('slippage_penalty_score', 20)
            await send_msg(f"⚠️ <b>[슬리피지 경고]</b> {ticker} 예상 체결 오차 {expected_slippage:.2f}%! 점수 차감.")
            if score < STRAT.get('pass_score_threshold', 60):
                await send_msg(f"🚫 <b>매수 취소</b>: {ticker} 슬리피지로 인한 펀더멘탈 점수 미달 ({score}점).")
                return False

        max_tolerable_price = curr_data['close'] * 1.005 
        buy_success = await execute_smart_buy(ticker, buy_amt, max_tolerable_price)
        
        if buy_success:
            # 🟢 [FIX: 실제 체결가(평단가) 확인. 바로 현재가(current_price)로 때려박으면 트레일링 스탑이 꼬임]
            await asyncio.sleep(1.5) # 잔고 갱신 대기
            current_balances = await execute_upbit_api(upbit.get_balances)
            coin_currency = ticker.split('-')[1]
            coin_info = next((b for b in current_balances if b['currency'] == coin_currency), None)
            
            if isinstance(current_balances, list):
                # 🟢 [Pylance 방어] isinstance(b, dict) 추가 및 직접 접근 방지
                coin_info = next((b for b in current_balances if isinstance(b, dict) and b.get('currency') == coin_currency), None)
            else:
                coin_info = None
            
            if coin_info and safe_float(coin_info.get('avg_buy_price')) > 0:
                final_buy_price = safe_float(coin_info.get('avg_buy_price'))
            else:
                final_buy_price = safe_float(await execute_upbit_api(pyupbit.get_current_price, ticker))

            now_ts = time.time()
            last_buy_time[ticker], last_global_buy_time = now_ts, now_ts
            
            temp_exit_plan = exit_plan if exit_plan else {"target_atr_multiplier": 5.5, "stop_loss": -3.5, "atr_mult": 2.0, "timeout": 24}
            
            tier_params = get_coin_tier_params(ticker, curr_data)
            
            if exit_plan:
                temp_exit_plan = exit_plan  
            else:
                temp_exit_plan = {
                    "target_atr_multiplier": tier_params.get('target_atr_multiplier', 4.5),
                    "stop_loss": tier_params.get('stop_loss', -3.0),
                    "atr_mult": tier_params.get('atr_mult', 2.0),
                    "timeout": tier_params.get('timeout_candles', 8)
                }
            
            temp_exit_plan['adaptive_breakeven_buffer'] = tier_params.get('adaptive_breakeven_buffer', 0.003)

            buy_ind_dict = curr_data if isinstance(curr_data, dict) else curr_data.to_dict()

            trade_data[ticker] = {
                'high_p': final_buy_price, 'entry_atr': curr_data.get('ATR', 0), 'guard': False,
                'buy_ind': buy_ind_dict, 
                'last_notified_step': 0, 'buy_ts': now_ts,
                'exit_plan': temp_exit_plan, 'buy_reason': reason, 'btc_buy_price': REALTIME_PRICES.get('KRW-BTC', 0),
                'pass_score': pass_score, 'is_runner': False, 'score_history': [pass_score]
            }
            TRADE_DATA_DIRTY = True
            await record_trade_db(ticker, 'BUY', final_buy_price, buy_amt, profit_krw=0, reason=reason, status="ENTERED", rating=int(score), pass_score=pass_score)        
            
            if buy_mode == "SNIPER":
                await send_msg(f"🎯 <b>스나이퍼 선제 매수 완료</b>: {ticker} (파이썬:{pass_score}점)\n- <b>매수 금액: {buy_amt:,.2f}원</b>\n👉 <b>사후 결재 대기중.</b>")
                mtf = await get_mtf_trend(ticker)
                asyncio.create_task(background_ai_post_report(ticker, curr_data, mtf, final_buy_price,pass_score))
            else:
                safe_reason = str(reason).replace('<', '&lt;').replace('>', '&gt;')
                await send_msg(f"✅ <b>참모회의 매수 승인</b>: {ticker} (파이썬:{pass_score}점 ➡️ AI:{score}점)\n- <b>매수 금액: {buy_amt:,.2f}원</b>\n- 분석: {safe_reason}")
            return True
        else:
            await send_msg(f"🚫 <b>매수 취소</b>: {ticker} 스마트 매수 실패.")
    return False

async def run_full_scan(is_deep_scan=False):
    global last_sell_time, consecutive_empty_scans, last_global_buy_time, SYSTEM_STATUS, LATEST_TOP_PASS_SCORE 
    
    new_status = "🟢 정상 감시 중"
    
    try:
        ob_btc = await execute_upbit_api(pyupbit.get_orderbook, "KRW-BTC")
        if isinstance(ob_btc, dict) and 'orderbook_units' in ob_btc:
            orderbook_units = ob_btc.get('orderbook_units', [])
            if isinstance(orderbook_units, list) and len(orderbook_units) > 0:
                # Validate each unit is a dict with required keys before calculation
                valid_units = [u for u in orderbook_units[:5] if isinstance(u, dict) and 'ask_size' in u and 'ask_price' in u and 'bid_size' in u and 'bid_price' in u]
                if valid_units:
                    # 🟢 [수정 1] 호가창 연산 시 safe_float 적용
                    total_depth_krw = sum((safe_float(u.get('ask_size')) * safe_float(u.get('ask_price'))) + (safe_float(u.get('bid_size')) * safe_float(u.get('bid_price'))) for u in valid_units)
                    
                    if total_depth_krw < STRAT.get('sleep_depth_threshold', 1000000000):
                        new_status = f"🟡 휴식 (호가창 얇음: {total_depth_krw/100000000:.1f}억)"
                        SYSTEM_STATUS = new_status
                        if is_deep_scan: 
                            await send_msg(f"💤 <b>[시장 유동성 고갈]</b> 비트코인 5호가 총액이 {total_depth_krw/100000000:.1f}억 원으로 매우 얇습니다. 스캔을 쉬어갑니다.")
                            last_global_buy_time = time.time()
                            return
                        else:
                            await send_msg(f"⚠️ 유동성 부족 상태({total_depth_krw/100000000:.1f}억)이나, <b>수동 명령이므로 스캔을 강행합니다!</b>")
    except: pass

    balances = await execute_upbit_api(upbit.get_balances)
    if not isinstance(balances, list): return

    cash = safe_float(next((b.get('balance') for b in balances if isinstance(b, dict) and b.get('currency') == "KRW"), 0.0))
    
    held_dict = {
        f"KRW-{b.get('currency')}": safe_float(b.get('avg_buy_price')) 
        for b in balances 
        if isinstance(b, dict) and b.get('currency') and b.get('currency') != "KRW" 
        and (safe_float(b.get('balance')) + safe_float(b.get('locked'))) * safe_float(b.get('avg_buy_price')) >= 5000
    }
    
    # 🟢 [수정 2] 총 자산(total_asset) 계산 시 구형 float() 로직을 safe_float으로 교체
    total_asset = cash
    for b in balances:
        if isinstance(b, dict) and b.get('currency') and b.get('currency') != "KRW":
            ticker = f"KRW-{b.get('currency')}"
            avg_p = safe_float(b.get('avg_buy_price'))
            p = safe_float(REALTIME_PRICES.get(ticker, avg_p))
            
            qty = safe_float(b.get('balance')) + safe_float(b.get('locked'))
            total_asset += qty * p

    can_buy = True
    if cash < 6000 or len(held_dict) >= STRAT.get('max_concurrent_trades', 5):
        new_status = "⏳ 매수 대기 (슬롯/현금 부족)"
        last_global_buy_time = time.time() 
        can_buy = False
        if not is_deep_scan:
            await send_msg("⚠️ <b>매수 중단</b>: 슬롯이 꽉 찼거나 가용 현금(6,000원 미만)이 부족합니다.")

    btc_short = await get_btc_short_term_data() 
    regime = await get_market_regime() 
    
    if btc_short['is_risky'] or (btc_short['trend'] == "단기 하락" and "Extreme Fear" in regime.get('fear_and_greed', '')):
        new_status = "🔥 사냥 (BTC 폭락장/과매도 탐색)"
        SYSTEM_STATUS = new_status
        if is_deep_scan: 
            await send_msg("🔥 <b>[사냥 모드 작동]</b> 비트코인 급락 및 투심 악화! 클래식 엔진이 낙폭 과대 종목 사냥을 시작합니다.")
    else:
        SYSTEM_STATUS = new_status
        
    if is_deep_scan:
        if consecutive_empty_scans >= 3:
            await send_msg(f"⏳ <b>[{consecutive_empty_scans + 1}회 연속 관망]</b> 시장에 기준을 충족하는 타점이 없습니다. 안전하게 대기합니다.")
        else: 
            await send_msg(f"⏰ <b>{consecutive_empty_scans + 1}번째</b> 클래식 정규 스캔 중...")
        await update_top_volume_tickers()

    last_global_buy_time = time.time() 
    wr, _, _, _, _, _ = await get_performance_stats_db() 
    
    python_passed = []
    current_loop_max_score = -999 
    
    score_mods = STRAT.get('scoring_modifiers', {})
    b_golden = score_mods.get('bonus_golden_combo', 35)
    b_mtf_panic = score_mods.get('bonus_mtf_panic_dip', 15)
    b_btc_panic = score_mods.get('bonus_btc_panic_dip', 10)
    b_st_bounce = score_mods.get('bonus_st_oversold_bounce', 10)
    p_st_down = score_mods.get('penalty_st_downtrend', -15)
    p_rs_weak = score_mods.get('penalty_rs_weakness', -20)

    # 한 번에 최대 4개의 코인만 동시에 API를 호출하도록 락(Lock)을 걸어 Rate Limit(429 에러)을 완벽 방어합니다.
    scan_semaphore = asyncio.Semaphore(4) 

    async def fetch_data(ticker):
        async with scan_semaphore:
            p, c = await get_indicators(ticker)
            return ticker, p, c

    # 15~20개 종목의 지표를 동시에(병렬로) 쫙 끌어옵니다!
    fetch_tasks = [fetch_data(t) for t in STRAT['tickers']]
    # 🟢 [Pylance 방어] 병렬 처리 중 하나가 실패해도 전체가 터지지 않게 안전망(return_exceptions) 추가
    indicator_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
    
    # 🟢 [추가 방어] 에러(Exception) 객체로 반환된 결과는 필터링해서 없애버립니다.
    if not isinstance(indicator_results, list):
        indicator_results = []
    
    indicator_results = [res for res in indicator_results if not isinstance(res, Exception)]

    # 가져온 결과값들을 순회하며 기존과 똑같이 점수를 매깁니다.
    for item in indicator_results:
        if not isinstance(item, tuple) or len(item) != 3:
            continue
        t, prev, curr = item
        if curr is None: 
            continue
        
        # Type normalization: convert Series to dict if necessary
        if isinstance(prev, pd.Series):
            prev = prev.to_dict()
        if isinstance(curr, pd.Series):
            curr = curr.to_dict()
        
        # Ensure both are dicts
        if not isinstance(prev, dict) or not isinstance(curr, dict):
            continue
    
        tier_params = get_coin_tier_params(t, curr)
        
        # 🟢 [수정 3] 각종 지표값 추출 시 구형 float() 대신 safe_float() 일괄 적용
        adx_base = STRAT.get('adx_strong_trend_threshold', 25.0)
        adx_threshold = safe_float(tier_params.get('adx_strong_trend_threshold', adx_base), 25.0)
        
        curr_adx = safe_float(curr.get('adx'), 0.0)
        curr_volume = safe_float(curr.get("volume"), 0.0)
        vol_sma_val = safe_float(curr.get("vol_sma"), 0.0001)
        z_score_val = safe_float(curr.get('z_score'), 0.0)
        curr_close = safe_float(curr.get('close'), 0.0)
        
        is_strong_trend = curr_adx > adx_threshold
        
        raw_logic = STRAT.get('trend_active_logic') if is_strong_trend else STRAT.get('range_active_logic')
                        
        # 🟢 [Pylance 방어] 리스트 타입인지 완벽하게 검사합니다.
        if isinstance(raw_logic, list):
            active_logic_list = raw_logic
        else:
            active_logic_list = ['supertrend', 'macd', 'volume', 'bollinger', 'obv', 'z_score'] if is_strong_trend else ['rsi', 'stochastics', 'vwap', 'ssl_channel', 'atr_trend', 'z_score']
                        
        regime = await get_market_regime()
        
        fgi = regime.get('fear_and_greed', '')
        
        try:
            match = re.search(r'\d+', fgi)
            fgi_value = int(match.group()) if match else 50
        except:
            fgi_value = 50  
            
        # 🟢 [수정 4] FGI 변수 추출 시 safe_float() 적용
        v_bottom = safe_float(STRAT.get('fgi_v_curve_bottom'), 70.0)
        v_max = safe_float(STRAT.get('fgi_v_curve_max'), 3.0)
        v_min = safe_float(STRAT.get('fgi_v_curve_min'), 0.5)
        v_greed = safe_float(STRAT.get('fgi_v_curve_greed_max'), 1.5)
            
        if fgi_value <= v_bottom:
            dynamic_fgi_mult = v_max - ((fgi_value / v_bottom) * (v_max - v_min))
        else:
            dynamic_fgi_mult = v_min + (((fgi_value - v_bottom) / (100.0 - v_bottom)) * (v_greed - v_min))
            
        dynamic_fgi_mult = round(dynamic_fgi_mult, 2)
            
        try:
            normalized_fear = (dynamic_fgi_mult - v_min) / (v_max - v_min)
        except ZeroDivisionError:
            normalized_fear = 0.5
        normalized_fear = max(0.0, min(1.0, normalized_fear)) 
        
        rsi_mult = 0.5 + (1.5 * normalized_fear)        
        boll_mult = 1.0 + (0.5 * normalized_fear)       
        st_mult = 1.5 - (1.0 * normalized_fear)         
        vol_mult = 2.0 - (1.0 * normalized_fear)        
        bb_break_mult = 1.5 - (1.0 * normalized_fear)   

        indicator_mults = {
            'rsi': rsi_mult, 'bollinger': boll_mult, 'supertrend': st_mult, 
            'volume': vol_mult, 'bollinger_breakout': bb_break_mult
        }

        weights = STRAT.get('indicator_weights', {})
        
        dynamic_total_weight = 0.0
        earned_weighted_score = 0.0
        
        # (run_full_scan 내부와 main 루프 내부 모두 교체)
        for name in active_logic_list:
            # 🟢 [Pylance 강제 진압] get 메서드 자체에 기본값을 주어 None을 1차 방어하고, 
            # safe_float으로 2차 방어하여 컴파일러의 불만을 완전히 없앱니다.
            w = safe_float(weights.get(name, 1.0), 1.0)
            m = safe_float(indicator_mults.get(name, 1.0), 1.0)
            
            # ❗주의: run_full_scan에서는 아래처럼 curr.get('close')를 쓰시고,
            # main() 감시 루프 쪽에서는 이 줄을 지우고 get_strategy_score에 real_price를 바로 넣으세요!
            close_price = safe_float(curr.get('close', 0.0), 0.0) 
            
            s = safe_float(get_strategy_score(name, prev, curr, close_price), 0.0)
            
            earned_weighted_score += (s * m * w)
            dynamic_total_weight += (m * w)
        
        pass_score = int(earned_weighted_score / dynamic_total_weight) if dynamic_total_weight > 0 else 0
        pass_score = min(100, pass_score)
        
        is_fear = "Fear" in fgi
        is_oversold = curr.get('rsi', 50) < STRAT.get('rsi_low_threshold', 35.0)
        is_mom_turn = False
        if curr is not None and prev is not None:
            is_mom_turn = (curr.get('macd_h_diff', 0) > 0 and prev.get('macd_h_diff', 0) <= 0) or \
                          (curr.get('st_rsi_k', 0) > curr.get('st_rsi_d', 0) and prev.get('st_rsi_k', 0) <= prev.get('st_rsi_d', 0))

        if is_fear and is_oversold and is_mom_turn:
            pass_score += b_golden  
            if is_deep_scan: curr['warning'] = curr.get('warning', '') + f"\n🔥 [골든 콤보 발동] 공포장 속 과매도 턴어라운드 포착! (+{b_golden}점)"

        if btc_short['trend'] == "단기 하락":
            mtf = await get_mtf_trend(t)
            if "4H 약세" in mtf and "1H 하락" in mtf:
                pass_score += b_mtf_panic  
            pass_score += b_btc_panic      
            if is_deep_scan: curr['warning'] = curr.get('warning', '') + f"\n🔥 [사냥 기회] 거시 추세 및 대장주 하락! 낙폭 과대 프리미엄 가산 (+{b_btc_panic + b_mtf_panic}점)."
            
        if curr.get('ST_DIR', 1) == -1:
            if curr.get('rsi', 50) <= STRAT.get('rsi_low_threshold', 35.0):
                pass_score += b_st_bounce
            else: pass_score += p_st_down

        if curr.get('rs', 0) < -2.0:
            pass_score += p_rs_weak
            if is_deep_scan: curr['warning'] = curr.get('warning', '') + f"\n⚠️ [펀더멘탈 경고] 비트코인 대비 심각한 약세(RS < -2.0). 진입 점수 대폭 하향."
        
        if z_score_val <= -2.5:
            pass_score += 20 # 강제 점수 펌핑
            if is_deep_scan: curr['warning'] = curr.get('warning', '') + f"\n🔥 [블랙 스완 포착] Z-Score {z_score_val:.2f} ! 통계적 극단적 패닉셀입니다 (+20점)."
            
        curr_open = safe_float(curr.get("open"), 0.0)
        curr_low = safe_float(curr.get("low"), 0.0)
        
        body = abs(curr_close - curr_open)
        lower_wick = curr_close - curr_low if curr_close > curr_open else curr_open - curr_low
        wick_ratio = lower_wick / (body + 0.0001) 
        
        is_reclaiming_ema = curr_close > curr.get('ema_10', 0) 
        
        # 🟢 거래량 필터 업그레이드: 비율(1.5배) + 절대 대금(최소 2~3억) 동시 만족 요구
        if z_score_val <= -2.5:
            required_vol_ratio = 1.5
        else:
            required_vol_ratio = 2.0
            
        current_candle_krw = curr_volume * curr_close
        min_safety_net_krw = 100000000
            
        is_volume_spiked = (curr_volume > (vol_sma_val * required_vol_ratio)) and (current_candle_krw > min_safety_net_krw)

        # 🟢 치명적 결함 검사
        fatal_flaw = False

        # (1) 투매 구간 방어선
        if curr.get('rsi', 50) < 25.0 and not is_reclaiming_ema:
            fatal_flaw = True
            if is_deep_scan: curr['warning'] = curr.get('warning', '') + "\n⚠️ [투매 지하실 경고] RSI 25 미만 구간이나, 단기 이평선(EMA 10) 회복 전까지 매수 불가."

        # (2) 캔들 패턴 컨펌
        elif not (wick_ratio > 1.5 or is_reclaiming_ema):
            fatal_flaw = True
            if is_deep_scan: curr['warning'] = curr.get('warning', '') + "\n⚠️ [추세 전환 미확인] 밑꼬리 반등(1.5배)이나 이평선 돌파가 확인되지 않음."
            
        # (3) 진짜 거래량 컨펌 (가장 중요)
        elif is_oversold and not is_volume_spiked:
            fatal_flaw = True
            if is_deep_scan: curr['warning'] = curr.get('warning', '') + f"\n⚠️ [가짜 바닥 하드락] 투매를 소화하는 거래량(평소 {required_vol_ratio}배 AND 최소 2억 원 이상)이 터지지 않음."

        # 🟢 최고 점수 기록 (결함으로 깎이기 전 순수 스코어)
        current_loop_max_score = max(current_loop_max_score, pass_score)

        if fatal_flaw: 
            pass_score = -999
            if is_deep_scan: curr["warning"] = curr.get("warning", "") + "\n🚫 [스나이퍼 프리패스 차단] 치명적 결함 발견!"
        
        if pass_score < 0: 
            continue

        min_score_threshold = STRAT.get("min_score", 60)

        # 상황별 점수 임계값 완화
        if is_fear and is_oversold and is_mom_turn: min_score_threshold = min(min_score_threshold, 40)
        if SYSTEM_STATUS == "🔥 사냥": min_score_threshold = min(min_score_threshold, 50)
        if z_score_val <= -2.5: min_score_threshold = min(min_score_threshold, 35)
        if is_volume_spiked: min_score_threshold = min(min_score_threshold, 55)
        if is_oversold: min_score_threshold = min(min_score_threshold, 50)
        if is_reclaiming_ema: min_score_threshold = min(min_score_threshold, 55)
        if is_mom_turn: min_score_threshold = min(min_score_threshold, 55)
        if curr.get("st_rsi_k", 0) > curr.get("st_rsi_d", 0): min_score_threshold = min(min_score_threshold, 50)
        if curr.get("vwap", 0) > curr_close: min_score_threshold = min(min_score_threshold, 55)
        if curr.get("ssl_channel", 0) > curr_close: min_score_threshold = min(min_score_threshold, 55)
        if curr.get("atr_trend", 0) > curr_close: min_score_threshold = min(min_score_threshold, 55)
        if curr.get("obv", 0) > curr.get("prev_obv", 0): min_score_threshold = min(min_score_threshold, 55)

        if pass_score < min_score_threshold:
            continue

        if t in held_dict or (t in last_sell_time and (time.time() - last_sell_time[t]) < 1800): continue
        if (time.time() - last_buy_time.get(t, 0)) < 1800: continue
        if btc_short["is_risky"] and check_correlation_risk(t, ["KRW-BTC"]): continue
        if check_correlation_risk(t, list(held_dict.keys())): continue 
        
        if curr.get("rsi", 50) >= STRAT.get("rsi_high_threshold", 65.0) or curr.get("stoch_k", 50) >= STRAT.get("stoch_k_overbought", 75.0): continue

        base_threshold = STRAT.get("pass_score_threshold", 80)
        
        # 🟢 [수정됨] 스나이퍼 모드 영구 폐지. 모든 1차 통과 종목은 AI 참모회의(False)로 직행
        if pass_score >= base_threshold:
            mtf = await get_mtf_trend(t)
            python_passed.append({"t": t, "score": pass_score, "data": curr, "mtf": mtf, "is_sniper": False})

    LATEST_TOP_PASS_SCORE = current_loop_max_score 
    python_passed.sort(key=lambda x: x['score'], reverse=True)
    python_passed = python_passed[:3]  

    if python_passed:
        report_msg = "🔍 <b>[파이썬 엔진 1차 통과 종목]</b>\n"
        for p in python_passed:
            report_msg += f"• {p['t']} : {p['score']}점 ({'🎯 스나이퍼' if p['is_sniper'] else '⚖️ 참모회의'})\n"
        if not is_deep_scan or can_buy:
            await send_msg(report_msg)
    else:
        if is_deep_scan: 
            await send_msg("🔍 <b>최종 판단</b>: ❌ 적기 종목 없음 (1차 예선 전원 탈락).")
            consecutive_empty_scans += 1
        else:
            await send_msg("🔍 <b>수동 스캔 결과</b>: ❌ 현재 차트 조건(점수)을 만족하는 코인이 하나도 없습니다.")
        return

    if not can_buy:
        if not is_deep_scan: await send_msg("⚠️ <b>매수 대기</b>: 스캔은 완료했으나 가용 현금/슬롯이 부족하여 AI 결재를 생략합니다.")
        return

    ai_approved = []
    ai_rejected = []  # 🟢 AI가 거절한 종목과 사유를 담을 바구니

    for p in python_passed:
        t = p['t']
        if p['is_sniper']:
            ai_approved.append({"t": t, "final_score": p['score'], "decision": "BUY", "reason": "[스나이퍼] 대다수 지표 강력 일치", "exit_plan": None, "data": p['data'], "mode": "SNIPER", "pass_score": p['score']})
        else:
            try:
                ai_data = p['data'].copy() # dictionary 복사
                df_daily = await execute_upbit_api(pyupbit.get_ohlcv, t, interval="day", count=5)
                if df_daily is not None and not df_daily.empty:
                    ai_data['daily_context'] = df_daily.tail(3).to_dict()
                    # 🟢 [수정 6] DataFrame max() 결과가 None일 경우 방어
                    ai_data['daily_resistance'] = safe_float(df_daily['high'].max())
                
                ob = await execute_upbit_api(pyupbit.get_orderbook, t)
                if isinstance(ob, dict) and ob.get('total_bid_size', 0) > 0:
                    imbalance = round(ob['total_ask_size'] / ob['total_bid_size'], 2)
                    ai_data['orderbook_imbalance_ratio'] = f"{imbalance} (설명: 1.0보다 크면 위에서 누르는 매도 압력 위험 / 1.0보다 작으면 바닥을 받치는 매수 방어 안전)"

                if "하락" in p['mtf'] or btc_short['is_risky']:
                    ai_data['warning'] = "🔥 [사냥 모드: 거시 하락장] 패닉셀 진행 중. 단, '거래량 없는 가짜 하락'이나 '반등 모멘텀 부재' 등 중대리스크가 조금이라도 감지된다면 절대 타협하지 말고 즉시 'SKIP'을 선언하세요!"
                    
                ai_data['python_pass_score'] = p['score']
                ana = await ai_analyze(t, ai_data, mode="BUY", ignore_cooldown=True, mtf_trend=p['mtf'], market_regime=regime, win_rate=wr)
                
                if ana and ana['decision'] == "BUY":
                    ai_approved.append({"t": t, "final_score": ana['score'], "decision": "BUY", "reason": ana['reason'], "exit_plan": ana['exit_plan'], "data": p['data'], "mode": "COUNCIL", "pass_score": p['score']})
                elif ana: 
                    ai_rejected.append({"t": t, "reason": ana.get('reason', '사유 없음')})
            except Exception as e: 
                logging.error(f"AI 분석 중 예외 발생 ({t}): {e}")
                ai_rejected.append({"t": t, "reason": "AI 통신/분석 중 에러 발생"}) 

    ai_approved.sort(key=lambda x: x.get('final_score', 0), reverse=True)
    
    reject_msg_str = ""
    if ai_rejected:
        reject_msg_str = "\n\n🚫 <b>[AI 2차 면접 탈락 사유]</b>\n"
        for r in ai_rejected:
            safe_reason = str(r['reason']).replace('<', '&lt;').replace('>', '&gt;')
            reject_msg_str += f"• <b>{r['t']}</b>: {safe_reason}\n"

    if not ai_approved:
        if is_deep_scan:
            await send_msg(f"🤖 <b>[AI 2차 면접 결과]</b>: 전원 탈락 (매수 스킵){reject_msg_str}")
            consecutive_empty_scans += 1  
        else:
            await send_msg(f"🤖 <b>[수동 스캔 결과]</b>: 파이썬은 통과했으나, AI가 위험을 감지하여 전원 탈락시켰습니다.{reject_msg_str}")
        return
    else:
        if ai_rejected:
            await send_msg(f"🤖 <b>[AI 2차 면접 부분 탈락]</b>{reject_msg_str}")

    top_coin = ai_approved[0]
    final_buy_targets = [top_coin]
    skipped_coins = []

    for item in ai_approved[1:]:
        if is_highly_correlated(top_coin['t'], item['t']): skipped_coins.append(item['t'])
        else: final_buy_targets.append(item)

    if skipped_coins: await send_msg(f"🔗 <b>[유사성 필터]</b> 1위({top_coin['t']})와 85% 이상 중복되어 매수 취소: {', '.join(skipped_coins)}")

    success_count = 0
    current_balances = await execute_upbit_api(upbit.get_balances)
    if isinstance(current_balances, list):
        current_cash = float(next((b['balance'] for b in current_balances if b['currency'] == "KRW"), 0))
        current_held = {f"KRW-{b['currency']}": float(b['avg_buy_price']) for b in current_balances if b['currency'] != "KRW" and f"KRW-{b['currency']}" in STRAT.get('tickers', []) and (float(b['balance']) + float(b['locked'])) * float(b['avg_buy_price']) >= 5000}

        for target in final_buy_targets:
            if current_cash < 6000 or len(current_held) >= STRAT.get('max_concurrent_trades', 5): break
            buy_succeeded = await process_buy_order(target['t'], target['final_score'], target['reason'], target['data'], total_asset, current_cash, len(current_held), target['exit_plan'], buy_mode=target['mode'], pass_score=target['pass_score'])
            if buy_succeeded: 
                success_count += 1
                current_cash -= min(current_cash * 0.99, (total_asset / STRAT.get('max_concurrent_trades', 5)))
                current_held[target['t']] = 0 

    if is_deep_scan:
        if success_count > 0: consecutive_empty_scans = 0
        else: consecutive_empty_scans += 1

# --- [6. 통합 메인 엔진 및 자산 관리] ---
SCAN_IN_PROGRESS = False
async def background_scan_task(is_deep):
    global SCAN_IN_PROGRESS
    SCAN_IN_PROGRESS = True
    try: await run_full_scan(is_deep_scan=is_deep)
    except Exception as e: logging.error(f"⚠️ 백그라운드 스캔 에러: {e}")
    finally: SCAN_IN_PROGRESS = False

async def build_report(header, is_running):
    balances = await execute_upbit_api(upbit.get_balances)
    if not isinstance(balances, list):
        return f"<b>📊 {header} {'🟢' if is_running else '🔴'}</b>\n⚠️ <b>Upbit API 에러:</b> 잔고 조회 실패.\nAPI 키, 권한(조회/주문), 또는 IP 등록 상태를 확인하세요.\n(상세: {balances})"

    cash = safe_float(next((b.get('balance') for b in balances if isinstance(b, dict) and b.get('currency') == "KRW"), 0.0))
    total, coins = cash, []
    for b in balances:
        if isinstance(b, dict) and b.get('currency') and b.get('currency') != "KRW":
            ticker = f"KRW-{b.get('currency')}"
            avg_p = safe_float(b.get('avg_buy_price'))
            p = safe_float(REALTIME_PRICES.get(ticker, avg_p))
            
            qty = safe_float(b.get('balance')) + safe_float(b.get('locked'))
            val = qty * p
            total += val

            if ticker in trade_data or (qty * avg_p >= 5000):
                invested_krw = (qty * avg_p) * 1.0005
                earned_krw = val * 0.9995
                
                net_profit = earned_krw - invested_krw
                net_rate = (net_profit / invested_krw) * 100 if invested_krw > 0 else 0
                
                coins.append({'t': ticker, 'r': net_rate, 'pft': net_profit, 'val': val})

    wr, tc, wc, tp, _,_ = await get_performance_stats_db()
    scan_interval_min = STRAT.get('deep_scan_interval', 1800) // 60

    pass_score_threshold = STRAT.get('pass_score_threshold', 60)
    recent_pass_scores = []
    held_tickers_list = [c['t'] for c in coins]

    for ticker, data in trade_data.items():
        if ticker in held_tickers_list and isinstance(data, dict) and 'pass_score' in data:
            recent_pass_scores.append(data['pass_score'])

    if recent_pass_scores:
        current_pass_score = sum(recent_pass_scores) / len(recent_pass_scores)
        score_label = "진입 평균"
    else:
        current_pass_score = LATEST_TOP_PASS_SCORE
        score_label = "대기 최고"

    score_display = f"{int(current_pass_score)}점" if current_pass_score > -900 else "-점 (대기중)"

    guideline = str(STRAT.get('exit_plan_guideline', '특별한 지침 없음')).replace('<', '&lt;').replace('>', '&gt;')

    indicator_weights_str = ", ".join([f"{k.upper()}: {v}" for k, v in STRAT.get('indicator_weights', {}).items()])
    trend_logic_str = ", ".join(STRAT.get('trend_active_logic', []))
    range_logic_str = ", ".join(STRAT.get('range_active_logic', []))

    msg = (
        f"📊 <b>[{header}]</b> {'🟢 가동 중' if is_running else '🔴 정지됨'}\n"
        f"🎯 <b>상태: {SYSTEM_STATUS}</b>\n" 
        f"━━━━━━━━━━━━━━━━━\n"
        f"🏦 <b>자산 현황</b>\n"
        f" ├ 💰 총 자산: {total:,.0f}원\n"
        f" └ 💵 가용 현금: {cash:,.0f}원\n\n"
        f"📈 <b>누적 퍼포먼스</b>\n"
        f" ├ 💸 누적 손익: {tp:,.0f}원\n"
        f" └ 🎯 승률: {wr:.1f}% ({tc}전 {wc}승)\n\n"
        f"⚙️ <b>클래식 엔진 세팅</b>\n"
        f" ├ ⏱️ 스캔 주기: {scan_interval_min}분\n"
        f" └ 스코어({score_label}): {score_display} / {pass_score_threshold}점\n\n"
        f"🚀 <b>활성 지표 (가중치)</b>\n"
        f" ├ 추세: {trend_logic_str}\n"
        f" ├ 횡보: {range_logic_str}\n"
        f" └ {indicator_weights_str}\n\n"
        f"📜 <b>작전 지침</b>\n"
        f" └ {guideline}\n"
    )

    if coins:
        msg += "\n🎒 <b>[보유 종목 상세]</b>\n"
        for c in coins:
            icon = "🔴" if c['r'] < 0 else "🟢"
            msg += f" {icon} {c['t']} [{c['val']:,.0f}원]\n   └ {c['r']:+.2f}% ({c['pft']:,.0f}원)\n"

    return msg

# 👇 [새로 교체할 코드] 최근 24시간 필터링 및 손익비(RRR) 계산 로직 탑재
async def daily_settlement_report():
    # 1. 정확히 24시간 전의 시간을 구합니다.
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    
    # 2. DB에서 최근 24시간 동안 발생한 '매도(SELL)' 기록만 싹 긁어옵니다.
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT profit_krw FROM trade_history WHERE side='SELL' AND timestamp >= ?", (yesterday_str,)) as cursor:
            rows = await cursor.fetchall()
            rows = list(rows)
            
    total_cnt = len(rows)
    wins = [row['profit_krw'] for row in rows if row['profit_krw'] > 0]
    losses = [row['profit_krw'] for row in rows if row['profit_krw'] <= 0]
    
    win_count = len(wins)
    loss_count = len(losses)
    
    # 3. 24시간 누적 손익 및 승률 계산
    daily_profit = sum(wins) + sum(losses)
    win_rate = (win_count / total_cnt * 100) if total_cnt > 0 else 0.0
    
    # 4. 손익비(RRR) 계산: (평균 수익금 / 평균 손실금)
    avg_win = sum(wins) / win_count if win_count > 0 else 0
    avg_loss = abs(sum(losses) / loss_count) if loss_count > 0 else 0
    
    if avg_loss > 0:
        pl_ratio_str = f"{avg_win / avg_loss:.2f}"
    else:
        # 손실이 아예 없었을 경우의 처리
        pl_ratio_str = "무손실 (MAX)" if avg_win > 0 else "0.00"
        
    return (
        f"📅 <b>클래식 일일 결산 (최근 24H)</b>\n"
        f"💰 <b>일일 손익: {daily_profit:,.0f}원</b>\n"
        f"📈 승률: {win_rate:.1f}% ({total_cnt}전 {win_count}승)\n"
        f"⚖️ 손익비 (RRR): {pl_ratio_str}\n"
    )

async def generate_daily_proposal(bot_name="Classic"):
    try:
        today_str = datetime.now().strftime('%Y%m%d')
        
        async with aiosqlite.connect(DB_FILE) as db:
            cursor = await db.execute(
                "SELECT id, timestamp, ticker, status, reason, improvement "
                "FROM trade_history "
                "WHERE status != 'ENTERED' AND is_reported = 0 "
                "ORDER BY id ASC" 
            )
            rows = await cursor.fetchall()
            rows = list(rows)

        if not rows:
            await send_msg(f"📁 <b>{bot_name}</b>: 새로 추가된 AI 제언이 없습니다. (모두 읽음 처리됨)")
            return

        file_name = f"적용제안_{bot_name}_{today_str}.txt"
        file_path = os.path.join(base_path, file_name)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"=== [{bot_name} 봇] 신규 AI 사후 분석 및 로직 개선 제안 ===\n")
            f.write(f"새롭게 누적된 {len(rows)}건의 제언입니다.\n\n")
            for r in rows:
                f.write(f"🕒 시간: {r[1]}\n")
                f.write(f"🪙 종목: {r[2]}\n")
                f.write(f"📊 상태: {r[3]}\n")
                f.write(f"🔍 사유: {r[4]}\n")
                f.write(f"💡 제언: {r[5]}\n")
                f.write("-" * 60 + "\n")
        
        async with aiosqlite.connect(DB_FILE) as db:
            reported_ids = [r[0] for r in rows]
            placeholders = ','.join('?' for _ in reported_ids)
            await db.execute(f"UPDATE trade_history SET is_reported = 1 WHERE id IN ({placeholders})", reported_ids)
            await db.commit()

        try:
            with open(file_path, "rb") as doc:
                await bot.send_document(chat_id=TG_CONF['chat_id'], document=doc, caption=f"📁 {bot_name} 신규 적용 제안 리포트 도착!\n중복이 제거된 최신 내역입니다.")
        except Exception as e:
            logging.error(f"텔레그램 파일 전송 실패: {e}")
            
    except Exception as e:
        logging.error(f"제안 파일 생성 중 오류 발생: {e}")

COMMAND_HELP_MSG = """⌨️ <b>[사용 가능한 텔레그램 명령어]</b>
• <b>보고</b> : 현재 자산, 누적 수익, 봇 상태 실시간 브리핑
• <b>명령어</b> : 현재 보고 계신 명령어 목록(도움말) 출력
• <b>시작</b> : 봇 감시 및 매매 엔진 가동 (🟢)
• <b>정지</b> : 봇 감시 및 매매 엔진 일시 정지 (🔴)
• <b>매수</b> : 시장 유동성 무시하고 강제 정밀 스캔 1회 가동
• <b>매도</b> : 보유 중인 모든 종목 시장가 긴급 전량 청산
• <b>최적화</b> : AI 기반 마스터 전략 및 파라미터 수동 최적화
• <b>제안</b> : 누적된 AI 사후 분석 리포트(TXT 파일) 추출
"""

async def handle_telegram_updates():
    global is_running, last_update_id, trade_data
    logging.info("텔레그램 명령 처리 태스크 시작")
    
    if last_update_id is None:
        try:
            updates = await bot.get_updates(offset=-1, limit=1)
            if updates:
                last_update_id = updates[-1].update_id + 1
            else:
                last_update_id = None
        except Exception as e:
            pass

    while True:
        try:
            updates = await asyncio.wait_for(
                bot.get_updates(offset=last_update_id, timeout=20),
                timeout=25.0
            )
            
            for update in updates:
                last_update_id = update.update_id + 1
                if not update.message or not update.message.text: continue
                
                if str(update.message.chat_id) != str(TG_CONF['chat_id']):
                    continue
                
                cmd = update.message.text
                logging.info(f"📩 텔레그램 명령 수신: {cmd}")
                
                if cmd == "보고": await send_msg(await build_report("클래식 실시간 보고", is_running))
                elif cmd == "명령어": await send_msg(COMMAND_HELP_MSG)
                elif cmd == "최적화": await ai_self_optimize()
                elif cmd == "시작": is_running = True; await send_msg("🟢 가동")
                elif cmd == "정지": is_running = False; await send_msg("🔴 정지")
                elif cmd == "매수": 
                    if not SCAN_IN_PROGRESS: 
                        await send_msg("🚀 <b>수동 정밀 스캔 가동</b> (방어막 무시)")
                        asyncio.create_task(background_scan_task(False)) 
                    else: 
                        await send_msg("⏳ 현재 이미 스캔이 진행 중입니다.")   
                elif cmd == "제안":
                    await send_msg("📁 <b>AI 제언 리포트 생성 중...</b>")
                    asyncio.create_task(generate_daily_proposal(bot_name="Classic"))
                     
                elif "매도" in cmd: # "/매도", "매도 " 등 모두 융통성 있게 찰떡같이 인식합니다!
                    balances = await execute_upbit_api(upbit.get_balances)
                    # Type validation for balances response
                    if not isinstance(balances, list):
                        await send_msg("❌ 잔고 조회 실패 (API 오류)")
                        continue
                    
                    # trade_data에 없더라도 실제 5000원 이상 들고 있으면 모두 강제 매도 대상에 포함 (투명 코인 방지)
                    held_for_sell = {}
                    for b in balances:
                        if not isinstance(b, dict) or b.get('currency') == "KRW":
                            continue
                        currency = b.get('currency')
                        ticker = f"KRW-{currency}"
                        balance = float(b.get('balance', 0)) + float(b.get('locked', 0))
                        avg_price = float(b.get('avg_buy_price', 0))
                        if (ticker in trade_data or balance * avg_price >= 5000):
                            held_for_sell[ticker] = b
                    
                    sold_count = 0
                    for t_ticker, b in held_for_sell.items():
                        _bal = safe_float(b.get('balance'))
                        _loc = safe_float(b.get('locked'))
                        _avg_p = safe_float(b.get('avg_buy_price'))
                        
                        qty = _bal + _loc
                        real_p = safe_float(REALTIME_PRICES.get(t_ticker), _avg_p)
                        
                        # 💣 [핵심 방어] 업비트는 5000원 미만 매도 시 에러를 뿜습니다. 
                        # 이 에러가 무한 재시도(무한 루프)를 유발하여 텔레그램 봇을 마비시키는 것을 원천 차단!
                        if qty * real_p < 5000:
                            logging.warning(f"⚠️ {t_ticker} 잔고 5000원 미만으로 매도 스킵 (짜투리 코인)")
                            continue
                            
                        invested_krw = _avg_p * qty * 1.0005
                        earned_krw = real_p * qty * 0.9995
                        p_krw = earned_krw - invested_krw
                        
                        await execute_upbit_api(upbit.sell_market_order, t_ticker, qty)
                        # db 기록 시 amount 자리에 0 대신 실제 qty를 기록하도록 수정
                        await record_trade_db(t_ticker, 'SELL', real_p, qty, profit_krw=p_krw, reason="[수동청산]")
                        
                        last_sell_time[t_ticker] = time.time()
                        sold_count += 1
                        
                    trade_data.clear()
                    TRADE_DATA_DIRTY = True
                    await send_msg(f"🚨 <b>클래식 수동 전량 매도 완료 ({sold_count}개 종목 청산)</b>")
                
        except asyncio.TimeoutError: pass
        except telegram.error.NetworkError: await asyncio.sleep(1.0)
        except Exception as e:
            logging.error(f"❗ 텔레그램 루프 에러: {e}")
            await asyncio.sleep(1.0)
        
        await asyncio.sleep(0.5)

# 🟢 [수술 완료] 메인 감시 루프의 딜레이를 없애기 위한 백그라운드 매도 리포트 생성기
async def background_sell_report(ticker, real_price, sell_qty, p_krw, p_rate, sell_reason_str, analyze_payload):
    try:
        # AI 분석을 메인 루프 밖에서 여유롭게 진행
        ai_r = await ai_analyze(ticker, analyze_payload, mode="SELL_REASON", ignore_cooldown=True) # 퀀텀은 ai_quantum_analyze
        
        ai_rating = ai_r.get('rating', 0) if isinstance(ai_r, dict) else 0
        ai_status = ai_r.get('status', 'UNKNOWN') if isinstance(ai_r, dict) else 'UNKNOWN'
        ai_msg = str(ai_r.get('reason', str(ai_r))).replace('<', '&lt;').replace('>', '&gt;') if isinstance(ai_r, dict) else str(ai_r)
        
        # 여기에 .replace('<', '&lt;').replace('>', '&gt;') 를 추가합니다!
        ai_improvement = str(ai_r.get('improvement', '없음')).replace('<', '&lt;').replace('>', '&gt;') if isinstance(ai_r, dict) else '없음'
        
        # DB 저장
        await record_trade_db(ticker, 'SELL', real_price, sell_qty, profit_krw=p_krw, reason=f"[{sell_reason_str}] {ai_msg}", status=ai_status, rating=ai_rating, improvement=ai_improvement)
        
        # 텔레그램 발송
        telegram_message = f"🔕 <b>최종 청산 완료</b> ({ticker})\n- 상태: {ai_status} ({ai_rating}점)\n- 사유: {sell_reason_str}\n- 수익률: {p_rate:+.2f}%\n- 수익금: {p_krw:,.0f}원\n- AI: {ai_msg}"
        if ai_improvement and ai_improvement != '없음': 
            telegram_message += f"\n\n💡 <b>제언</b>: {ai_improvement}"
            
        await send_msg(telegram_message)
    except Exception as e:
        logging.error(f"백그라운드 매도 리포트 에러 ({ticker}): {e}")

async def main():
    global trade_data, last_global_buy_time, BALANCE_CACHE, last_sell_time, last_buy_time, is_running, last_update_id

    global instance_lock
    import socket
    try:
        instance_lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        instance_lock.bind(('127.0.0.1', 65432)) # 아무도 안 쓰는 임의의 비밀 포트에 자물쇠를 채웁니다.
    except socket.error:
        logging.error("❌ 이미 ATS_Classic 봇이 실행 중입니다. 중복 실행을 방지하기 위해 즉시 종료합니다.")
        return # 이미 포트가 잠겨있다면 조용히 프로그램을 종료!
    
    tg_task = asyncio.create_task(handle_telegram_updates())
    await asyncio.sleep(0.1) 
    
    last_report_time = time.time()
    last_loss_check_time = time.time()
    last_checked_win_rate = 100.0
    last_daily_report_day = datetime.now().day
    last_proposal_day = None
    
    
    await init_db()
    trade_data = await load_trade_status_db()
    asyncio.create_task(websocket_ticker_task())
    
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT ticker, timestamp FROM trade_history WHERE side='SELL' ORDER BY id DESC LIMIT 50") as cursor:
            async for row in cursor:
                ticker, ts_str = row[0], row[1]
                t_time = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').timestamp()
                if time.time() - t_time < 1800:
                    if ticker not in last_sell_time or last_sell_time[ticker] < t_time:
                        last_sell_time[ticker] = t_time

    current_balances = await execute_upbit_api(upbit.get_balances)
    if isinstance(current_balances, list):
        # 현재 업비트에 실제로 5,000원 이상 보유 중인 코인 목록
        real_held = [f"KRW-{b['currency']}" for b in current_balances if b['currency'] != 'KRW' and (float(b['balance']) + float(b['locked'])) * float(b['avg_buy_price']) >= 5000]
        
        # 1. 👻 유령 코인 삭제 (DB에는 있는데 실제 잔고엔 없는 경우)
        ghost_coins = [t for t in list(trade_data.keys()) if t not in real_held]
        for gc in ghost_coins:
            logging.warning(f"👻 유령 코인 삭제: {gc} (실제 잔고 없음)")
            del trade_data[gc]
            TRADE_DATA_DIRTY = True
            
        # 2. 👶 미아 코인 입양 (실제 잔고엔 있는데 DB엔 없는 경우)
        for t in real_held:
            if t not in trade_data:
                logging.warning(f"👶 미아 코인 입양: {t} (DB 누락 복구)")
                b = next(x for x in current_balances if f"KRW-{x['currency']}" == t)
                avg_p = float(b['avg_buy_price'])
                
                # 🟢 [Pylance 방어] 입양 시 데이터 정화 로직 강화
                _, curr_ind_raw = await get_indicators(t)
                if curr_ind_raw is None:
                    curr_ind_dict = {}
                else:
                    curr_ind_dict = curr_ind_raw if isinstance(curr_ind_raw, dict) else curr_ind_raw.to_dict()
                
                real_atr = curr_ind_dict.get('ATR', avg_p * 0.02) if curr_ind_dict else (avg_p * 0.02)
                tier_params = get_coin_tier_params(t, curr_ind_dict) if curr_ind_dict else STRAT.get('major_params', {})
                
                trade_data[t] = {
                    'high_p': avg_p, 'entry_atr': real_atr, 'guard': False,
                    'buy_ind': curr_ind_dict, 
                    'last_notified_step': 0, 'buy_ts': time.time(),
                    'exit_plan': {
                        "target_atr_multiplier": tier_params.get('target_atr_multiplier', 4.5),
                        "stop_loss": tier_params.get('stop_loss', -3.0),
                        "atr_mult": tier_params.get('atr_mult', 2.0),
                        "timeout": tier_params.get('timeout_candles', 8),
                        "adaptive_breakeven_buffer": tier_params.get('adaptive_breakeven_buffer', 0.003)
                    }, 
                    'buy_reason': "[시스템 복구] 재가동 잔고 동기화 입양", 
                    'btc_buy_price': 0,
                    'pass_score': 80, 'is_runner': False, 'score_history': []
                }
                TRADE_DATA_DIRTY = True

    await send_msg(f"⚔️ <b>ATS_Classic 가동 시작 </b>\n\n{COMMAND_HELP_MSG}")
    await send_msg(await build_report("초기 보고", True))
    asyncio.create_task(background_scan_task(True))
    asyncio.create_task(db_flush_task())
    await asyncio.sleep(3)
    
    while True:
        try:
            await asyncio.sleep(0.1) 
            
            if not is_running:
                await asyncio.sleep(0.5)
                continue
            
            now_ts, now_dt = time.time(), datetime.now()
            
            if 'BALANCE_CACHE' not in globals(): BALANCE_CACHE = {"data": None, "timestamp": 0}
            if now_ts - BALANCE_CACHE['timestamp'] > BALANCE_CACHE_SEC: 
                BALANCE_CACHE['data'] = await execute_upbit_api(upbit.get_balances)
                BALANCE_CACHE['timestamp'] = now_ts
                
            balances = BALANCE_CACHE['data']
            if not balances or not isinstance(balances, list): 
                await asyncio.sleep(1.0)
                continue

            # 🟢 [Pylance 방어] cash 안전 추출
            cash = safe_float(next((b.get('balance') for b in balances if isinstance(b, dict) and b.get('currency') == "KRW"), 0.0))
            
            # 🟢 [FIX: 변수명 복구 및 방어] main 루프에서는 held_dict가 아니라 held를 사용해야 하며, 값도 float이 아닌 b(딕셔너리) 자체여야 합니다!
            held = {
                f"KRW-{b.get('currency')}": b 
                for b in balances 
                if isinstance(b, dict) and b.get('currency') and b.get('currency') != "KRW" 
                and (
                    f"KRW-{b.get('currency')}" in trade_data or 
                    (safe_float(b.get('balance')) + safe_float(b.get('locked'))) * safe_float(b.get('avg_buy_price')) >= 5000
                )
            }
            
            monitoring_tickers = list(set(STRAT.get('tickers', []) + list(held.keys())))
            btc_short = await get_btc_short_term_data()

            for ticker in monitoring_tickers:
                current_live_score = None
                if ticker not in held and ticker in last_sell_time and (now_ts - last_sell_time.get(ticker, 0)) < 1800: 
                    continue                    

                if ticker in held:
                    # 🟢 보유 종목의 지표를 백그라운드에서 주기적으로 새로고침
                    asyncio.create_task(get_indicators(ticker))
                    
                    coin = held[ticker]
                    # 🟢 [Pylance 추가 방어] coin 딕셔너리에서 평단가를 꺼낼 때도 정수기(safe_float)를 통과시킵니다.
                    avg_p = safe_float(coin.get('avg_buy_price'))
                    real_price = REALTIME_PRICES.get(ticker)
                    if not real_price: continue
                    
                    invested_krw_unit = avg_p * 1.0005
                    earned_krw_unit = real_price * 0.9995
                    p_rate = ((earned_krw_unit - invested_krw_unit) / invested_krw_unit) * 100 if invested_krw_unit > 0 else 0.0

                    if ticker not in trade_data:
                        continue
                    
                    t = trade_data[ticker]
                    changed = False

                    if real_price > t.get('high_p', real_price): t['high_p'] = real_price; changed = True
                    if int(p_rate) >= 1 and int(p_rate) > t.get('last_notified_step', 0): await send_msg(f"📈 {ticker} 랠리! {p_rate:+.2f}%"); t['last_notified_step'] = int(p_rate); changed = True
                    
                    current_live_score = None
                    if ticker in INDICATOR_CACHE:
                        prev_i, curr_i = INDICATOR_CACHE[ticker][1], INDICATOR_CACHE[ticker][2]
                        
                        # Type normalization: convert Series to dict if necessary
                        if isinstance(prev_i, pd.Series):
                            prev_i = prev_i.to_dict()
                        if isinstance(curr_i, pd.Series):
                            curr_i = curr_i.to_dict()
                        
                        # Ensure both are dicts
                        if not isinstance(prev_i, dict) or not isinstance(curr_i, dict):
                            continue
                        
                        is_strong_trend = curr_i.get('adx', 0) > STRAT.get('adx_strong_trend_threshold', 25.0)
                        active_logic_list = STRAT.get('trend_active_logic', ['supertrend', 'macd', 'volume', 'bollinger', 'obv']) if is_strong_trend else STRAT.get('range_active_logic', ['rsi', 'stochastics', 'vwap', 'ssl_channel', 'atr_trend'])
                        regime = await get_market_regime()

                        # 🟢 [수술 완료] 실시간 점수 산출 시에도 FGI 동적 배율 완벽 적용 (스캔 엔진과 일치시킴)
                        fgi = regime.get('fear_and_greed', '')
                        try:
                            match = re.search(r'\d+', fgi)
                            fgi_value = int(match.group()) if match else 50
                        except:
                            fgi_value = 50  
                            
                        v_bottom = STRAT.get('fgi_v_curve_bottom', 70.0)
                        v_max = STRAT.get('fgi_v_curve_max', 3.0)
                        v_min = STRAT.get('fgi_v_curve_min', 0.5)
                        v_greed = STRAT.get('fgi_v_curve_greed_max', 1.5)
                            
                        if fgi_value <= v_bottom:
                            dynamic_fgi_mult = v_max - ((fgi_value / v_bottom) * (v_max - v_min))
                        else:
                            dynamic_fgi_mult = v_min + (((fgi_value - v_bottom) / (100.0 - v_bottom)) * (v_greed - v_min))
                            
                        dynamic_fgi_mult = round(dynamic_fgi_mult, 2)
                        
                        try:
                            normalized_fear = (dynamic_fgi_mult - v_min) / (v_max - v_min)
                        except ZeroDivisionError:
                            normalized_fear = 0.5
                        normalized_fear = max(0.0, min(1.0, normalized_fear)) 
                        
                        rsi_mult = 0.5 + (1.5 * normalized_fear)        
                        boll_mult = 1.0 + (0.5 * normalized_fear)       
                        st_mult = 1.5 - (1.0 * normalized_fear)         
                        vol_mult = 2.0 - (1.0 * normalized_fear)        
                        bb_break_mult = 1.5 - (1.0 * normalized_fear)   

                        indicator_mults = {
                            'rsi': rsi_mult, 'bollinger': boll_mult, 'supertrend': st_mult, 
                            'volume': vol_mult, 'bollinger_breakout': bb_break_mult
                        }

                        weights = STRAT.get('indicator_weights', {})
                        dynamic_total_weight = 0.0
                        earned_weighted_score = 0.0
                        
                        for name in active_logic_list:
                            w = safe_float(weights.get(name, 1.0), 1.0)
                            m = safe_float(indicator_mults.get(name, 1.0), 1.0)
                            # main()에서는 웹소켓으로 받아온 real_price를 씁니다.
                            s = safe_float(get_strategy_score(name, prev_i, curr_i, real_price), 0.0)
                            
                            earned_weighted_score += (s * m * w)
                            dynamic_total_weight += (m * w)
                        
                        # ... (동적 배율을 곱해 earning_weighted_score를 구하는 로직)
                        current_live_score = int(earned_weighted_score / dynamic_total_weight) if dynamic_total_weight > 0 else 0
                        
                        # 🟢 [수술 완료] 스캔 엔진과 동일하게 실시간 점수에도 '상황별 보너스/페널티' 완벽 적용!
                        score_mods = STRAT.get('scoring_modifiers', {})
                        b_golden = score_mods.get('bonus_golden_combo', 35)
                        b_mtf_panic = score_mods.get('bonus_mtf_panic_dip', 15)
                        b_btc_panic = score_mods.get('bonus_btc_panic_dip', 10)
                        b_st_bounce = score_mods.get('bonus_st_oversold_bounce', 10)
                        p_st_down = score_mods.get('penalty_st_downtrend', -15)
                        p_rs_weak = score_mods.get('penalty_rs_weakness', -20)
                        
                        is_fear = "Fear" in fgi
                        is_oversold = curr_i.get('rsi', 50) < STRAT.get('rsi_low_threshold', 35.0)
                        is_mom_turn = (curr_i.get('macd_h_diff', 0) > 0 and prev_i.get('macd_h_diff', 0) <= 0) or \
                                      (curr_i.get('st_rsi_k', 0) > curr_i.get('st_rsi_d', 0) and prev_i.get('st_rsi_k', 0) <= prev_i.get('st_rsi_d', 0))

                        if is_fear and is_oversold and is_mom_turn:
                            current_live_score += b_golden  

                        if btc_short['trend'] == "단기 하락":
                            mtf_live = await get_mtf_trend(ticker)
                            if "4H 약세" in mtf_live and "1H 하락" in mtf_live:
                                current_live_score += b_mtf_panic  
                            current_live_score += b_btc_panic      
                            
                        if curr_i.get('ST_DIR', 1) == -1:
                            if curr_i.get('rsi', 50) <= STRAT.get('rsi_low_threshold', 35.0):
                                current_live_score += b_st_bounce
                            else: current_live_score += p_st_down

                        if curr_i.get('rs', 0) < -2.0:
                            current_live_score += p_rs_weak
                            
                        # 최종 점수를 0~100 사이로 안전하게 가둠
                        current_live_score = max(0, min(100, current_live_score))

                    ma_live_score = current_live_score # 기본값
                    if current_live_score is not None:
                        score_hist = t.get('score_history', [])
                        score_hist.append(current_live_score)
                        # 최근 10번의 틱(약 10~20초 분량)만 유지하여 노이즈 상쇄
                        if len(score_hist) > 10: 
                            score_hist.pop(0)
                        t['score_history'] = score_hist
                        
                        # 리스트의 평균값 계산 (소수점 1자리까지)
                        ma_live_score = round(sum(score_hist) / len(score_hist), 1)
                    
                    # 🟢 (이후 기존 방어 로직 계속)
                    if p_rate > 0.6 and current_live_score is not None and ma_live_score < STRAT.get('guard_score_threshold', 60):
                        if not t.get('guard', False):
                            t['guard'] = True
                            changed = True
                            await send_msg(f"🛡️ <b>[펀더멘탈 둔화 방어]</b> {ticker} 평균 점수 하락({ma_live_score}점)! 즉시 본절 방어선 가동.")
                    
                    if changed: TRADE_DATA_DIRTY = True


                    exit_plan = t.get('exit_plan', {})
                    entry_atr = t.get('entry_atr', 0)
                    target_atr_multiplier = exit_plan.get('target_atr_multiplier', 4.5)
                    
                    target_p_price = avg_p + (entry_atr * target_atr_multiplier)
                    target_p = ((target_p_price - avg_p) / avg_p) * 100 if avg_p > 0 else 999.0
                    hard_s = exit_plan.get('stop_loss', -3.0) 

                    current_atr_mult = exit_plan.get('atr_mult', STRAT.get('atr_multiplier_for_stoploss', 1.8))
                    
                    entry_rsi = t.get('buy_ind', {}).get('rsi', 50)
                    if entry_rsi >= 70.0:
                        current_atr_mult = min(current_atr_mult, 1.5) 

                    invested_high_krw = avg_p * 1.0005
                    earned_high_krw = t['high_p'] * 0.9995
                    max_p_rate = ((earned_high_krw - invested_high_krw) / invested_high_krw) * 100 if invested_high_krw > 0 else 0
                    dynamic_mult = current_atr_mult
                    if max_p_rate >= 5.0: dynamic_mult = current_atr_mult * 0.4  
                    elif max_p_rate >= 3.0: dynamic_mult = current_atr_mult * 0.7
                    elif max_p_rate >= 1.0: dynamic_mult = current_atr_mult * 0.85
                        
                    atr_stop = t['high_p'] - (entry_atr * dynamic_mult)
                    chandelier_stop = t['high_p'] * 0.975 if max_p_rate >= 5.0 else 0
                    stop_p = max(atr_stop, chandelier_stop)
                    
                    adaptive_buffer = exit_plan.get('adaptive_breakeven_buffer', 0.003)
                    
                    # 👇 [수정 후] 발동 조건 상향에 맞추어 조건을 > 0.6 으로 변경하고, 바닥을 1.002(+0.2%)로 설정
                    if t.get('guard') and max_p_rate > 0.6: 
                        # 💡 [조화로운 바닥] 수수료(0.1%)와 슬리피지(0.1%)만 딱 막아내는 +0.2%를 바닥으로 설정
                        hard_breakeven_floor = avg_p * 1.003 
                        calculated_guard_p = t['high_p'] * (1 - adaptive_buffer)
                        stop_p = max(stop_p, hard_breakeven_floor, calculated_guard_p)
                    else: 
                        stop_p = max(stop_p, avg_p - (entry_atr * current_atr_mult))
                    if entry_atr == 0: stop_p = max(stop_p, avg_p * 0.98) 
                    
                    # 🟢 [FIX: 러너 스탑 방어막 논리 일관성 수정] 기존 트레일링 스탑 계산과 융합하여 무조건 본절 + 0.7% 위에서 청산되도록 수정
                    if t.get('is_runner', False):
                        stop_p = max(stop_p, avg_p * 1.007)

                    if max_p_rate >= 1.0:
                        t['breakeven_locked'] = True
                        
                    # 브레이크이븐 락이 걸렸다면, 그 어떤 상황에서도 평단가 + 수수료(약 0.2%) 위에서 방어
                    if t.get('breakeven_locked', False):
                        stop_p = max(stop_p, avg_p * 1.005)
                    
                    scale_out_step = t.get('scale_out_step', 0)
                    is_sell, is_partial_sell = False, False
                    sell_reason_str, urgency = "", "NORMAL"
                    sell_qty_ratio = 1.0
                    next_step = scale_out_step

                    # 🟢 [개선] 1. 미리 시간을 계산해 둡니다.
                    timeout_candles = exit_plan.get('timeout', STRAT.get('timeout_candles', 8))
                    
                    # 🟢 [수술 완료] 업비트가 지원하는 모든 차트 주기에 대응하도록 초 단위 정확히 할당
                    interval_str = STRAT.get('interval', 'minute15')
                    if interval_str.startswith('minute'):
                        interval_sec = int(interval_str.replace('minute', '')) * 60
                    elif interval_str == 'day':
                        interval_sec = 86400  # 24시간
                    elif interval_str == 'week':
                        interval_sec = 604800 # 7일
                    elif interval_str == 'month':
                        interval_sec = 2592000 # 30일
                    else:
                        interval_sec = 900 # 알 수 없는 값일 경우 기본 15분으로 방어
                        
                    elapsed_sec = now_ts - t.get('buy_ts', now_ts)

                    # 타임아웃 관련 변수 정의
                    full_timeout_sec = timeout_candles * interval_sec
                    half_timeout_sec = full_timeout_sec / 2
                    micro_timeout_sec = interval_sec * 1 # 1캔들 타임아웃으로 설정

                    curr_i_safe = INDICATOR_CACHE[ticker][2] if ticker in INDICATOR_CACHE else {}
                    
                    # 🟢 [수술 완료] 2. 펀더멘탈 붕괴 여부를 Elif 늪에 빠지지 않게 미리 판단(Boo
                    #lean)해 둡니다.
                    is_fundamental_broken = False
                    if current_live_score is not None and ma_live_score < STRAT.get('sell_score_threshold', 40):
                        atr_1x_pct = (entry_atr / avg_p) * 100 if avg_p > 0 else 1.5
                        fundamental_bailout_limit = -max(1.0, min(3.0, atr_1x_pct))
                        if elapsed_sec > (interval_sec * 2) or p_rate < fundamental_bailout_limit:
                            is_fundamental_broken = True
                    
                    rsi_high_limit = STRAT.get('rsi_high_threshold', 60.0)
                    # 매도 조건 로직 리팩토링
                    macd_diff_val = curr_i_safe.get('macd_h_diff', 0)
                    if macd_diff_val is None: macd_diff_val = 0
                    
                    # 타입 체커를 위한 명시적 타입 변환 및 None 방어
                    curr_p_rate = float(p_rate) if p_rate is not None else 0.0
                    curr_ma_score = float(ma_live_score) if ma_live_score is not None else 0.0
                    
                    sell_conditions = [
                        (curr_p_rate >= (target_p * 0.7) and curr_i_safe.get('rsi', 50) >= rsi_high_limit and scale_out_step == 0, "동적 익절 1단계 (RSI 과열)", 0.3, 1, "NORMAL"),
                        (curr_p_rate >= target_p and scale_out_step <= 1, "목표 수익 익절 2단계", 0.5, 2, "NORMAL"),
                        (curr_p_rate <= hard_s, "절대 손절선 이탈", 1.0, 0, "HIGH"),
                        (real_price <= stop_p, "트레일링 스탑 이탈", 1.0, 0, "HIGH"),
                        (is_fundamental_broken, f"펀더멘탈 붕괴 ({ma_live_score}점)", 1.0, 0, "HIGH"),
                        (elapsed_sec > full_timeout_sec and curr_p_rate <= 1.0, f"타임아웃 ({timeout_candles}캔들)", 1.0, 0, "NORMAL"),
                        (elapsed_sec > half_timeout_sec and curr_p_rate < 0.0 and (macd_diff_val < 0 or curr_ma_score < 55), "⏳ 조기 타임아웃 (반등 모멘텀 소멸)", 1.0, 0, "HIGH"),                        
                        (elapsed_sec > micro_timeout_sec and curr_p_rate <= -1.0, "⏳ 초단기 컷 (가짜 바닥 판명, 즉각 탈출)", 1.0, 0, "HIGH"),
                        (elapsed_sec > micro_timeout_sec and curr_p_rate <= -0.5 and macd_diff_val < 0, "⏳ 초단기 컷 (반등 실패 및 모멘텀 악화)", 1.0, 0, "HIGH")
                    ]

                    for condition, reason, ratio, step, urgency_level in sell_conditions:
                        if condition:
                            is_sell = (ratio == 1.0)
                            is_partial_sell = not is_sell
                            sell_qty_ratio = ratio
                            sell_reason_str = reason
                            urgency = urgency_level
                            next_step = step
                            break
                    else: # 모든 조건에 해당하지 않을 경우
                        is_sell, is_partial_sell = False, False
                        sell_reason_str, urgency = "", "NORMAL"
                        sell_qty_ratio = 1.0
                        next_step = scale_out_step

                    if is_sell or is_partial_sell:
                        # 🟢 라이브 호가 갱신
                        live_price = await execute_upbit_api(pyupbit.get_current_price, ticker)
                        if live_price:
                            real_price = live_price
                            # 👇 [개선 로직 4-1] 라이브 호가 갱신 시에도 수수료 적용 수익률로 재계산
                            invested_krw_unit = avg_p * 1.0005
                            earned_krw_unit = real_price * 0.9995
                            p_rate = ((earned_krw_unit - invested_krw_unit) / invested_krw_unit) * 100 if invested_krw_unit > 0 else 0.0

                        # 🟢 [Pylance 방어] 코인 잔고 데이터도 정수기를 거쳐 안전하게 계산합니다.
                        _c_bal = safe_float(coin.get('balance'))
                        _c_loc = safe_float(coin.get('locked'))
                        
                        qty = _c_bal + _c_loc
                        sell_qty = qty * sell_qty_ratio if is_partial_sell else qty
                        
                        buy_principal = sell_qty * avg_p
                        invested_krw = buy_principal * 1.0005
                        s_krw = sell_qty * real_price
                        earned_krw = s_krw * 0.9995
                        p_krw = earned_krw - invested_krw
                        
                        await execute_smart_sell(ticker, sell_qty, real_price, urgency)
                        BALANCE_CACHE['timestamp'] = 0 
                        
                        if is_partial_sell:
                            t['scale_out_step'] = next_step
                            # 🟢 [FIX: 강제 음수 할당(버그) 제거 -> 러너 플래그 활성화로 트레일링 스탑에 권한 위임]
                            t['is_runner'] = True 

                            TRADE_DATA_DIRTY = True
                            await record_trade_db(ticker, 'SELL', real_price, sell_qty, profit_krw=p_krw, reason=f"[{sell_reason_str}]", status="PARTIAL_SUCCESS", rating=80)
                            await send_msg(f"💸 <b>{next_step}차 분할 익절</b> ({ticker})\n- 수익률: {p_rate:+.2f}%\n- 수익금: {p_krw:,.0f}원")
                            continue

                        _, curr = await get_indicators(ticker)
                        btc_sell_p = REALTIME_PRICES.get('KRW-BTC', 0)
                        btc_buy_p = t.get('btc_buy_price', btc_sell_p)
                        btc_change = ((btc_sell_p - btc_buy_p) / btc_buy_p * 100) if btc_buy_p > 0 else 0
                        
                        analyze_payload = {
                            'p_rate': round(p_rate, 2), 'buy_ind': t.get('buy_ind'), 'sell_ind': curr.to_dict() if curr is not None else {},
                            'actual_sell_reason': sell_reason_str, 'original_buy_reason': t.get('buy_reason', ''), 'original_exit_plan': t.get('exit_plan', {}),
                            'btc_buy_price': btc_buy_p, 'btc_sell_price': btc_sell_p, 'btc_change': btc_change
                        }
                        
                        last_sell_time[ticker] = now_ts
                        del trade_data[ticker]
                        TRADE_DATA_DIRTY = True
                        
                        # 2. AI 반성문과 텔레그램 발송은 백그라운드 태스크로 던져버림 (Fire and Forget)
                        # ticker=ticker 형태로 바인딩
                        asyncio.create_task(background_sell_report(ticker=ticker, real_price=real_price, sell_qty=sell_qty, p_krw=p_krw, p_rate=p_rate, sell_reason_str=sell_reason_str, analyze_payload=analyze_payload))                        
                        continue

            # --- [주요 백그라운드 태스크 실행 및 보고 로직] ---

            # 1. 정기 보고
            if now_ts - last_report_time >= STRAT.get("report_interval_seconds", 7200): 
                await send_msg(await build_report("정기 보고", is_running))
                last_report_time = now_ts
            
            # 2. 일일 결산 보고 (매일 오전 9시)
            if now_dt.hour == 9 and now_dt.minute == 0 and now_dt.day != last_daily_report_day: 
                await send_msg(await daily_settlement_report())
                last_daily_report_day = now_dt.day
            
            # 3. 일일 AI 제안 파일 생성 (매일 오전 9시)
            if now_dt.hour == 9 and now_dt.minute == 0 and now_dt.day != last_proposal_day:
                asyncio.create_task(generate_daily_proposal(bot_name="Classic")) 
                last_proposal_day = now_dt.day
            
            # 4. 4시간마다 손실 방어 및 AI 전략 자동 최적화
            if now_ts - last_loss_check_time >= 14400:
                last_loss_check_time = now_ts 
                try:
                    wr, _, _, _, wins, losses = await get_performance_stats_db()
                    
                    # 🟢 [수술 완료] 스마트 상대평가 도입!
                    # 1. 전체 승률이 70% 미만인가? (절대 조건)
                    # 2. 승률이 4시간 전(이전 검사)보다 떨어졌는가? (상대 조건)
                    if wr < 70.0 and wr < last_checked_win_rate:
                        await ai_self_optimize(trigger="auto")  # 클래식의 경우
                        # 퀀텀은 await quantum_self_optimize(trigger="auto") 로 작성
                        
                    # 현재 승률을 \'이전 승률\'로 덮어씌워 다음 4시간 뒤에 비교할 수 있게 함
                    last_checked_win_rate = wr
                except Exception as e:
                    logging.error(f"승률 기반 최적화 로직 오류: {e}")
            
            # 5. 딥 스캔 실행 조건
            if is_running and (now_ts - last_global_buy_time >= STRAT.get("deep_scan_interval", 1800)):
                if not SCAN_IN_PROGRESS: 
                    asyncio.create_task(background_scan_task(True))
                else: 
                    last_global_buy_time = now_ts # 이미 스캔 중이면 다음 스캔 시간을 늦춰줌
                
            await asyncio.sleep(0.5) 
            
        except Exception as e:
            logging.error(f"❗ 클래식 메인 루프 예외 발생: {e}\n{traceback.format_exc()}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("\n🛑 봇이 종료되었습니다.")
    except Exception as e:
        logging.error(f"\n❌ 실행 중 치명적 오류:\n{traceback.format_exc()}")
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        print(f"로그 파일 저장됨: {log_filepath}")
