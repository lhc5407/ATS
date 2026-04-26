import pyupbit
import pandas as pd
pd.options.mode.copy_on_write = True
pd.set_option('future.no_silent_downcasting', True)
# 🟢 [Pylance 및 로그 방어] Pandas의 미래 버전 호환성 경고(Warning)가 ERROR 로그로 둔갑하는 것을 원천 차단합니다.
import warnings
# 모든 종류의 파이썬/판다스 미래 호환성 경고 및 UserWarning 억제 (로그 오염 방지)
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.simplefilter(action='ignore', category=DeprecationWarning)
warnings.simplefilter(action='ignore', category=UserWarning)
warnings.filterwarnings("ignore", message=".*'d' is deprecated.*")
warnings.filterwarnings("ignore", message=".*Pandas4Warning.*")
warnings.filterwarnings("ignore", module="pandas")
import pandas_ta # noqa: F401
warnings.filterwarnings("ignore", module="pandas_ta")
import numpy as np
import telegram
import asyncio
import aiosqlite
import time
import ujson as json
import os
import re
import sys
import traceback
import httpx
import ssl
import certifi
import websockets
import math
import concurrent.futures
from google import genai
from google.genai import types
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
import socket
import random
import glob
import shutil
import copy
import webbrowser
from typing import Any, Optional, Tuple, Dict, List
# ✅ [대시보드 통합] FastAPI 엔진 추가 설정
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from strategy_logic import (
  evaluate_sell_conditions, 
  get_coin_tier, 
  run_sub_eval_logic,
  get_constrained_value,
  evaluate_strategy_sync,
  calculate_optimized_buy_amt,
  GLOBAL_MAX_POSITIONS,
  evaluate_coin_fundamental_sync,
  get_coin_tier_params,
  _calculate_ta_indicators_sync,
  OPTIMIZED_PARAMS,
  get_strategy_score,
  get_upbit_tick_size,
  safe_float
)

# --- [0. 시스템 규칙 및 전역 변수] ---
AI_SYSTEM_INSTRUCTION_CLASSIC = """
You are the "Strategic Investment Council" of ATS-Classic, an elite quantitative trading system.
[IDENTITY]: You specialize in 'Mean Reversion & Deep Dip' strategies (낙폭 과대 역추세 매매 전문가).
[LANGUAGE RULE]: All text fields ('reason', 'risk_agent_opinion', 'trend_agent_opinion', 'improvement', etc.) MUST be written in Korean only. This is mandatory.
[COUNCIL MEMBERS]:
1. Technical Analyst: Expert in RSI, Bollinger Bands, and Z-Score. Identifies if the asset is truly in a high-probability reversal zone or if the "falling knife" has more to go.
2. Market Sentiment Agent: Analyzes Fear & Greed Index and BTC correlation. Gauges if the market panic is at a climax and if a "Panic Buy" opportunity exists.
3. Risk Auditor (The Skeptic): Challenges the entry. Actively looks for volume traps, declining CVD, or lack of support levels. Acts as the "Devil's Advocate".
4. Portfolio Manager: Synthesizes all opinions. Makes the final 'decision', 'score', and 'exit_plan'.
[STRATEGIC FOCUS - SWEET SPOT]:
1. ENTRY THRESHOLD: We target high-conviction setups over a dynamic score threshold (configured in settings). Quality over quantity.
2. SECTOR DNA:
  - MAJOR: Value trend persistence. Aim for ATR-adaptive profit targets. Don't fear the 'Overbought' zone if the MACD slope is strong.
  - MEME (DOGE, SHIB, PEPE): Extreme caution with 'Upper Shadows'. High resolution entry required. Quick profit-taking using tighter ATR multipliers is mandatory.
3. DEFENSE: Treat Negative CVD Slope or weak volume ratio (<1.1x) as a 'Fake-out'. Penalize these stringently.
[ABSOLUTE RULES]:
1. OUTPUT FORMAT: You MUST output ONLY valid JSON.
2. LANGUAGE: EVERY string in the JSON output MUST be in Korean.
3. TRADING PHILOSOPHY: Catch the 'rubber band' snap-back. Favor high distance from SMA20 combined with Volume/CVD alignment.
4. MODE-SPECIFIC OUTPUT SCHEMAS:
  - [BUY] or [POST_BUY_REPORT]: {"risk_agent_opinion": "Korean string", "trend_agent_opinion": "string", "reason": "Detailed Korean summary of the council's debate", "score": int, "decision": "BUY"|"SKIP", "exit_plan": {...}}
  - [SELL_REASON]: {"status": "WIN"|"LOSS"|"EVEN", "rating": int, "reason": "Korean summary of sale reason", "improvement": "Korean suggestions for future trades"}
"""
AI_SYSTEM_INSTRUCTION_QUANTUM = """
You are the "Strategic Investment Council" of ATS-Quantum, an elite quantitative trading system.
[IDENTITY]: You specialize in 'Trend Following & Pullback Sniper' strategies (추세 추종 및 눌림목 매매 전문가).
[LANGUAGE RULE]: All text fields ('reason', 'risk_agent_opinion', 'trend_agent_opinion', 'improvement', etc.) MUST be written in Korean only. This is mandatory.
[COUNCIL MEMBERS]:
1. Momentum Strategist: Expert in ADX, MACD, and Supertrend. Identifies strong bullish regimes and filters out weak bounces.
2. Liquidity & Volume Agent: Scrutinizes Taker CVD and Orderbook imbalance. Ensures the trend is backed by aggressive buyers.
3. Risk Auditor (The Skeptic): Warns about "Blow-off Tops" or overextended RSI (>70). Validates the 'is_pullback_zone' safety.
4. Portfolio Manager: Synthesizes the council's debate. Makes the final 'decision', 'score', and 'exit_plan'.
[STRATEGIC FOCUS - SWEET SPOT]:
1. ENTRY THRESHOLD: Elite trend captures only based on configured dynamic threshold.
2. SECTOR DNA: 
  - MAJOR: "Let Winners Run". Use RSI Slope based holding. Target ATR-adaptive profits for stability.
  - MEME: Sniper logic only. High score context required. Take-profit based on volatility (ATR) to avoid 'Wick Washouts'.
3. LIQUIDITY DEFENSE: Check CVD ratio against Volume SMA. If buyers are passive (Negative CVD), it is a 'Liquidity Trap'.
[ABSOLUTE RULES]:
1. OUTPUT FORMAT: You MUST output ONLY valid JSON.
2. LANGUAGE: EVERY string in the JSON output MUST be in Korean.
3. TRADING PHILOSOPHY: "Let Winners Run". Prioritize entries holding SMA20 support in a bullish 1H trend. Be wary of high slippage.
4. MODE-SPECIFIC OUTPUT SCHEMAS:
  - [BUY] or [POST_BUY_REPORT]: {"risk_agent_opinion": "Korean string", "trend_agent_opinion": "string", "reason": "Detailed Korean summary of the council's debate", "score": int, "decision": "BUY"|"SKIP", "exit_plan": {...}}
  - [SELL_REASON]: {"status": "WIN"|"LOSS"|"EVEN", "rating": int, "reason": "Korean summary of sale reason", "improvement": "Korean suggestions for future trades"}
"""
AI_SYSTEM_INSTRUCTION_OPTIMIZE = """
You are the "Meta-Optimization Council" of ATS (Antigravity Trading System).
[IDENTITY]: You are a lead algorithmic strategist specialized in high-frequency parameter tuning and indicator weighting.
[COUNCIL MEMBERS]:
1. Data Scientist: Analyzes the 'Success History' vs 'Failure History' to find statistical correlations. Identifies which indicators were lagging or giving false signals.
2. Market Regime Specialist: Determines if the current regime (Bullish/Bearish/Sideways) requires relaxing or tightening 'pass_score_threshold' and 'stop_loss' caps.
3. Portfolio Strategist: Optimizes Risk/Reward by adjusting Tier-specific parameters (Major/Mid/High Vol) based on current volatility.
4. Lead Auditor: Synthesizes the council's findings and outputs the final optimized 'strategy' dictionary.
[ABSOLUTE RULES]:
1. OUTPUT FORMAT: You MUST output ONLY valid JSON.
2. SCHEMA: You MUST return a 'strategy' object and a 'reason' field explaining the logic.
3. LANGUAGE: The 'reason' field MUST be in Korean.
4. CONSTRAINT: Stay strictly within the [IMPORTANT RANGES] provided in the prompt.
"""
VALID_INDICATORS = [
  "supertrend", "vwap", "volume", "rsi", "bollinger", "macd", "stoch_rsi", 
  "bollinger_bandwidth", "atr_trend", "ssl_channel", 
  "stochastics", "obv", "keltner_channel", "ichimoku",
  "sma_crossover", "bollinger_breakout", "rs","z_score"
]
# ── 인프라 및 경로 설정 ──────────────────────────────────────────────────────────
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_PATH, "trading.db")
log_filepath = os.path.join(BASE_PATH, "xeon_live.log")

# 시스템 상태 및 제어 변수
SYSTEM_STATUS = {
    "status": "INIT",
    "last_update": datetime.now(),
    "is_running": True,
    "current_mode": "HYBRID",
    "fgi": 50.0,
    "avg_p": 0.0,
    "p_rate": 0.0
}
TRADE_DATA_DIRTY = False
last_deep_scan_ts = 0
last_main_loop_time = 0
_TA_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=5)
last_update = 0 # 실시간 소켓 업데이트 시간 기록

# 로그 리다이렉션 백업용
original_stdout = sys.stdout
original_stderr = sys.stderr

#  [FIX: 리   학 공식 교정] 화(KRW) 기 로  개의 코인   부 Volume)  여 확 VWAP 출
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
      # ask_p가 0 경우 0 로 누 륷 방 
      if ask_p <= 0:
        continue #  창 무시 고 음 로 어 
      avail_krw = ask_p * ask_s
      if rem_krw <= avail_krw:
        total_filled_vol += (rem_krw / ask_p)
        rem_krw = 0
        break
      else:
        total_filled_vol += ask_s
        rem_krw -= avail_krw
    if total_filled_vol == 0: return 0.0
    # 5   먹고 이 으 최악 경우 가 하 5  가격으 마 체결 다 정.    최상 가격보  는 음.
    if rem_krw > 0:
      #  금액 재   최하 가격으 최 매수 도
      remaining_buy_price = units[-1]['ask_price']
      # 최악 경우 가 하  재가보다 지지 도 보정
      effective_remaining_price = max(current_price, remaining_buy_price)
      # effective_remaining_price가 0 경우 0 로 누 륷 방 
      if effective_remaining_price <= 0:
        return 0.0
      total_filled_vol += (rem_krw / effective_remaining_price)
    avg_exec_price = buy_amt_krw / total_filled_vol
    # current_price가 0 경우 0 로 누 륷 방 
    if current_price <= 0:
      return 0.0
    slippage_pct = ((avg_exec_price - current_price) / current_price) * 100
    return slippage_pct
  except Exception as e:
        logging.error(f"슬리피지 계산 오류 ({ticker}): {e}")
  return 0.0
def get_exit_plan_preview(ticker: str, curr_data: dict, eval_mode: str = "QUANTUM") -> str:
    """기대 수익과 동적 손절선을 계산하여 AI 분석용 컨텍스트 문자열을 생성합니다."""
    try:
        strat_conf = QUANTUM_STRAT if eval_mode == "QUANTUM" else CLASSIC_STRAT
        tier_params = get_coin_tier_params(ticker, curr_data, strat_config=strat_conf)
        target_mult = tier_params.get('target_atr_multiplier', 4.5)
        sl_cap = tier_params.get('stop_loss', -3.0)
        close_p = safe_float(curr_data.get('close', 1))
        atr_val = safe_float(curr_data.get('ATR') or curr_data.get('atr', 0))
        atr_pct = (atr_val / close_p) * 100 if close_p > 0 else 0
        expected_target = round(atr_pct * target_mult, 2)
        sl_atr_mult = tier_params.get('atr_mult', 2.0)
        dynamic_sl = -(atr_pct * sl_atr_mult)
        final_sl = max(dynamic_sl, sl_cap)
        if abs(final_sl) > (expected_target * 0.7):
            final_sl = -(expected_target * 0.7)
        final_sl = round(final_sl, 2)
        rr_ratio = round(expected_target / abs(final_sl), 2) if final_sl != 0 else 1.0
        return f"기대수익 +{expected_target}% / 예상손절 {final_sl}% (손익비 {rr_ratio}:1)"
    except Exception as e:
        logging.error(f"Exit Plan Preview 생성 오류 ({ticker}): {e}")
        return "데이터 부족으로 산출 불가"

# ── 데이터베이스 유틸리티 (복구됨) ──────────────────────────────────────────────────

async def record_trade_db(ticker, side, price, qty, profit_krw=0, reason="", status="COMPLETED", rating=0, improvement="", pass_score=0, strategy_mode="QUANTUM"):
    """매매 내역을 SQLite DB에 기록합니다."""
    global TRADE_DATA_DIRTY
    try:
        async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
            await db.execute("""
                INSERT INTO trades (ticker, side, price, qty, profit_krw, reason, status, rating, improvement, pass_score, strategy_mode, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ticker, side, float(price), float(qty), float(profit_krw), reason, status, rating, improvement, pass_score, strategy_mode, datetime.now().isoformat()))
            await db.commit()
        TRADE_DATA_DIRTY = True
    except Exception as e:
        logging.error(f"DB 기록 오류 ({ticker}): {e}")

async def save_trade_status_db(status_dict):
    """현재 매매 상태(포지션 등)를 DB에 저장합니다."""
    try:
        async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
            await db.execute("DELETE FROM system_status WHERE key='trade_status'")
            await db.execute("INSERT INTO system_status (key, value) VALUES (?, ?)", 
                           ('trade_status', json.dumps(status_dict)))
            await db.commit()
    except Exception as e:
        logging.error(f"상태 저장 오류: {e}")

async def load_trade_status_db():
    """DB에서 이전 매매 상태를 복구합니다."""
    try:
        async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
            async with db.execute("SELECT value FROM system_status WHERE key='trade_status'") as cursor:
                row = await cursor.fetchone()
                if row: return json.loads(row[0])
    except Exception as e:
        logging.error(f"상태 로드 오류: {e}")
    return {}
def load_config():
  """BASE_PATH를 기준으로 설정 파일을 로드합니다."""
  quantum_path = os.path.join(BASE_PATH, "config_quantum.json")
  classic_path = os.path.join(BASE_PATH, "config_classic.json")
  if not os.path.exists(quantum_path): 
    # 시 모  백 (   역 서 처리   수 정 해  )
    logging.error(f"❌ 설정 파일을 찾을 수 없습니다: {quantum_path}")
    sys.exit(1)
  with open(quantum_path, 'r', encoding='utf-8') as f: quantum_conf = json.load(f)
  with open(classic_path, 'r', encoding='utf-8') as f: classic_conf = json.load(f)
  return quantum_conf, classic_conf, quantum_path, classic_path
def get_strat_for_mode(mode="QUANTUM"):
  if isinstance(mode, str) and mode.upper() == "CLASSIC":
    return CLASSIC_STRAT
  return QUANTUM_STRAT
def get_dynamic_strat_value(key, mode=None, default=None, ticker=None):
  # 0. OPTIMIZED_PARAMS(ScoringParams) 우선 확인
  from dataclasses import asdict
  opt_dict = asdict(OPTIMIZED_PARAMS)
  if key in opt_dict: return opt_dict[key]
  
  if ticker:
    dna = STRAT.get('ticker_dna', {}).get(ticker, {})
    if key in dna: return dna[key]
  if isinstance(mode, str) and mode.upper() in ("CLASSIC", "QUANTUM"):
    config = get_strat_for_mode(mode)
    if key in config: return config.get(key, default)
  return STRAT.get(key, default)
#   [1 계: 리 방어 (Hard Constraints)]  
# 최적 기가 매매 로직 본질 손 는 것을 막는 안전 장치치 니 
# Iteration 12076 최적 기 로 ±10%  트 용 범위 강제 니 
async def save_config_async(config_data, path):
  def _save():
    import time
    import shutil
    # 1. 백업 일 성 ( 안전 장치치)
    bak_path = path + ".bak"
    try:
      if os.path.exists(path):
        shutil.copy2(path, bak_path)
    except:
      pass # 백업 패 무시 고 진행
    # 2. 메인 일 일 기 도 (최 5 시 
    success = False
    last_err = None
    for i in range(5):
      try:
        # 도 금 제 해 시  
        if i > 0: time.sleep(0.3)
        with open(path, 'w', encoding='utf-8') as f: 
          json.dump(config_data, f, indent=4, ensure_ascii=False)
          f.flush()
          os.fsync(f.fileno())
        success = True
        break
      except Exception as e:
        last_err = e
        # 금 륷 률 으므 시 루프 행
        continue
    if not success:
      # 최종 패 백업 서 복구 도
      try:
        if os.path.exists(bak_path):
          shutil.copy2(bak_path, path)
      except:
        pass
      raise last_err
  try:
    await asyncio.to_thread(_save)
  except Exception as e:
        logging.error(f"설정 파일 저장 중 최종 에러: {e}")
QUANTUM_CONF, CLASSIC_CONF, CONFIG_PATH, CLASSIC_CONFIG_PATH = load_config()
API_CONF, TG_CONF = QUANTUM_CONF['api_keys'], QUANTUM_CONF['telegram']
#  [ 역 어 객체] 스 부  캔 충돌 방 
SCAN_LOCK = asyncio.Lock()
GLOBAL_API_SEMAPHORE = asyncio.Semaphore(15) #  시 API 출 한 향 (15 권장)
INDICATOR_CACHE = {} 
INDICATOR_CACHE_LOCK = asyncio.Lock()
INDICATOR_CACHE_SEC = 60 
OHLCV_CACHE = {} 
OHLCV_CACHE_LOCK = asyncio.Lock()
# [데이터 동기 설정]
last_auto_optimize_time = 0 
consecutive_empty_scans = 0 
REALTIME_PRICES = {}
REALTIME_PRICES_TS = {}
INDICATOR_CACHE = {}
last_sell_time = {}
BALANCE_CACHE = {'data': [], 'timestamp': 0}
BALANCE_CACHE_SEC = 2
SYSTEM_STATUS = {"status": "INIT", "last_update": datetime.now()}
background_tasks = set()
#  [FIX: API Rate Limit 방어 MTF 캐싱 입]
MTF_CACHE = {}
MTF_CACHE_SEC = 300
SCAN_TIMESTAMP_FILE = os.path.join(BASE_PATH, "last_scan.txt")
QUANTUM_STRAT = QUANTUM_CONF['strategy']
CLASSIC_STRAT = CLASSIC_CONF['strategy']
STRAT = dict(QUANTUM_STRAT)
STRAT['tickers'] = sorted(list(set(QUANTUM_STRAT.get('tickers', []) + CLASSIC_STRAT.get('tickers', []))))
STRAT['external_dashboard_url'] = "http://localhost:8080" #   속  보 주소 ( 제 트 8080 맞춤)
upbit = pyupbit.Upbit(API_CONF['access_key'], API_CONF['secret_key'])
bot = telegram.Bot(token=TG_CONF['token'])
client = genai.Client(api_key=API_CONF['gemini_api_key'], http_options=types.HttpOptions(api_version='v1beta'))
MODEL_ID = 'gemini-2.5-flash-lite'
GLOBAL_COOLDOWN, last_ai_call_time = 0.5, 0 
last_coin_ai_call, last_sell_time, last_buy_time = {}, {}, {}
trade_data = {} #  [추 ]  방패 먼  워 러 천 차단!
last_global_buy_time = 0 
#  [BTC 급등 비정 캔 리  번 1%+ 상 파 크 즉시 트 매수 기회 선 한 태 변 
BTC_SURGE_TRIGGERED = False   #  루프가 인 는 리 래 
BTC_PRICE_WINDOW = {}      # {timestamp: price} 라 딩 도 
BTC_SURGE_COOLDOWN_TS = 0    # 마  리 각 ( 속 리 방 )
BTC_SURGE_THRESHOLD = 1.5    # 리 기  승 (%) - AI OPTIMIZE 조정 가 
LATEST_TOP_PASS_SCORE = 0
BOT_START_TIME = time.time() 

# [데이터 동기 설정]
last_auto_optimize_time = 0 
consecutive_empty_scans = 0 
REALTIME_PRICES = {}
REALTIME_PRICES_TS = {}
REALTIME_CVD = {} #  시 Taker CVD  소
LATEST_SCAN_RESULTS = {} #  모든 종목 최신 캐 보 (  보 출 
LATEST_SCAN_TS = 0
API_FATAL_ERRORS = 0 #  API 속 패 카운 
is_running = True
last_update_id = None
SYSTEM_STATUS = "정상 감시 중"
background_tasks = set()
INDICATOR_CACHE_LOCK = asyncio.Lock()
#  [FIX: API Rate Limit 방어 MTF 캐싱 입]
MTF_CACHE = {}
MTF_CACHE_SEC = 300
instance_lock = None #  [Pylance 벽 방어] 미선 태 global 참조 발생 는 경고 결 기 해 역 초기 
TRADE_DATA_DIRTY = False # 메모 이  변경되 는지 인 는 래 
#  [  보 용 버 팅]
app = FastAPI(title="ATS Command Center", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
#  PyInstaller 경 서 빌트 된 _MEIPASS 시 더 서 적 일 찾습 다.
if getattr(sys, 'frozen', False):
  dashboard_dir = os.path.join(sys._MEIPASS, "dashboard")
else:
  dashboard_dir = os.path.join(BASE_PATH, "dashboard")
@app.get("/api/dashboard")
async def api_get_dashboard(timeframe: str = 'all'):
  wins, losses, total_profit = 0, 0, 0.0
  chart_data = []
  avg_pl_ratio = 1.0 
  try:
    async with aiosqlite.connect(DB_FILE, timeout=5.0) as db:
      async with db.execute("SELECT COUNT(CASE WHEN profit_krw > 0 THEN 1 END), COUNT(CASE WHEN profit_krw <= 0 THEN 1 END), SUM(profit_krw) FROM trades WHERE side='SELL'") as cursor:
        stat_row = await cursor.fetchone()
        if stat_row:
          wins, losses = stat_row[0] or 0, stat_row[1] or 0
          total_profit = stat_row[2] or 0.0
      # [P/L Ratio 계산]
      query_pl = """
        SELECT 
          AVG(CASE WHEN profit_krw > 0 THEN profit_krw END),
          AVG(CASE WHEN profit_krw <= 0 THEN ABS(profit_krw) END)
        FROM trades WHERE side='SELL'
      """
      async with db.execute(query_pl) as cursor:
        pl_row = await cursor.fetchone()
        if pl_row and pl_row[1] and pl_row[1] > 0:
          avg_pl_ratio = (pl_row[0] or 0.0) / pl_row[1]
        elif pl_row and pl_row[0]:
          avg_pl_ratio = 3.0 # 실 음
      now = datetime.now()
      if timeframe == 'day': cutoff = now - timedelta(days=1)
      elif timeframe == 'week': cutoff = now - timedelta(days=7)
      else: cutoff = now - timedelta(days=365)
      cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')
      async with db.execute("SELECT SUM(profit_krw) FROM trades WHERE side='SELL' AND timestamp < ", (cutoff_str,)) as cursor:
        prev_sum_row = await cursor.fetchone()
        cumulative_profit = prev_sum_row[0] or 0.0
      query = "SELECT timestamp, profit_krw FROM trades WHERE side='SELL' AND timestamp >=  ORDER BY timestamp ASC LIMIT 1000"
      async with db.execute(query, (cutoff_str,)) as cursor:
        async for row in cursor:
          profit = safe_float(row[1])
          cumulative_profit += profit
          chart_data.append({"time": str(row[0]), "profit": cumulative_profit})
  except Exception as e:
        logging.error(f"대시보드 DB 쿼리 오류: {e}")
  total = wins + losses
  win_rate = (wins / total * 100) if total > 0 else 0
  active_trades = []
  #  [ 정] 비 시 고(balances) 기반 로 이  보
  balances = BALANCE_CACHE['data']
  if not isinstance(balances, list): balances = []
  # 고 커별로 매칭 기 게 셔 리 변 
  held_balances = {f"KRW-{b['currency']}": b for b in balances if b['currency'] != 'KRW'}
  for t_name, t_data in trade_data.items():
    if t_name not in held_balances: continue # 령  방 
    coin = held_balances[t_name]
    # 단가  량 추출 ( 비 시 고 선)
    avg_p = safe_float(coin.get('avg_buy_price'))
    amount = safe_float(coin.get('balance')) + safe_float(coin.get('locked'))
    cur_p = safe_float(REALTIME_PRICES.get(t_name, avg_p))
    # 제 자 가치  재 가 계산
    buy_amount_krw = avg_p * amount
    current_amount_krw = cur_p * amount
    pnl = ((cur_p - avg_p) / avg_p) * 100 if avg_p > 0 else 0
    active_trades.append({
      "ticker": t_name,
      "entry_price": avg_p,
      "current_price": cur_p,
      "amount": amount,
      "buy_amount": buy_amount_krw,
      "current_amount": current_amount_krw,
      "pnl_pct": pnl,
      "score": t_data.get('pass_score', 80),
      "mode": t_data.get('strategy_mode', 'QUANTUM'),
            "reason": t_data.get('buy_reason', '자동 매수')
    })
  # [ 시 산 계산]
  total_asset_bal = 0.0
  cash_bal = 0.0
  if isinstance(balances, list):
    for b in balances:
      c = b.get('currency', '')
      b_val = safe_float(b.get('balance')) + safe_float(b.get('locked'))
      if c == 'KRW':
        cash_bal = b_val
        total_asset_bal += b_val
      else:
        price = REALTIME_PRICES.get(f"KRW-{c}", safe_float(b.get('avg_buy_price')))
        total_asset_bal += (b_val * price)
  return {
    "status": "success",
    "system_status": SYSTEM_STATUS,
    "btc_trend": BTC_SHORT_CACHE['data']['trend'],
    "win_rate": round(win_rate, 2),
    "total_profit": total_profit,
    "total_balance": round(total_asset_bal, 0),
    "available_cash": round(cash_bal, 0),
    "avg_pl_ratio": round(avg_pl_ratio, 2),
    "active_trades": active_trades,
    "chart_data": chart_data
  }
@app.get("/api/history")
async def api_get_history():
  history_data = []
  try:
    async with aiosqlite.connect(DB_FILE, timeout=5.0) as db:
      query = "SELECT timestamp, ticker, side, price, profit_krw, reason, pass_score, rating, strategy_mode FROM trades ORDER BY id DESC LIMIT 100"
      async with db.execute(query) as cursor:
        async for row in cursor:
          side = str(row[2])
          history_data.append({
            "time": str(row[0]),
            "ticker": str(row[1]),
            "side": side,
            "price": safe_float(row[3]),
            "profit_krw": safe_float(row[4]),
                        "reason": str(row[5]) if row[5] else "사유 없음", 
            "score": safe_float(row[7]),
            "mode": str(row[8]) if row[8] else "UNKNOWN"
          })
  except Exception as e:
        logging.error(f"히스토리 DB 쿼리 오류: {e}")
  return {"history": history_data}
@app.get("/api/scanner")
async def api_get_scanner():
  results = []
  # 셔 리 리스 태 변 하 송
  for t, info in LATEST_SCAN_RESULTS.items():
    results.append({
      "ticker": t,
      "score": info["score"],
      "reason": info["reason"],
      "price": info["price"],
      "mode": info["mode"],
      "mtf": info["mtf"],
      "fatal_flaw": info.get("reason", "PASS") #  [ 정] 결격 유 명시 달
    })
  # 수   으 렬
  results.sort(key=lambda x: x['score'], reverse=True)
  return {"scanner": results, "timestamp": LATEST_SCAN_TS}
@app.get("/api/market-history")
async def api_get_market_history():
  history = []
  try:
    async with aiosqlite.connect(DB_FILE, timeout=5.0) as db:
      # 최근 48 간 이 조회
      async with db.execute("SELECT timestamp, fgi_value, btc_price, regime_mode FROM market_history ORDER BY id DESC LIMIT 48") as cursor:
        rows = await cursor.fetchall()
        for row in rows:
          history.append({
            "time": row[0],
            "fgi": row[1],
            "btc_price": row[2],
            "regime": row[3]
          })
  except Exception as e:
        logging.error(f"설정 파일 저장 중 최종 에러: {e}")
  # 가 방향 차트 해 간 으 반전
  return {"history": list(reversed(history))}
@app.post("/api/scanner/refresh")
async def api_scanner_refresh():
  #  [추 ] 즉시 수 검   리거합 다.
  asyncio.create_task(run_full_scan(is_deep_scan=True))
  return {"status": "success", "message": "점수 갱신(전수검사) 태스크가 시작되었습니다."}
@app.post("/api/trade")
async def api_trade_manual(request: Request):
  global trade_data, TRADE_DATA_DIRTY
  data = await request.json()
  ticker = data.get("ticker")
  action = data.get("action") # "buy" or "sell"
  if not ticker or not action:
    return {"status": "error", "message": "Missing ticker or action"}
  try:
    if action == "sell":
      # 1. 고 조회 즉시 장가 매도
      balances = await execute_upbit_api(upbit.get_balances)
      coin = next((b for b in balances if f"KRW-{b['currency']}" == ticker), None)
      if not coin:
                return {"status": "error", "message": "현재가를 불러올 수 없어 매수를 중단합니다."}
      qty = safe_float(coin['balance']) + safe_float(coin['locked'])
      if qty <= 0:
                return {"status": "error", "message": "현재가를 불러올 수 없어 매수를 중단합니다."}
      # 매수 점 수 계 도
      t_data = trade_data.get(ticker, {})
      p_score = t_data.get('pass_score', 0)
      # 매도 행
      await execute_upbit_api(upbit.sell_market_order, ticker, qty)
      # 익 계산 (보고 용)
      avg_p = safe_float(coin['avg_buy_price'])
      real_p = safe_float(REALTIME_PRICES.get(ticker, avg_p))
      invested = qty * avg_p * 1.0005
      earned = qty * real_p * 0.9995
      p_krw = earned - invested
      m = trade_data[ticker].get('strategy_mode', 'UNKNOWN') if ticker in trade_data else 'UNKNOWN'
      await record_trade_db(ticker, 'SELL', real_p, qty, profit_krw=p_krw, reason="[대시보드 수동매도]", pass_score=p_score, strategy_mode=m)
      if ticker in trade_data:
        del trade_data[ticker]
        global TRADE_DATA_DIRTY
        TRADE_DATA_DIRTY = True
        await send_msg(f"🛑 <b>대시보드 수동 매도 완료</b>: {ticker}\n- 예상 수익금: {p_krw:,.0f}원")
      return {"status": "success", "message": f"{ticker} 매도 주문이 완료되었습니다."}
    elif action == "buy":
      # 1. 도 체크
      max_concurrent = STRAT.get('max_concurrent_trades', GLOBAL_MAX_POSITIONS)
      if len(trade_data) >= max_concurrent:
                return {"status": "error", "message": f"매수 슬롯 한도({max_concurrent}개)에 도달했습니다."}
      # 2. 시 기  보 득
      cur_p = safe_float(REALTIME_PRICES.get(ticker))
      if cur_p <= 0:
        # 소 가격이 으 REST API 도
        cur_p = safe_float(await execute_upbit_api(pyupbit.get_current_price, ticker))
      if cur_p <= 0:
                return {"status": "error", "message": "현재가를 불러올 수 없어 매수를 중단합니다."}
      # 3. 매수 행 (기본 정 금액 용)
      buy_amt = STRAT.get('base_trade_amount', 5000)
      await execute_upbit_api(upbit.buy_market_order, ticker, buy_amt)
      # 량  (기록 
      qty = buy_amt / cur_p if cur_p > 0 else 0
      # DB 기록  림 ( 캐 에 수가 으 가 다 고, 으 기본 80 부 
      manual_score = LATEST_SCAN_RESULTS.get(ticker, {}).get('score', 80.0)
      #  [버그 스] eval_m 변 의 DB 기록(record_trade_db) 출 으 어 립 다.
      eval_m = "QUANTUM" if "Quantum" in SYSTEM_STATUS else "CLASSIC"
      await record_trade_db(ticker, 'BUY', cur_p, qty, profit_krw=0, reason="[대시보드 수동매수]", status="ENTERED", pass_score=manual_score, strategy_mode=eval_m) 
      # 어 라미터 미리 계산
      dummy_curr = {'close': cur_p, 'ATR': 0, 'volume': 0} # 단가 기 최소 보
      t_params = get_coin_tier_params(ticker, dummy_curr, strat_config=get_strat_for_mode(eval_m))
      #  [버그 스] 메인 진(evaluate_sell_conditions) 구 는 벽 규격 로 주입
      trade_data[ticker] = {
        'high_p': cur_p, 
        'entry_atr': cur_p * 0.02, # 기본 가 ATR 팅 (2%)
        'guard': False,
        'buy_ind': dummy_curr, 
        'last_notified_step': 0, 
        'buy_ts': time.time(),
        'exit_plan': {
          "target_atr_multiplier": t_params.get('target_atr_multiplier', 4.5),
          "stop_loss": t_params.get('stop_loss', -3.0),
          "atr_mult": t_params.get('atr_mult', 2.0),
          "timeout": t_params.get('timeout_candles', 8),
          "adaptive_breakeven_buffer": t_params.get('adaptive_breakeven_buffer', 0.003)
        }, 
                'buy_reason': "[대시보드 수동매수]", 
        'btc_buy_price': safe_float(REALTIME_PRICES.get('KRW-BTC', 0)),
        'pass_score': manual_score, 
        'is_runner': False, 
        'score_history': [manual_score],
        'strategy_mode': eval_m,
        'last_ind_update_ts': time.time()
      }
      TRADE_DATA_DIRTY = True
      # 즉시 DB 속 보
      await save_trade_status_db(trade_data)
      await send_msg(f"✅ <b>대시보드 수동 매수 완료</b>: {ticker}\n- 매수 단가: {cur_p:,.0f}원\n- 매수 금액: {buy_amt:,.0f}원")
    return {"status": "success", "message": f"{ticker} 매수 주문 및 관리가 시작되었습니다."}
  except Exception as e:
        logging.error(f"대시보드 매매 오류 ({ticker}): {e}")
        return {"status": "error", "message": f"매매 처리 중 오류 발생: {str(e)}"}
  return {"status": "error", "message": "Invalid action"}
@app.get("/api/logs")
async def api_get_logs():
  try:
    # log_filepath is defined globally at line 136
    if not os.path.exists(log_filepath):
      return {"logs": "Log file not found."}
    with open(log_filepath, 'r', encoding='utf-8') as f:
      lines = f.readlines()
      # Tail last 200 lines
      last_lines = lines[-200:] if len(lines) > 200 else lines
      return {"logs": "".join(last_lines)}
  except Exception as e:
    return {"logs": f"Error reading logs: {e}"}
@app.post("/api/control")
async def api_control_system(request: Request):
  data = await request.json()
  action = data.get("action")
  if action == "restart":
    logging.warning("🔄 Dashboard requested RESTART...")
    asyncio.create_task(shutdown_after_delay(0))
    return {"status": "success", "message": "Restarting engine..."}
  elif action == "shutdown":
    logging.warning("🛑 Dashboard requested FULL SHUTDOWN...")
    asyncio.create_task(shutdown_after_delay(99))
    return {"status": "success", "message": "Shutting down system..."}
  return {"status": "error", "message": "Invalid action"}
async def shutdown_after_delay(code):
  await asyncio.sleep(1.5)
  os._exit(code)
class SettingsUpdate(BaseModel):
  max_concurrent_trades: int
  base_trade_amount: int
  max_slippage_pct: float
@app.get("/api/settings")
async def api_get_settings():
  # Return core strategy settings from QUANTUM_CONF (assumed shared with CLASSIC_CONF for core ones)
  st = QUANTUM_CONF.get("strategy", {})
  return {
    "max_concurrent_trades": st.get("max_concurrent_trades", GLOBAL_MAX_POSITIONS),
    "base_trade_amount": st.get("base_trade_amount", 5000),
    "max_slippage_pct": st.get("max_slippage_pct", 0.5),
    "deep_scan_interval": st.get("deep_scan_interval", 900)
  }
@app.post("/api/settings")
async def api_post_settings(data: SettingsUpdate):
  try:
    global QUANTUM_CONF, CLASSIC_CONF, STRAT, CLASSIC_STRAT
    QUANTUM_CONF.setdefault("strategy", {})
    QUANTUM_CONF["strategy"]["max_concurrent_trades"] = data.max_concurrent_trades
    QUANTUM_CONF["strategy"]["base_trade_amount"] = data.base_trade_amount
    QUANTUM_CONF["strategy"]["max_slippage_pct"] = data.max_slippage_pct
    CLASSIC_CONF.setdefault("strategy", {})
    CLASSIC_CONF["strategy"]["max_concurrent_trades"] = data.max_concurrent_trades
    CLASSIC_CONF["strategy"]["base_trade_amount"] = data.base_trade_amount
    CLASSIC_CONF["strategy"]["max_slippage_pct"] = data.max_slippage_pct
    # 일 동 기록 (비동기로 안전 장치게)
    await save_config_async(QUANTUM_CONF, CONFIG_PATH)
    await save_config_async(CLASSIC_CONF, CLASSIC_CONFIG_PATH)
    # 봇의 메모 역 변 에 바로 복사 여 시 반영!
    if 'STRAT' in globals() and isinstance(STRAT, dict):
      STRAT["max_concurrent_trades"] = data.max_concurrent_trades
      STRAT["base_trade_amount"] = data.base_trade_amount
      STRAT["max_slippage_pct"] = data.max_slippage_pct
    if 'CLASSIC_STRAT' in globals() and isinstance(CLASSIC_STRAT, dict):
      CLASSIC_STRAT["max_concurrenta_trades"] = data.max_concurrent_trades
      CLASSIC_STRAT["base_trade_amount"] = data.base_trade_amount
      CLASSIC_STRAT["max_slippage_pct"] = data.max_slippage_pct
      logging.info("🌐 웹 대시보드(Settings)에서 봇의 핵심 파라미터가 실시간 오버라이드 되었습니다.")
    return {"status": "success", "message": "Settings perfectly updated and hot-reloaded!"}
  except Exception as e:
    logging.error(f"시장 히스토리 조회 오류: {e}")
    return {"status": "error", "message": str(e)}
if os.path.exists(dashboard_dir):
  app.mount("/", StaticFiles(directory=dashboard_dir, html=True), name="static")
else:
    logging.warning("⚠️ 대시보드 정적 파일 폴더가 없습니다. 웹 UI를 불러올 수 없습니다.")
async def run_fastapi_server():
  try:
    logging.warning("🌐 대시보드 서버 가동 중 (접속: http://localhost:8080)")
    #  버가 준비되 을 것으 상 는 점 브라   동 로 니 
    def open_browser():
      time.sleep(2) # 버가 기동 간 줍니 
      webbrowser.open("http://localhost:8080")
    asyncio.create_task(asyncio.to_thread(open_browser))
    #  uvicorn 고유 로거가 PyInstaller 경 stdout 충돌 여 래   발   log_config=None 로 비활 화
    config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_config=None)
    server = uvicorn.Server(config)
    await server.serve()
  except Exception as e:
        logging.error(f"설정 파일 저장 중 최종 에러: {e}")
#  [ 정 코드]  하 가 " 위치 먼  니 
async def db_flush_task():
  global TRADE_DATA_DIRTY, trade_data
  while True:
    await asyncio.sleep(5.0) 
    if TRADE_DATA_DIRTY:
      #  1. 른 이 켜기 에  먼  위치  니 
      TRADE_DATA_DIRTY = False 
      try:
        #  2. 심 고 DB  하  니 
        await save_trade_status_db(trade_data) 
      except Exception as e:
        #  3. 만약 패 다 시 위치 켜서 음 을 립 다.
        TRADE_DATA_DIRTY = True 
        logging.error(f"DB 일괄 저장 중 에러: {e}")
async def cache_cleanup_task():
  while True:
    try:
      await asyncio.sleep(3600)
      await clean_unused_caches()
    except Exception as e:
      logging.error(f"시장 히스토리 조회 오류: {e}")
      await asyncio.sleep(60)
def robust_clean(data):
  if isinstance(data, dict): return {k: robust_clean(v) for k, v in data.items()}
  elif isinstance(data, list): return [robust_clean(v) for v in data]
  #  [개선] 수 8 리 -> 4 리 줄여 AI 롬 트 큰 약   집중
  elif isinstance(data, (int, float)): return 0 if pd.isna(data) or np.isinf(data) else round(data, 4)
  else: return data
from typing import Any # 일  에 추 시거나 기 어 니 
#  [ 규 추 ] 비 KRW 마켓   위(Tick Size) 계산

async def send_msg(text):
  if not text: return
  text_str = str(text)
  for attempt in range(3):
    try:
      await bot.send_message(
        chat_id=TG_CONF['chat_id'], 
        text=text_str, 
        parse_mode='HTML',
        read_timeout=20.0,
        write_timeout=20.0,
        connect_timeout=20.0
      )
      return
    except Exception as e:
      if attempt < 2: 
        await asyncio.sleep(2.0)
      else: 
        err_name = type(e).__name__
        logging.error(f"❌ TG 전송 실패 [{err_name}]: {e}")
RETRY_INTERVAL_SECONDS = 2 

async def execute_upbit_api(api_call, *args, **kwargs):
  global API_FATAL_ERRORS
  for attempt in range(5):
    try:
      res = await asyncio.to_thread(api_call, *args, **kwargs)
      API_FATAL_ERRORS = 0
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
  API_FATAL_ERRORS += 1
  logging.error(f"🚫 API 호출 5회 연속 실패. 포기합니다: {getattr(api_call, '__name__', 'Unknown API')}")
  return None

#  비동 SQLite DB 정 (BASE_PATH 용)
# DB_FILE  단 서   의 
async def init_db():
  async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("""CREATE TABLE IF NOT EXISTS trades (
      id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, ticker TEXT, side TEXT, 
      price REAL, qty REAL, profit_krw REAL, reason TEXT, status TEXT, rating INTEGER, improvement TEXT, pass_score INTEGER, strategy_mode TEXT)""")
    try: await db.execute("ALTER TABLE trades ADD COLUMN is_reported INTEGER DEFAULT 0")
    except: pass
    await db.commit()
#  [개선 2- & 1- RAG 컨텍 트 추출 용 수 (중복 출 방  극단   함)
async def get_rag_context():
  try:
    async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
      db.row_factory = aiosqlite.Row
      #  1. 가 게 익  (최 2 
      c1 = await db.execute("SELECT ticker, profit_krw, reason FROM trades WHERE side='SELL' AND profit_krw > 0 ORDER BY profit_krw DESC LIMIT 2")
      best_wins = [dict(r) for r in await c1.fetchall()]
      #  2. 가 게 실  (최 2 
      c2 = await db.execute("SELECT ticker, profit_krw, reason FROM trades WHERE side='SELL' AND profit_krw < 0 ORDER BY profit_krw ASC LIMIT 2")
      worst_losses = [dict(r) for r in await c2.fetchall()]
      #  3. 가 최근 거래 (최 2 
      c3 = await db.execute("SELECT ticker, profit_krw, reason FROM trades WHERE side='SELL' ORDER BY id DESC LIMIT 2")
      recent = [dict(r) for r in await c3.fetchall()]
      return f"\n[RAG CONTEXT: Learn from Past Trades]\n- Biggest Wins: {best_wins}\n- Biggest Losses: {worst_losses}\n- Recent Trades: {recent}\n* CRITICAL: Avoid setups identical to the 'Biggest Losses'."
  except Exception as e:
    logging.error(f"RAG 데이터 추출 실패: {e}")
    return ""
#  [Pylance 방어] profit_krw 기본값을 0.0(float) 로 명시 여 러 결 니 
async def get_performance_stats_db():
  async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
    db.row_factory = aiosqlite.Row 
    #  [메모 수 벽 차단] 가 최근 1000건의 매매 롤링(Rolling) 방식 로 가 옵 다.
    async with db.execute("SELECT ticker, side, price, amount, profit_krw, reason, status, rating, improvement FROM trades WHERE side='SELL' ORDER BY id DESC LIMIT 1000") as cursor:
      rows = await cursor.fetchall()
      rows = list(rows)
  total_cnt = len(rows)
  history = [dict(row) for row in rows]
  wins = [t for t in history if t['profit_krw'] > 0]
  losses = [t for t in history if t['profit_krw'] <= 0]
  win_rate = (len(wins) / total_cnt * 100) if total_cnt >= 1 and total_cnt > 0 else 50.0
  total_profit = sum(t['profit_krw'] for t in history)
  return win_rate, total_cnt, len(wins), total_profit, wins, losses

async def clean_unused_caches():
  global OHLCV_CACHE, INDICATOR_CACHE, STRAT, trade_data
  active_tickers = set(STRAT.get('tickers', []) + list(trade_data.keys()) + ["KRW-BTC"])
  async with OHLCV_CACHE_LOCK:
    for t in list(OHLCV_CACHE.keys()):
      if t not in active_tickers:
        del OHLCV_CACHE[t]
  #  [버그 스] INDICATOR_CACHE: Lock 보호 에 안전 장치게 
  async with INDICATOR_CACHE_LOCK:
    for t in list(INDICATOR_CACHE.keys()):
      if t not in active_tickers:
        del INDICATOR_CACHE[t]
  #  [버그 스] 각각 셔 리 립 으 회 며 좀 코인 이   벽 게  니 
  for t in list(REALTIME_CVD.keys()):
    if t not in active_tickers: del REALTIME_CVD[t]
  for t in list(REALTIME_PRICES_TS.keys()):
    if t not in active_tickers: del REALTIME_PRICES_TS[t]
  for t in list(REALTIME_PRICES.keys()):
    if t not in active_tickers: del REALTIME_PRICES[t]

async def update_top_volume_tickers():
  global STRAT
  try:
    tickers = await execute_upbit_api(pyupbit.get_tickers, fiat="KRW")
    if not tickers: return STRAT.get('tickers', [])
    if isinstance(tickers, tuple): tickers = tickers[0]
    url = f"https://api.upbit.com/v1/ticker markets={','.join(tickers)}"
    try:
      async with httpx.AsyncClient() as client:
        res = await client.get(url, timeout=5.0)
      if res.status_code != 200:
        return STRAT.get('tickers', [])
      json_response = res.json()
    except Exception as e:
      logging.error(f"❌ httpx 요청 실패: {e}")
      return STRAT.get('tickers', [])
    if not isinstance(json_response, list):
      return STRAT.get('tickers', [])
    sorted_data = sorted(json_response, key=lambda x: x.get('acc_trade_price_24h', 0), reverse=True)
    exclude = ['KRW-USDT', 'KRW-USDC', 'KRW-TUSD', 'KRW-DAI']
    top_tickers = [x['market'] for x in sorted_data if isinstance(x, dict) and x.get('market') not in exclude][:50]
    balances = await execute_upbit_api(upbit.get_balances)
    if isinstance(balances, list):
      held = [f"KRW-{b['currency']}" for b in balances if isinstance(b, dict) and b.get('currency') != "KRW" and (float(b.get('balance', 0)) + float(b.get('locked', 0))) * float(b.get('avg_buy_price', 0)) >= 5000]
      for h in held:
        if h in trade_data and h not in top_tickers: 
          top_tickers.append(h)
    STRAT['tickers'] = top_tickers
    QUANTUM_CONF['strategy']['tickers'] = top_tickers
    CLASSIC_CONF['strategy']['tickers'] = top_tickers
    await save_config_async(QUANTUM_CONF, CONFIG_PATH)
    await save_config_async(CLASSIC_CONF, CLASSIC_CONFIG_PATH)
    await clean_unused_caches() # 불필 한 OHLCV/지 캐시 리
    return top_tickers
  except Exception as e:
    logging.error(f"❌ update_top_volume_tickers 오류: {e}")
    await clean_unused_caches() # 류가 도 캐시 리 도
    return STRAT.get('tickers', [])
FGI_CACHE = {"data": {"fear_and_greed": "50 (Neutral)"}, "timestamp": 0}
async def get_market_regime():
  global FGI_CACHE
  #  1. 캐싱 입: 1 간(3600  안   API 찌르지 고 기억 둔 값을 용 ( 도 방 )
  if time.time() - FGI_CACHE['timestamp'] < 3600:
    return FGI_CACHE['data']
  try:
    #  2. 무한 시 execute_upbit_api) 거: 비   닌   이 이므 직통 로 찌르 패 면 깔끔 게 기
    try:
      async with httpx.AsyncClient() as client:
        fgi_res = await client.get("https://api.alternative.me/fng/", timeout=5.0)
      if fgi_res.status_code != 200:
        return FGI_CACHE['data']
      fgi_data = fgi_res.json()
    except Exception:
      return FGI_CACHE['data']
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
    #  [추 ] DB 매시 장 황 기록 (  보 차트 
    try:
      async with aiosqlite.connect(DB_FILE, timeout=5.0) as db:
        # 마  기록 인
        async with db.execute("SELECT timestamp FROM market_history ORDER BY id DESC LIMIT 1") as cursor:
          row = await cursor.fetchone()
          last_hour = row[0][:13] if row else "" # YYYY-MM-DD HH
          current_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
          current_hour = current_ts[:13]
          if current_hour != last_hour:
            btc_p = safe_float(REALTIME_PRICES.get('KRW-BTC', 0))
            # btc_p가 0 면 REST 가 오 
            if btc_p == 0: btc_p = safe_float(await execute_upbit_api(pyupbit.get_current_price, 'KRW-BTC'))
            fgi_int = int(fgi_value)
            # Determine regime mode (RSI based logic)
            btc_data = await get_btc_short_term_data()
            btc_rsi = btc_data.get('rsi', 50.0)
            if btc_rsi <= 42: regime = "CLASSIC"
            elif btc_rsi >= 58: regime = "QUANTUM"
            elif fgi_int <= 35: regime = "CLASSIC"
            elif fgi_int >= 65: regime = "QUANTUM"
            else: regime = "HYBRID"
            await db.execute("INSERT INTO market_history (timestamp, fgi_value, btc_price, regime_mode) VALUES (?, ?, ?, ?)",
                    (current_ts, fgi_int, btc_p, regime))
            await db.commit()
            logging.info(f"📊 시장 상황 기록 완료: FGI {fgi_int}, Regime {regime}")
    except Exception as db_e:
            logging.error(f"⚠️ 시장 상황 DB 기록 실패: {db_e}")
    return FGI_CACHE['data']
  except Exception as e:
    # 러 발생 기존 캐싱 값을 반환 여 봇이  멈추지 도 방어
    logging.error(f"⚠️ FGI 지수 갱신 실패 (기존 값 유지): {e}")
    return FGI_CACHE['data']
#  [ 로 추 코드] 시 소 가 신 진
async def websocket_ticker_task():
  global REALTIME_PRICES, STRAT, trade_data, REALTIME_CVD
  uri = "wss://api.upbit.com/websocket/v1"
  #  [추 ] certifi 용 안전 장치SSL/TLS 컨텍 트 성
  ssl_context = ssl.create_default_context(cafile=certifi.where())
  while True:
    try:
      #  [ 정] websockets.connect ssl=ssl_context 라미터 추 !
      async with websockets.connect(uri, ping_interval=60, ping_timeout=30, ssl=ssl_context) as websocket:
        logging.info("🌐 업비트 실시간 웹소켓 연결 성공 (Ticker & Trade)")
        # 재 감시 야 종목 리스 (보유종목 + 캔  + BTC)
        current_tickers = list(set(STRAT.get('tickers', []) + ["KRW-BTC"] + list(trade_data.keys())))
        #  [개선 2- ticker  께 'trade'(체결) 이 도 구독 니 
        subscribe_fmt = [
          {"ticket": "ats_hybrid_ws"},
          {"type": "ticker", "codes": current_tickers, "isOnlyRealtime": True},
          {"type": "trade", "codes": current_tickers, "isOnlyRealtime": True}
        ]
        await websocket.send(json.dumps(subscribe_fmt))
        last_subscribed_tickers = set(current_tickers)
        ws_recv_count = 0
        ws_last_check_ts = time.time()
        while True:
          #  1. 중간 코인 매수/매도 거 캔  이 바뀌면 적 로 소 ' 구 처리
          new_tickers = set(STRAT.get('tickers', []) + ["KRW-BTC"] + list(trade_data.keys()))
          if new_tickers != last_subscribed_tickers:
            subscribe_fmt = [
              {"ticket": "ats_hybrid_ws"},
              {"type": "ticker", "codes": list(new_tickers), "isOnlyRealtime": True},
              {"type": "trade", "codes": list(new_tickers), "isOnlyRealtime": True}
            ]
            await websocket.send(json.dumps(subscribe_fmt))
            last_subscribed_tickers = new_tickers
            logging.info(f"🔄 웹소켓 감시 종목 동적 갱신 (완료 {len(new_tickers)}개)")
          #  [Half-Open 감 ] 120초간 이 신   으 '죽  결' 간주 고 접 도
          now_ws = time.time()
          if now_ws - ws_last_check_ts >= 120:
            if ws_recv_count == 0:
              logging.warning("⚠️ 웹소켓 수신 지연(120초) 감지. 강제 재연결을 시도합니다.")
              break # Inner loop 출 -> outer while: reconnect
            ws_recv_count = 0
            ws_last_check_ts = now_ws
          #  2. 이 신 (Timeout 짧게 주어 루프가 멈추지 고 종목 변경을 체크 게 
          try:
            raw_data = await asyncio.wait_for(websocket.recv(), timeout=1.0)
            ws_recv_count += 1
            #  [CPU 최적 python json 모듈  bytes 체 싱   decode() 산  분기 철거
            data = json.loads(raw_data) if isinstance(raw_data, (bytes, str)) else raw_data
            # dict  인 근 (  체커  
            if isinstance(data, dict):
              code_str = str(data.get('code'))
              if data.get('type') == 'ticker':
                price = float(data['trade_price'])
                REALTIME_PRICES[code_str] = price
                REALTIME_PRICES_TS[code_str] = time.time()
                await asyncio.sleep(0)
                #  [BTC 급등 감 ] BTC 가격을 라 딩 도 에 적
                if code_str == 'KRW-BTC':
                  global BTC_SURGE_TRIGGERED, BTC_PRICE_WINDOW, BTC_SURGE_COOLDOWN_TS
                  now_ws = time.time()
                  BTC_PRICE_WINDOW[now_ws] = price
                  #  1 는 이 만  (60 도 
                  cutoff = now_ws - 60
                  BTC_PRICE_WINDOW = {t: p for t, p in BTC_PRICE_WINDOW.items() if t >= cutoff}
                  #  1 기  vs 재 가격으 승 정
                  if len(BTC_PRICE_WINDOW) >= 2:
                    oldest_ts = min(BTC_PRICE_WINDOW.keys())
                    oldest_price = BTC_PRICE_WINDOW[oldest_ts]
                    if oldest_price > 0:
                      pct_change = (price - oldest_price) / oldest_price * 100
                      cooldown_ok = (now_ws - BTC_SURGE_COOLDOWN_TS) >= 180 #  3 쿨다 
                      if pct_change >= BTC_SURGE_THRESHOLD and not BTC_SURGE_TRIGGERED and cooldown_ok:
                        BTC_SURGE_TRIGGERED = True
                        BTC_SURGE_COOLDOWN_TS = now_ws
                        logging.warning(f"🚨 BTC 급등 감지! 1분 +{pct_change:.2f}% → 비정규 딥스캔 트리거")
              #  시 Taker Buy/Sell 적 로직 (강력 행 지 
              elif data.get('type') == 'trade':
                vol = float(data.get('trade_volume', 0))
                ask_bid = data.get('ask_bid') # ASK=매도  체결( 장가매수), BID=매수  체결( 장가매도)
                if ask_bid == 'ASK':
                  REALTIME_CVD[code_str] = REALTIME_CVD.get(code_str, 0.0) + vol
                elif ask_bid == 'BID':
                  REALTIME_CVD[code_str] = REALTIME_CVD.get(code_str, 0.0) - vol
          except asyncio.TimeoutError:
            continue #  1 안 장 거래가 으 음 루프 어가 종목 변 무 체크
    except Exception as e:
      logging.error(f"⚠️ 웹소켓 연결 끊김 ({e}). 3초 후 재연결 자동 시도...")
      await asyncio.sleep(3.0)
#  [ 중앙 로직 통합] strategy_logic.py의 공통 지표 엔진 호출
def _calculate_ta_indicators(df: pd.DataFrame, btc_df: Optional[pd.DataFrame], strat_params: dict) -> Tuple[Optional[pd.Series], Optional[pd.Series]]:
  try:
    df = _calculate_ta_indicators_sync(df, btc_df, strat_params)
    if df is None or len(df) < 2: return None, None
    return df.iloc[-2], df.iloc[-1]
  except Exception as e:
    logging.error(f"TA 연산 중 스레드 오류: {e}")
    return None, None
INDICATOR_CACHE, INDICATOR_CACHE_SEC = {}, 60 
OHLCV_CACHE = {} 
BALANCE_CACHE, BALANCE_CACHE_SEC = {"data": None, "timestamp": 0}, 10
#   [4단계: 전략 기조 브리핑 생성 (AI Alignment)]  
# (구버전 중복 제거됨, 1358행의 고도화된 버전 사용)
async def get_indicators(ticker):
  global INDICATOR_CACHE, OHLCV_CACHE
  now = time.time()
  async with INDICATOR_CACHE_LOCK:
    if ticker in INDICATOR_CACHE and (now - INDICATOR_CACHE[ticker][0] < INDICATOR_CACHE_SEC):
      return INDICATOR_CACHE[ticker][1], INDICATOR_CACHE[ticker][2]
  try:
    async with OHLCV_CACHE_LOCK:
      cached = OHLCV_CACHE.get(ticker)
    if cached is None:
      await asyncio.sleep(0.15) #  [최적 캐시 미스 에 레 (캐시 트 12 약)
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
    # 레 충돌 막기 해 이 프 임 복사 copy) 서 깁 다.
    df_copy = df.copy(deep=True)
    btc_copy = btc_df.copy(deep=True) if btc_df is not None else None
    #  [최적 고정 레  로 TA 계산 ( 레 경합 최소 + 정 능)
    loop = asyncio.get_running_loop()
    prev_data, curr_data = await loop.run_in_executor(_TA_EXECUTOR, _calculate_ta_indicators, df_copy, btc_copy, STRAT)
    if prev_data is None or curr_data is None:
      return None, None
    async with INDICATOR_CACHE_LOCK:
      INDICATOR_CACHE[ticker] = (now, prev_data, curr_data)
    return prev_data, curr_data
  except Exception as e: 
    logging.error(f"지표 계산 실패 ({ticker}): {e}")
    return None, None
#  [FIX: 거시 렌 캔 API 병목(Rate Limit) 막기 한 MTF 캐싱]
async def get_mtf_trend(ticker):
  global MTF_CACHE
  now = time.time()
  if ticker in MTF_CACHE and (now - MTF_CACHE[ticker]['time'] < MTF_CACHE_SEC):
    return MTF_CACHE[ticker]['data']
  try:
    df_1h = await execute_upbit_api(pyupbit.get_ohlcv, ticker, interval="minute60", count=30)
    df_4h = await execute_upbit_api(pyupbit.get_ohlcv, ticker, interval="minute240", count=30)
    if df_1h is None or df_1h.empty or df_4h is None or df_4h.empty: 
        return {"str": "알수없음", "4h_macd": 0, "1h_trend": 0}
    ema20_1h = df_1h.ta.ema(length=20).iloc[-1]
    macd_4h = df_4h.ta.macd(fast=12, slow=26, signal=9)
    macd_hist_4h = macd_4h[macd_4h.columns[1]].iloc[-1] if macd_4h is not None else 0
    trend_1h = "상승(EMA20 위)" if df_1h['close'].iloc[-1] > ema20_1h else "하락/횡보"
    trend_4h = "강세(MACD>0)" if macd_hist_4h > 0 else "약세(MACD<0)"
    #  [추 2] 이 로직 서 먹 해 치 이   께 반환
    result_data = {
      "str": f"4H {trend_4h} / 1H {trend_1h}",
      "4h_macd": macd_hist_4h,
      "1h_trend": 1 if df_1h['close'].iloc[-1] > ema20_1h else -1
    }
    MTF_CACHE[ticker] = {'time': now, 'data': result_data}
    return result_data
  except Exception as e:
        logging.error(f"MTF 분석 실패 ({ticker}): {e}")
        return {"str": "알수없음", "4h_macd": 0, "1h_trend": 0}
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
    # Pandas-TA 용 RSI 계산 (기존  import ta 용)
    df_btc['rsi'] = df_btc.ta.rsi(length=14)
    btc_rsi = round(df_btc['rsi'].iloc[-1], 2) if not df_btc['rsi'].empty else 50.0
    btc_vol_threshold = STRAT.get('btc_short_term_vol_threshold', 0.5) 
    is_risky = (volatility_pct >= btc_vol_threshold) and ("하락" in trend)
    BTC_SHORT_CACHE['data'] = {
      "trend": trend, 
      "volatility_pct": round(volatility_pct, 2), 
      "is_risky": is_risky,
      "rsi": btc_rsi #  BTC RSI 추 
    }
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
def extract_ai_essential_data(curr_data):
  # AI가 차트 단 는  요 심 지 만 터 (고도 지 추 )
  essential_keys = [
    'close', 'volume', 'rsi', 'macd_h', 'ST_DIR', 'adx', 'z_score', 'bb_bw', 'cvd',
    'dist_sma20', 'atr_pct', 'v_shape_special', 'is_volume_spike', 'is_bullish_recovery', 
    'cvd_improving', 'ob_imbalance', 'is_pullback_zone', 'is_rsi_cooling'
  ]
  return {k: round(v, 4) if isinstance(v, (int, float)) else v for k, v in curr_data.items() if k in essential_keys}
#   [3 계 & 4 계: 략 기조 브리 성 (AI Alignment)]  
def generate_strategy_context_briefing(eval_mode: str) -> str:
  """
    현재 설정된 핵심 파라미터(Iteration 12076 최적값 등)를 AI가 이해할 수 있는 '영어 자연어'로 번역합니다.
    이 브리핑은 AI의 프롬프트에 주입되어, 봇의 수치적 기조와 AI의 정성적 판단을 동기화시킵니다.
  """
  briefing = ["[CURRENT STRATEGY STANCE & PARAMETER BIAS]"]
  # 1. 꼬 (Wick) 민감 
  wick_pen = safe_float(get_dynamic_strat_value('wick_penalty', eval_mode, 63.7))
  if wick_pen > 40.0:
    briefing.append("- EXTREME WICK PENALTY: The system heavily penalizes upper shadows (wicks). If the candle shape is unstable or shows strong rejection at the top, you MUST REJECT (SKIP) the trade even if technical scores are high.")
  # 2. MTF( 추세) 가중치
  mtf_pen = safe_float(get_dynamic_strat_value('mtf_penalty_q', eval_mode, 17.7))
  mtf_bon = safe_float(get_dynamic_strat_value('mtf_bonus_q', eval_mode, 21.3))
  if mtf_pen > 30.0:
    briefing.append("- MACRO TREND STRICTNESS: High penalty for trading against the 1H/4H trend. Ensure the macro trend aligns with the trade direction.")
  elif mtf_bon > 30.0:
    briefing.append("- MACRO TREND RIDING: Huge bonus for aligning with the macro trend. Aggressively buy dips if the higher timeframe is strongly bullish.")
  # 3. 파 (Breakout) 민감 
  bb_bon = safe_float(get_dynamic_strat_value('bb_breakout_bonus', eval_mode, 76.0))
  if bb_bon > 50.0 and eval_mode == "QUANTUM":
    briefing.append("- AGGRESSIVE BREAKOUT HUNTER: The system gives massive scores for Bollinger Band upper breakouts.")
  # 4.  (Mean Reversion) 민감 
  rsi_bon = safe_float(get_dynamic_strat_value('rsi_oversold_bonus', eval_mode, 41.2))
  if rsi_bon > 30.0 and eval_mode == "CLASSIC":
    briefing.append("- DEEP DIP CATCHER: High reward for extreme oversold conditions. Look for signs of selling exhaustion.")

  # 5. [신규] 수익 극대화 기조 (Profit Maximization Stance)
  tp_mult = safe_float(get_dynamic_strat_value('tp_atr_mult', eval_mode, 4.5))
  sl_mult = safe_float(get_dynamic_strat_value('sl_atr_mult', eval_mode, 2.0))
  if tp_mult > 5.0:
    briefing.append(f"- AGGRESSIVE PROFIT TARGETING: TP multiplier is high ({tp_mult}x ATR). We are looking for big trend runs.")
  else:
    briefing.append(f"- CONSERVATIVE SCALPING: TP multiplier is moderate ({tp_mult}x ATR). Prioritize securing profit quickly.")
  
  briefing.append(f"- RISK TOLERANCE: Dynamic SL is set at {sl_mult}x ATR.")

  # 6. [신규] 진입 엄격도 (Entry Strictness)
  pass_thr = safe_float(get_dynamic_strat_value('pass_score_threshold', eval_mode, 80.0))
  briefing.append(f"- ENTRY QUALITY CONTROL: Target score threshold is {pass_thr}. Only high-conviction setups allowed.")

  # 7. [신규] 스나이퍼 보너스 (Sniper Boost)
  sniper_bon = safe_float(get_dynamic_strat_value('sniper_confluence_bonus', eval_mode, 45.0))
  if sniper_bon > 50.0:
    briefing.append(f"- SNIPER MODE ACTIVE: High bonus ({sniper_bon}) for perfect RSI+BB+CVD confluence entries.")

  return "\n".join(briefing)
def _smooth_parameter_update(old_val: float, new_val: float, learning_rate: float = 0.3) -> float:
  """
    전략 표류(Strategy Drift)를 방지하기 위해 새로운 최적화 값을 점진적으로 반영합니다 (EMA 방식).
  """
  return (old_val * (1.0 - learning_rate)) + (new_val * learning_rate)
# --- [4. AI 분석 진] ---
async def ai_analyze(ticker, data, mode="BUY", eval_mode="CLASSIC", no_trade_hours=0.0, win_rate=50.0, recent_wins=None, mtf_trend="알수없음", buy_price=0.0, market_regime=None, ignore_cooldown=False, rag_context="", expected_slippage=0.0, exit_plan_preview=None, strategy_intent="알수없음", coin_tier="알수없음"):
  global last_ai_call_time, last_coin_ai_call
  if mode == "BUY" and not ignore_cooldown and (time.time() - last_coin_ai_call.get(ticker, 0)) < 300: return None
  clean_data = robust_clean(data)
  #  [추 ] market_regime 서 fgi_val 추출 ( 롬 트 서 용 기 함)
  fgi_val = 50
  if isinstance(market_regime, dict):
    fgi_str = market_regime.get('fear_and_greed', '')
    fgi_match = re.search(r'\d+', fgi_str)
    if fgi_match: fgi_val = int(fgi_match.group())
  if mode == "OPTIMIZE":
    #  [ 정 1] 역 STRAT 닌, 최적 하 는 ' 당 모드' 진짜 정값을 가 옵 다.
    target_strat = get_strat_for_mode(eval_mode)
    forbidden_keys = ['tickers', 'max_concurrent_trades', 'interval', 'report_interval_seconds', 'history_win_count', 'history_loss_count', 'exit_plan_guideline']
    allowed_keys = [k for k in target_strat.keys() if k not in forbidden_keys]
    s_count = target_strat.get('success_reference_count', 8)
    f_count = target_strat.get('failure_reference_count', 8)
    # 기본 공통 용 
    common_keys = ['indicator_weights', 'scoring_modifiers', 'btc_short_term_vol_threshold', 'sleep_depth_threshold', 'risk_per_trade', 'high_vol_params', 'mid_vol_params', 'major_params', 'success_reference_count', 'failure_reference_count']
    for k in common_keys:
      if k not in allowed_keys: allowed_keys.append(k)
    #  [ 정 2] 래 과   모드 Allowed Keys  Important Ranges 철 분리
    if eval_mode == "CLASSIC":
      classic_keys = ['bonus_mtf_panic_dip', 'bonus_btc_panic_dip', 'bonus_golden_combo', 'bonus_st_oversold_bounce', 'penalty_st_downtrend', 'penalty_rs_weakness']
      for k in classic_keys: 
        if k not in allowed_keys: allowed_keys.append(k)
      strategy = "Deep Dip / Oversold Mean Reversion (낙폭 과대 역추세 매매)"
      important_ranges = """
      - pass_score_threshold: MUST be between 82 and 90 (Ultra Sniper Mode)
      - guard_score_threshold: MUST be between 55 and 65
      - sell_score_threshold: MUST be between 40 and 50
      - bonus_golden_combo: MUST be between 30 and 50
      - bonus_mtf_panic_dip: MUST be between 20 and 40
      - bonus_st_oversold_bounce: MUST be between 15 and 30
      - penalty_st_downtrend: MUST be between -15 and -5
      - major_params/stop_loss: -1.5 ~ -1.0 (ULTRA TIGHT)
      - major_params/target_atr_multiplier: 1.2 ~ 2.5 (QUICK SNIPE)
      - mid/high_vol_params/target_atr_multiplier: 2.0 ~ 3.5
      - timeout_candles: 4 ~ 10 (CRITICAL: High Velocity)
      - btc_surge_threshold: 1.0 ~ 2.0
      """
      critical_rule = "CRITICAL RULE: You MUST include 'z_score' and 'bollinger' in BOTH 'trend_active_logic' and 'range_active_logic'. Remove breakout modifiers like 'bonus_volume_explosion'."
    else: # QUANTUM
      quantum_keys = ['bonus_all_time_high', 'bonus_volume_explosion', 'penalty_btc_weakness', 'penalty_weak_momentum', 'penalty_overbought_rsi']
      for k in quantum_keys: 
        if k not in allowed_keys: allowed_keys.append(k)
      strategy = "Trend Follower & Breakout Trader (추세 추종 및 돌파 매매)"
      important_ranges = """
      - pass_score_threshold: MUST be between 75 and 85
      - guard_score_threshold: MUST be between 60 and 70
      - sell_score_threshold: MUST be between 40 and 50
      - bonus_volume_explosion: MUST be between 25 and 45
      - bonus_all_time_high: MUST be between 20 and 40
      - penalty_btc_weakness: MUST be between -30 and -15
      - penalty_weak_momentum: MUST be between -25 and -10
            - btc_surge_threshold: MUST be between 1.0 and 3.0 (BTC 1분 급등 트리거 기준%. 시장 변동성 높으면 낙게, 낙으면 높게 교정)
      """
      critical_rule = "CRITICAL RULE: You MUST prioritize momentum indicators like 'bollinger_breakout' and 'sma_crossover'. Remove panic dip bonuses."
    #  [ 정 3] AI 게 염 역 STRAT 닌, 깨끗 target_strat 깁 다.
    # 치 루 네 셷 방  해 "Key: Value" 리스 로 변 하 명시 으 달
    filtered_strat = {k: target_strat[k] for k in allowed_keys if k in target_strat}
    current_strategy_str = "\n".join([f"- {k}: {v}" for k, v in filtered_strat.items()])
    success_hist = recent_wins[-s_count:] if isinstance(recent_wins, list) and len(recent_wins) > 0 else "데이터 없음 (현재 기본 설정 유지 권장)"
    failure_hist = clean_data[-f_count:] if isinstance(clean_data, list) and len(clean_data) > 0 else "데이터 없음 (현재 기본 설정 유지 권장)"
    mission = f"""
    Success History: {success_hist}
    Failure History: {failure_hist}
    Mission:
    1. Swap or update indicators in 'trend_active_logic' and 'range_active_logic' to match the '{strategy}' regime.
    2. Tune indicator_weights, scoring_modifiers, Tier-params, and the FGI V-Curve parameters.
    3. You MUST keep thresholds and bonuses strictly within the [IMPORTANT RANGES].
        4. If History is "데이터 없음", make VERY MINIMAL changes.
    5. [CRITICAL FOR 'reason' FIELD]: You MUST refer to the [Current Strategy Settings] below. 
      If you report a change as 'A -> B', 'A' MUST be the exact value from the list below. 
      DO NOT mention or explain parameters that you kept the same. Be strictly factual and matching the numerical results.
    Provide ONLY valid JSON.
    """
    prompt = f"""
    [X_OPTIMIZE]
    Strategy: {strategy}
    WinRate: {win_rate:.1f}% | Regime: {market_regime}
    [Current Strategy Settings]
    {current_strategy_str}
    Allowed Keys: {allowed_keys}
    [IMPORTANT RANGES]
    {important_ranges}
    {critical_rule}
    [SPECIAL SNIPER INSTRUCTION]:
    - CURRENT BEST MODEL USES: stop_loss = -1.5%, pass_score_threshold = 85.
    - You MUST design prompts and parameters to support this 'High Velocity' strategy. 
    - Do NOT suggest stop-loss wider than -2.5% unless volatility is extreme.
    - Target ATR multipliers should favor 1.2 to 2.8 ranges for consistency.
    {mission}
    """
  elif mode == "SELL_REASON":
      strategy_mode = clean_data.get('strategy_mode', 'UNKNOWN')
      strategy_desc = "Mean Reversion" if eval_mode == "CLASSIC" else "Trend Following"
      prompt = f"""
      [X_SELL_REASON]
      Ticker: {ticker} | Mode: {strategy_mode}
            Final Profit: {clean_data.get('p_rate')}% | Max Reached Profit: {clean_data.get('max_p_rate', '알수없음')}%
            Hold Duration: {clean_data.get('elapsed_min', '알수없음')} minutes
      BTC Change: {clean_data.get('btc_change')}%
      Original Buy Reason: {clean_data.get('original_buy_reason')}
      Original Exit Plan: {clean_data.get('original_exit_plan')}
      Buy Indicators: {clean_data.get('buy_ind')}
      Sell Indicators: {clean_data.get('sell_ind')}
      Actual Sell Reason: {clean_data.get('actual_sell_reason')}
      Mission:
      1. 시스템의 손실/수익 사례를 분석하십시오.
            2. [CRITICAL]: 핵심 내용을 반드시 '3문장 이내'로 요약하십시오 (Korean).
            3. [SNIPER AUDIT]: 수익 1.2% 돌파 후 절반 익절이 정상 작동했는지, -1.5% 손절이 지켜졌는지 체크하십시오.
            4. [IMPROVEMENT]: 'improvement' 필드에 다음 거래 승률을 높이기 위한 제언을 반드시 포함하십시오.
            5. [DNA EVOLVE]: 코인 특성상 파라미터 튜닝이 필요하면 'dna_tweak'으로 제안하되, 손절선을 -2.5% 보다 넓게 잡는 것은 금지 수준으로 신중해야 합니다.
            Output JSON: {{"reason": "3문장 핵심 요약", "status": "SUCCESS"|"FAIL"|"ACCEPTABLE", "rating": 0~100, "improvement": "제언", "dna_tweak": {{}} }}
      """
  elif mode == "BUY": 
    strategy_mode = clean_data.get('strategy_mode', 'QUANTUM')
    guideline = get_dynamic_strat_value('exit_plan_guideline', mode=strategy_mode, default='Follow Tier Params.')
    warning_msg = f"🚨 WARNING: {clean_data['warning']}" if (isinstance(clean_data, dict) and clean_data.get('warning')) else ""
    if eval_mode == "CLASSIC":
      strategy_desc = "Deep Dip / Oversold Mean Reversion"
    else:
      strategy_desc = "Trend Follower & Pullback Sniper"
    #  [4 계: AI 기  적 라미터 브리 성
    strategy_context_briefing = generate_strategy_context_briefing(eval_mode)
    #  [모두 어 성] 스 컨텍 트 어 출력 지 는 국 강제
    prompt = f"""
    [X_BUY_EVALUATION]
    Ticker: {ticker} | Coin Tier: {coin_tier} | Regime: {market_regime}
    Strategy Mode: {eval_mode} | Strategy Logic: {strategy_desc}
    {strategy_context_briefing}
    [DATA CONTEXT]
    - Indicators: {json.dumps(clean_data, indent=2, ensure_ascii=False)}
    - MTF Trend: {mtf_trend}
    - Fear & Greed Index: {fgi_val}
    - Expected Exit Plan: {exit_plan_preview}
    - Strategy Intent: {strategy_intent}
    {warning_msg}
    [COUNCIL MISSION]
    1. Technical Analyst: Evaluate momentum vs. oversold state based on the Data Context. Check if volume or CVD supports a real reversal or if it's a fakeout.
    2. Market Sentiment Agent: Assess if the broader market (BTC trend, FGI) supports this trade.
    3. Risk Auditor: Audit slippage ({expected_slippage}%) and orderbook imbalance ('ob_imbalance'). You hold the final VETO. Reject (SKIP) if structural risk outweighs potential.
    [FINAL OUTPUT STRUCTURE (STRICT JSON)]
    You MUST output valid JSON ONLY.
    CRITICAL: The values for 'tech_agent_opinion', 'trend_agent_opinion', 'risk_agent_opinion', and 'reason' MUST BE WRITTEN IN KOREAN.
    {{
      "tech_agent_opinion": "Korean text here",
      "trend_agent_opinion": "Korean text here",
      "risk_agent_opinion": "Korean text here",
      "decision": "BUY" or "SKIP",
      "score": 0~100 (integer),
      "reason": "Portfolio Manager's final synthesis in Korean",
      "exit_plan": {{
        "target_atr_multiplier": float,
        "stop_loss": float,
        "atr_mult": float,
        "timeout": integer
      }}
    }}
    """
  elif mode == "POST_BUY_REPORT": 
    strategy_mode = clean_data.get('strategy_mode', 'QUANTUM')
    warning_msg = f"🚨 WARNING: {clean_data['warning']}" if (isinstance(clean_data, dict) and clean_data.get('warning')) else ""
    if eval_mode == "CLASSIC":
      strategy_desc = "Deep Dip / Oversold Mean Reversion"
    else:
      strategy_desc = "Trend Follower & Pullback Sniper"
    strategy_context_briefing = generate_strategy_context_briefing(eval_mode)
    prompt = f"""
    [X_POST_BUY_AUDIT]
    Ticker: {ticker} | Mode: {strategy_mode} | Eval Mode: {eval_mode} | Entry Price: {buy_price:,.0f}
    Regime: {market_regime}
    {strategy_context_briefing}
    [SITUATION]
    The Python engine has made a preemptive purchase. The committee must now audit the entry quality.
    - Indicators: {json.dumps(clean_data, indent=2, ensure_ascii=False)}
    - Exit Plan: {exit_plan_preview}
    {warning_msg}
    [COUNCIL DEBATE]
    1. Technical Analyst: Is the bounce or breakout holding Check indicator strength.
    2. Risk Auditor: Is there a "Fatal Flaw" (e.g., severe negative CVD) that the Python engine ignored due to scoring 
    3. Portfolio Manager: Synthesize and decide to CONTINUE (BUY) or ABORT (SKIP).
    [FINAL OUTPUT STRUCTURE (STRICT JSON)]
    You MUST output valid JSON ONLY. All string values MUST be in KOREAN.
    {{
      "risk_opinion": "Korean text",
      "decision": "BUY" or "SKIP",
      "score": 0~100 (integer),
      "reason": "Final audit synthesis in Korean",
      "exit_plan": {{ "target_atr_multiplier": float, "stop_loss": float, "atr_mult": float, "timeout": integer }}
    }}
    """
  elif mode == "EVOLVE_PROMPT":
    #  [ 정 1]  서 주입 최신 지 rag_context) 용 도 변경하 메모 기 
    current_guideline = rag_context if rag_context else "없음"
    proposals_text = clean_data 
    prompt = f"""
    [X_EVOLVE_PROMPT]
    Strategy Mode: {eval_mode}
    Current AI Prompt (exit_plan_guideline): 
    {current_guideline}
    New Post-Trade AI Suggestions:
    {proposals_text}
    Mission: Read the New Suggestions systematically. If they contain valuable insights or logical corrections that are NOT already in the 'Current AI Prompt', rewrite the Prompt.
    * IMPORTANT RULE: Do NOT add instructions for conditions that are ALREADY handled by the Python Engine's 'HARDCODED SYSTEM OVERRIDES' (e.g., Fatal Flaw locks, Volume validation, Trailing Stops). Focus on nuanced, agentic evaluations that Python cannot natively compute.
    * FORMATTING RULE: Do NOT use angle brackets (<, >) in your text. Use words like 'under', 'below', or 'less than' instead of mathematical symbols to prevent HTML parsing errors.
    Your goal is to formulate a concise, powerful, and directive guideline (in Korean) that will guide future agentic trade analysis based on empirical failures.
    Ensure it is less than 2 sentences. If no practical changes are needed, just output the Current AI Prompt exactly as it is.
    Output JSON: {{"new_guideline": "string", "reason": "string"}}
    """
  else: return None
  if not prompt.strip(): return None 
  for attempt in range(3):
    try:
      logging.info(f"🤖 [AI {mode} 면접] {ticker} 분석 시작... (시도 {attempt+1}/3)")
      if attempt > 0:
        await asyncio.sleep(2.0)
      if attempt == 0 and mode != "POST_BUY_REPORT":
        elapsed = time.time() - last_ai_call_time
        if elapsed < GLOBAL_COOLDOWN: await asyncio.sleep(GLOBAL_COOLDOWN - elapsed)
      last_ai_call_time = time.time()
      if mode in ("BUY", "POST_BUY_REPORT"): last_coin_ai_call[ticker] = last_ai_call_time
      if mode == "OPTIMIZE":
        system_instruction_text = AI_SYSTEM_INSTRUCTION_OPTIMIZE
      elif eval_mode == "CLASSIC":
        system_instruction_text = AI_SYSTEM_INSTRUCTION_CLASSIC
      else:
        system_instruction_text = AI_SYSTEM_INSTRUCTION_QUANTUM
      res = await asyncio.wait_for(
        asyncio.to_thread(
          client.models.generate_content, 
          model=MODEL_ID, 
          contents=prompt,
          config=types.GenerateContentConfig(
            system_instruction=types.Content(parts=[types.Part(text=system_instruction_text)]),
            temperature=0.1,
            response_mime_type="application/json"
          )
        ), 
        timeout=25.0
      )
      try: 
        res_text = res.text
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
      if end <= start: raise Exception("불완 JSON")
      raw_json = res_text[start:end+1]
      #  [개선] 강력 JSON 화: 어문자  스케 프 류 거
      raw_json = re.sub(r'[\x00-\x1F\x7F]', '', raw_json)
      raw_json = re.sub(r'\\( !["\\/bfnrtu])', '', raw_json)
      res_json = json.loads(raw_json)
      if mode == "OPTIMIZE": return res_json
      if mode == "EVOLVE_PROMPT":
        return {
          "new_guideline": str(res_json.get('new_guideline', '')),
          "reason": str(res_json.get('reason', 'N/A'))
        }
      if mode == "SELL_REASON":
        if not isinstance(res_json, dict): raise Exception("응답이 딕셔너리가 아닙니다.")
        return {
          "rating": int(res_json.get('rating', 50)),
          "status": str(res_json.get('status', 'UNKNOWN')).upper(),
          "reason": str(res_json.get('reason', res_json.get('message', '분석 결과 없음'))),
          "improvement": str(res_json.get('improvement', '없음')),
          "dna_tweak": res_json.get('dna_tweak', {}) #  DNA 추출
        }
      if mode in ("POST_BUY_REPORT", "BUY"):
        score = int(res_json.get('score', 50 if mode == "POST_BUY_REPORT" else 0))
        decision = str(res_json.get('decision', 'SKIP')).upper()
        if mode == "POST_BUY_REPORT" and decision not in ('BUY', 'SKIP'): decision = 'BUY' if score >= 50 else 'SKIP'
        if mode == "BUY" and decision not in ('BUY', 'SKIP'): decision = 'SKIP'
        extracted_reason = res_json.get('reason')
        #  [ 락 복구] tech_agent_opinion 추출 추 
        tech_opinion = res_json.get('tech_agent_opinion', 'N/A')
        trend_opinion = res_json.get('trend_agent_opinion', 'N/A')
        risk_opinion = res_json.get('risk_agent_opinion', 'N/A')
        if not extracted_reason:
          cso_opinion = res_json.get('chief_strategy_officer_opinion')
          if isinstance(cso_opinion, dict): 
            extracted_reason = cso_opinion.get('reason', 'N/A')
          elif isinstance(cso_opinion, str): 
            extracted_reason = cso_opinion
          else: 
            extracted_reason = 'N/A'
        #  [Step 3: Council Logging 개선]
        logging.info(f"📊 [AI Council - Tech]: {tech_opinion}")
        logging.info(f"📈 [AI Council - Trend]: {trend_opinion}")
        logging.info(f"🛡️ [AI Council - Risk]: {risk_opinion}")
        logging.info(f"📝 [AI Council - Final]: {extracted_reason}")
        raw_plan = res_json.get('exit_plan', {})
        strategy_mode = clean_data.get('strategy_mode', 'QUANTUM')
        default_stop = -1.5 # [Sniper Upgrade] 기본 절 향
        default_atr = 1.2  # [Sniper Upgrade] 목표가 1  기 
        default_timeout = 8 # [Sniper Upgrade] 안전 장치선
        exit_plan = {
          "target_atr_multiplier": max(1.0, min(8.0, safe_float(raw_plan.get('target_atr_multiplier', 2.8)))),
          "stop_loss": max(-3.5, min(-0.5, safe_float(raw_plan.get('stop_loss', default_stop)))),
          "atr_mult": max(0.5, min(4.0, safe_float(raw_plan.get('atr_mult', default_atr)))),
          "timeout": max(2, min(20, int(safe_float(raw_plan.get('timeout', default_timeout)))))
        }
        return {
          "score": score, 
          "decision": decision, 
          "reason": str(extracted_reason), 
          "tech_opinion": str(tech_opinion), #  반환 객체 추 
          "trend_opinion": str(trend_opinion),
          "risk_opinion": str(risk_opinion),
          "exit_plan": exit_plan
        }
    except Exception as e:
      err_str = str(e).lower()
      #  [개선] 503 과 러  간  ( 버 고  간 부 
      backoff = (attempt + 1) * 2.0
      if "503" in err_str or "high demand" in err_str or "unavailable" in err_str:
        logging.warning(f"⏳ AI 서버 과부하 감지 (503). {(attempt+1)*5}초 대기 후 다시 시도합니다...")
        await asyncio.sleep((attempt + 1) * 5.0)
      else:
        logging.error(f"⚠️ [AI {mode} 분석 실패] {ticker}: {e}")
        await asyncio.sleep(backoff)
      if attempt < 2: continue 
  if mode == "OPTIMIZE": return None
  if mode == "SELL_REASON": return {"rating": 50, "status": "UNKNOWN", "message": "AI 응답 불가"}
  if mode == "BUY": 
    return {"score": 0, "decision": "SKIP", "reason": "🚨 [비상 엔진] AI 서버 응답 지연으로 안전을 위해 매수 스킵.", "exit_plan": {}, "system_error": True}
  return {"is_error": True}
async def ai_self_optimize(trigger="manual", eval_mode="QUANTUM"):
  global last_auto_optimize_time
  target_strat = get_strat_for_mode(eval_mode)
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
    eval_mode=eval_mode,
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
      if eval_mode == "CLASSIC":
        default_trend = ['volume', 'rsi', 'bollinger', 'macd', 'z_score']
      else:
        default_trend = ['supertrend', 'macd', 'volume', 'bollinger_breakout', 'sma_crossover', 'z_score']
      valid_trend = enforce_indicator_count(new_data['trend_active_logic'], default_trend)
      old_trend = target_strat.get('trend_active_logic', [])
      if set(old_trend) != set(valid_trend):
        added = [x for x in valid_trend if x not in old_trend]
        removed = [x for x in old_trend if x not in valid_trend]
        msg_parts = []
        if added: msg_parts.append(f"추가[{', '.join(added)}]")
        if removed: msg_parts.append(f"제외[{', '.join(removed)}]")
        if msg_parts: changes.append(f" <b>강추 지 /b>: {' / '.join(msg_parts)}")
        target_strat['trend_active_logic'] = valid_trend
    if 'range_active_logic' in new_data: 
      if eval_mode == "CLASSIC":
        default_range = ['rsi', 'stochastics', 'vwap', 'ssl_channel', 'atr_trend']
      else:
        default_range = ['rsi', 'stochastics', 'bollinger_bandwidth', 'vwap', 'ssl_channel', 'z_score']
      valid_range = enforce_indicator_count(new_data['range_active_logic'], default_range)
      old_range = target_strat.get('range_active_logic', [])
      if set(old_range) != set(valid_range):
        added = [x for x in valid_range if x not in old_range]
        removed = [x for x in old_range if x not in valid_range]
        msg_parts = []
        if added: msg_parts.append(f"추가[{', '.join(added)}]")
        if removed: msg_parts.append(f"제외[{', '.join(removed)}]")
        if msg_parts: changes.append(f"• 🌊 <b>횡보장 지표</b>: {' / '.join(msg_parts)}")
        target_strat['range_active_logic'] = valid_range
    if 'indicator_weights' in new_data:
      current_weights = target_strat.get('indicator_weights', {})
      raw_new_weights = new_data['indicator_weights']
      active_indicators = set(target_strat.get('trend_active_logic', []) + target_strat.get('range_active_logic', []))
      clamped_weights = {}
      for ind in active_indicators:
        val = raw_new_weights.get(ind, current_weights.get(ind, 1.0))
        clamped_weights[ind] = max(0.5, min(2.0, float(val)))
      if current_weights != clamped_weights:
        weight_changes = []
        for k, v in clamped_weights.items():
          old_v = current_weights.get(k, 1.0) 
          if old_v != v: weight_changes.append(f"{k}({old_v}{v})")
        if weight_changes: changes.append(f"• ⚖️ <b>가중치 조정</b>: {', '.join(weight_changes)}")
        target_strat['indicator_weights'] = clamped_weights
    if 'scoring_modifiers' in new_data:
      current_mods = target_strat.get('scoring_modifiers', {})
      raw_mods = new_data['scoring_modifiers']
      clamped_mods = {}
      mod_changes = []
      if eval_mode == "CLASSIC":
        valid_strategy_mods = [
          'bonus_mtf_panic_dip', 'bonus_btc_panic_dip', 'bonus_golden_combo', 
          'bonus_st_oversold_bounce', 'penalty_st_downtrend', 'penalty_rs_weakness'
        ]
      else:
        valid_strategy_mods = [
          'bonus_all_time_high', 'bonus_volume_explosion', 'penalty_btc_weakness',
          'penalty_weak_momentum', 'penalty_overbought_rsi'
        ]
      for mk in valid_strategy_mods:
        val = raw_mods.get(mk, current_mods.get(mk))
        if val is None: continue
        try: mv = int(val)
        except: mv = current_mods.get(mk, 0)
        if mk == 'bonus_all_time_high': clamped_mods[mk] = max(10, min(40, mv)) 
        elif mk == 'bonus_volume_explosion': clamped_mods[mk] = max(20, min(50, mv)) 
        elif mk == 'penalty_btc_weakness': clamped_mods[mk] = max(-30, min(-5, mv)) 
        elif mk == 'penalty_weak_momentum': clamped_mods[mk] = max(-25, min(-5, mv)) 
        elif mk == 'penalty_overbought_rsi': clamped_mods[mk] = max(-20, min(-5, mv)) 
        elif mk == 'bonus_mtf_panic_dip': clamped_mods[mk] = max(15, min(35, mv))
        elif mk == 'bonus_btc_panic_dip': clamped_mods[mk] = max(10, min(25, mv))
        elif mk == 'bonus_golden_combo': clamped_mods[mk] = max(25, min(45, mv))
        elif mk == 'bonus_st_oversold_bounce': clamped_mods[mk] = max(10, min(25, mv))
        elif mk == 'penalty_st_downtrend': clamped_mods[mk] = max(-15, min(0, mv))
        elif mk == 'penalty_rs_weakness': clamped_mods[mk] = max(-30, min(-10, mv))
        old_mv = current_mods.get(mk, "N/A")
        if old_mv != clamped_mods[mk]:
          mod_changes.append(f"{mk}({old_mv}->{clamped_mods[mk]})")
      if mod_changes:
        changes.append(f"• 🧮 <b>점수 가감 스위치 조정</b>: {', '.join(mod_changes)}")
        target_strat['scoring_modifiers'] = clamped_mods
    new_guideline = res.get('exit_plan_guideline')
    if new_guideline and target_strat.get('exit_plan_guideline') != new_guideline:
      changes.append(f"• 📜 작전 지침: <b>{str(new_guideline).replace('<', '&lt;').replace('>', '&gt;')}</b>")
      target_strat['exit_plan_guideline'] = new_guideline
    tier_keys = ['high_vol_params', 'mid_vol_params', 'major_params']
    tier_updated = False
    for tk in tier_keys:
      if tk in new_data:
        old_p = target_strat.get(tk, {})
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
            target_strat[tk] = updated_p
            tier_updated = True
    if tier_updated:
      table_str = "• 📊 <b>티어 파라미터 (Params)</b>\n"
      table_str += "<pre>Tier | SL | TAM | ABB | ASTH | ADX\n"
      table_str += "----------------------------------------\n"
      for tk, name in zip(tier_keys, ['High ', 'Mid ', 'Major']):
        p = target_strat.get(tk, {})
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
      if k in target_strat and k not in ignore_list:
        try:
          if 'mult' in k or 'dev' in k: v = max(0.5, min(5.0, float(v)))
          elif 'len' in k: v = max(3, min(200, int(v)))
          elif k == 'fgi_v_curve_bottom': v = max(15.0, min(55.0, float(v)))
          elif k == 'fgi_v_curve_max': v = max(1.2, min(3.5, float(v)))
          elif k == 'fgi_v_curve_min': v = max(0.3, min(1.0, float(v)))
          elif k == 'fgi_v_curve_greed_max': v = max(0.8, min(3.0, float(v)))
          elif k == 'pass_score_threshold': v = max(70, min(95, int(v)))
          elif k == 'guard_score_threshold': v = max(40, min(80, int(v)))
          elif k == 'sell_score_threshold': 
            #  [개선] CLASSIC 모드  계 30 서 버틸 게 용
            min_sell = 25 if eval_mode == "CLASSIC" else 40
            v = max(min_sell, min(55, int(v)))
          elif k == 'rsi_low_threshold': v = max(15.0, min(65.0, float(v)))
          elif k == 'rsi_high_threshold': v = max(55.0, min(90.0, float(v)))
          elif k == 'btc_surge_threshold':
            v = max(0.8, min(4.0, float(v)))
            global BTC_SURGE_THRESHOLD
            BTC_SURGE_THRESHOLD = v
          elif k == 'btc_short_term_vol_threshold': v = max(0.5, min(2.0, float(v)))
          elif k == 'sleep_depth_threshold': v = max(0, min(1000000000, int(v)))
          elif k == 'success_reference_count': v = max(5, min(15, int(v)))
          elif k == 'failure_reference_count': v = max(5, min(15, int(v)))
        except: continue 
        if target_strat.get(k) != v: 
          changes.append(f" {k}: {target_strat.get(k)} <b>{v}</b>")
          target_strat[k] = v
    if eval_mode == "CLASSIC":
      await save_config_async(CLASSIC_CONF, CLASSIC_CONFIG_PATH.replace(".json", "_backup.json"))
      CLASSIC_CONF['strategy'] = target_strat
      await save_config_async(CLASSIC_CONF, CLASSIC_CONFIG_PATH)
    else:
      await save_config_async(QUANTUM_CONF, CONFIG_PATH.replace(".json", "_backup.json"))
      QUANTUM_CONF['strategy'] = target_strat
      await save_config_async(QUANTUM_CONF, CONFIG_PATH)
    ai_reason = str(res.get('reason', 'N/A')).replace('<', '&lt;').replace('>', '&gt;')
    if changes: await send_msg(f"✨ <b>통합 전략 진화 완료 </b>\n\n" + "\n".join(changes) + f"\n\n💡 <b>AI:</b>\n{ai_reason}")
    else: await send_msg("🧬 <b>최적화 유지</b> (변경 없음)") 
    if trigger in ("auto", "daily"): last_auto_optimize_time = time.time()
    else: await send_msg("🧬 <b>최적화 실패 또는 AI 응답 없음</b>") 
async def execute_smart_sell(ticker, qty, current_price, urgency="NORMAL"):
  if urgency == "HIGH" or (qty * current_price) < 6000:
    res = await execute_upbit_api(upbit.sell_market_order, ticker, qty)
    return res is not None #  공  반환
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
        final_order = await execute_upbit_api(upbit.get_order, uuid)
        exec_vol = float(final_order.get('executed_volume', 0)) if final_order else 0
        remaining_qty -= exec_vol
      else:
        break
    else: break 
  if remaining_qty > 0:
    open_orders = await execute_upbit_api(upbit.get_order, ticker)
    if isinstance(open_orders, list):
      for order in open_orders:
        if isinstance(order, dict) and order.get('uuid'):
          await execute_upbit_api(upbit.cancel_order, order.get('uuid'))
          await asyncio.sleep(0.2)
    balances = await execute_upbit_api(upbit.get_balances)
    if isinstance(balances, list):
      coin_currency = ticker.split('-')[1]
      coin_info = next((b for b in balances if b['currency'] == coin_currency), None)
      if coin_info:
        actual_rem = float(coin_info['balance']) + float(coin_info['locked'])
        if actual_rem * current_price >= 5000:
          res = await execute_upbit_api(upbit.sell_market_order, ticker, actual_rem)
          if res is None: return False #  최종 패 False
  return True
#  [체결 최적  리  방    기반 마 분할 매수 진
async def execute_smart_buy(ticker, buy_amt, limit_price_threshold):
  orderbook = await execute_upbit_api(pyupbit.get_orderbook, ticker)
  if not orderbook: return False, "호가창(Orderbook) 조회 실패"
  total_bid, total_ask = orderbook['total_bid_size'], orderbook['total_ask_size']
  if total_bid == 0 or total_ask == 0: return False, "호가창 물량 없음 (거래 정지 의심)"
  imbalance_ratio = total_ask / total_bid
  if imbalance_ratio > 5.0 or imbalance_ratio < 0.2:
    await send_msg(f"⚠️ <b>휩소 필터링</b>: {ticker} 호가창 극심한 불균형")
    return False, "호가창 극심한 불균형 (휩소 필터링)"
  remaining_amt = buy_amt
  for attempt in range(3):
    if remaining_amt < 6000: break
    ob = await execute_upbit_api(pyupbit.get_orderbook, ticker)
    if not ob: return False, f"매수 중 호가창 갱신 실패 (시도 {attempt+1})"
    best_ask = ob['orderbook_units'][0]['ask_price']
    if best_ask > limit_price_threshold: 
      return False, f"순간적인 가격 급등 (1호가 {best_ask}원이 마지노선 {limit_price_threshold}원 초과)"
    buy_qty = math.floor((remaining_amt / best_ask) * 1e8) / 1e8
    res = await execute_upbit_api(upbit.buy_limit_order, ticker, best_ask, buy_qty)
    if not res or 'uuid' not in res: 
      return False, "매수 주문 API 거절 (잔고 부족 또는 한도 초과)"
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
  if (buy_amt - remaining_amt) >= 6000:
    return True, "매수 성공"
  else:
    return False, "3회 분할 매수 시도 후에도 최소 체결 금액(6,000원) 미달"
async def background_ai_post_report(ticker, curr_data, mtf, buy_price, pass_score, eval_mode="QUANTUM"):
  global TRADE_DATA_DIRTY, trade_data
  await asyncio.sleep(1.0) 
  regime = await get_market_regime()
  wr, _, _, _, _, _ = await get_performance_stats_db()
  curr_data_dict = curr_data if isinstance(curr_data, dict) else curr_data.to_dict()
  curr_data_dict['strategy_mode'] = eval_mode
  mtf_str = mtf.get('str', '알수없음') if isinstance(mtf, dict) else str(mtf)
  exit_preview = get_exit_plan_preview(ticker, curr_data_dict, eval_mode=eval_mode)
  intent = "상승 추세 중 눌림목 매수 (Pullback)" if eval_mode == "QUANTUM" else "낙폭 과대 구간 역추세 매매 (Deep Dip)"
  tier = get_coin_tier(ticker, curr_data_dict)
  ai_res = await ai_analyze(ticker, curr_data_dict, mode="POST_BUY_REPORT", eval_mode=eval_mode, mtf_trend=mtf_str, buy_price=buy_price, market_regime=regime, win_rate=wr, exit_plan_preview=exit_preview, strategy_intent=intent, coin_tier=tier)
  if not isinstance(ai_res, dict): ai_res = ai_res or {}
  if ticker in trade_data:
    t = trade_data[ticker]
    safe_reason = str(ai_res.get('reason', '')).replace('<', '&lt;').replace('>', '&gt;')
    score = ai_res.get('score', 50)
    decision = ai_res.get('decision', 'SKIP')
    if decision == 'SKIP' or score < 50:
      risk_alert = ai_res.get('risk_opinion', safe_reason)
      await send_msg(
        f"🚨 <b>AI Council 리스크 경고</b>: {ticker} 위험 감지!\n"
        f"⚠️ <b>감사관 의견</b>: {risk_alert}\n"
        f"👉 <b>최소 손실 탈출 모드로 전환합니다!</b>"
      )
      t['exit_plan'] = {'target_atr_multiplier': 1.0, 'stop_loss': -0.7, 'atr_mult': 0.5, 'timeout': 2}
    else:
      t['exit_plan'] = ai_res.get('exit_plan', {})
      await send_msg(f"📝 <b>AI 사후 결재 (스나이퍼)</b>: {ticker} (파이썬:{pass_score:.1f}점 ➡️ AI:{score:.1f}점)\n- 작전: {t['exit_plan']}\n- 코멘트: {safe_reason}")
      t['buy_reason'] = f"[스나이퍼 선제공격] {safe_reason}"
    TRADE_DATA_DIRTY = True
# --- [5. 공통 캔 모듈] ---
async def process_buy_order(ticker, score, reason, curr_data, total_asset, cash, held_count, exit_plan, buy_mode="QUANTUM", pass_score=0):
  global last_global_buy_time, TRADE_DATA_DIRTY
  # eval_mode buy_mode  기 하 불일 천 차단
  eval_mode = buy_mode
  #  [보안 1] 가 괴리 보호 (Price Drift Protection)
  # 분석 점 가 curr_data['close']) 재 행 점 가격을 비교
  analysis_price = safe_float(curr_data.get('close'))
  current_market_p = safe_float(REALTIME_PRICES.get(ticker, 0))
  if current_market_p > analysis_price * 1.025:
    logging.warning(f"🚫 [매수 취소] {ticker}: 분석 가격({analysis_price}) 대비 실시간 가격({current_market_p})이 너무 높음 (괴리율 > 2.5%)")
    return False
  strat = get_strat_for_mode(buy_mode)
  max_trades = strat.get('max_concurrent_trades', STRAT.get('max_concurrent_trades', GLOBAL_MAX_POSITIONS)) 
  if held_count >= max_trades: return False
  # [ 기  티마이   일 변 성 겉팅 기반 금 배분
  atr_pct = (curr_data['ATR'] / curr_data['close']) if curr_data['close'] > 0 else 0.01
  buy_amt = calculate_optimized_buy_amt(total_asset, cash, (atr_pct * 100))
  if buy_amt >= 6000: 
    max_tolerable_price = curr_data['close'] * 1.005 
    buy_success, fail_reason = await execute_smart_buy(ticker, buy_amt, max_tolerable_price)
    if buy_success:
      await asyncio.sleep(1.5)
      current_balances = await execute_upbit_api(upbit.get_balances)
      coin_currency = ticker.split('-')[1]
      coin_info = None
      if isinstance(current_balances, list):
        coin_info = next((b for b in current_balances if isinstance(b, dict) and b.get('currency') == coin_currency), None)
      final_buy_price = safe_float(coin_info.get('avg_buy_price')) if coin_info and safe_float(coin_info.get('avg_buy_price')) > 0 else safe_float(await execute_upbit_api(pyupbit.get_current_price, ticker))
      now_ts = time.time()
      last_buy_time[ticker], last_global_buy_time = now_ts, now_ts
      tier_params = get_coin_tier_params(ticker, curr_data, strat_config=get_strat_for_mode(eval_mode))
      if not exit_plan:
        atr_pct_val = (curr_data.get('ATR', 0) / curr_data.get('close', 1)) * 100
        target_mult = tier_params.get('target_atr_multiplier', 4.5)
        sl_atr_mult = tier_params.get('atr_mult', 2.0) 
        final_sl = max(-(atr_pct_val * sl_atr_mult), tier_params.get('stop_loss', -3.0))
        expected_target = atr_pct_val * target_mult
        if abs(final_sl) > (expected_target * 0.7): final_sl = -(expected_target * 0.7)
        exit_plan = {
          "target_atr_multiplier": target_mult, "stop_loss": round(final_sl, 2),
          "atr_mult": sl_atr_mult, "timeout": tier_params.get('timeout_candles', 8)
        }
      exit_plan['adaptive_breakeven_buffer'] = tier_params.get('adaptive_breakeven_buffer', 0.007)
      trade_data[ticker] = {
        'high_p': final_buy_price, 'entry_atr': curr_data.get('ATR', 0), 'guard': False,
        'buy_ind': curr_data if isinstance(curr_data, dict) else curr_data.to_dict(), 
        'last_notified_step': 0, 'buy_ts': now_ts, 'exit_plan': exit_plan, 'buy_reason': reason, 
        'btc_buy_price': REALTIME_PRICES.get('KRW-BTC', 0), 'pass_score': pass_score, 
        'is_runner': False, 'score_history': [pass_score], 'strategy_mode': buy_mode
      }
      TRADE_DATA_DIRTY = True
      await record_trade_db(ticker, 'BUY', final_buy_price, buy_amt, profit_krw=0, reason=reason, status="ENTERED", rating=int(score), pass_score=pass_score, strategy_mode=eval_mode)    
      btc_data = await get_btc_short_term_data()
      btc_rsi = btc_data.get('rsi', 0)
      mode_icon = "📉" if eval_mode == "CLASSIC" else "🚀"
      safe_reason = str(reason).replace('<', '&lt;').replace('>', '&gt;')
      if buy_mode == "SNIPER" or "선제공격" in str(reason):
        await send_msg(f"🎯 <b>스나이퍼 매수 완료</b> [{buy_mode}]\n- 종목: {ticker} (파이썬:{pass_score:.1f}점)\n- <b>시황: BTC RSI {btc_rsi}</b> {mode_icon}\n- <b>금액: {buy_amt:,.0f}원</b>\n👉 <b>사후 분석 대기중.</b>")
        mtf = await get_mtf_trend(ticker)
        asyncio.create_task(background_ai_post_report(ticker, curr_data, mtf, final_buy_price, pass_score, eval_mode))
      else:
        await send_msg(f"✅ <b>매수 승인</b> [{buy_mode}]\n- 종목: {ticker} ({pass_score:.1f} ➡️ AI:{score:.1f}점)\n- <b>시황: BTC RSI {btc_rsi}</b> {mode_icon}\n- <b>금액: {buy_amt:,.0f}원</b>\n- 분석: {safe_reason}")
      return True
    else:
      await send_msg(f"🚫 <b>매수 취소</b>: {ticker} 스마트 매수 실패.\n- 사유: {fail_reason}")
  return False
async def run_full_scan(is_deep_scan=False):
  global consecutive_empty_scans, last_global_buy_time, SYSTEM_STATUS, LATEST_TOP_PASS_SCORE 
  if SCAN_LOCK.locked():
    if not is_deep_scan: 
      await send_msg("⏳ 현재 다른 스캔/작업이 진행 중입니다. 종료 후 자동으로 시작합니다.")
    logging.info("스캔 대기 중 (Lock 활성화 상태)...")
  async with SCAN_LOCK:
    btc_short = await get_btc_short_term_data() 
    regime = await get_market_regime()
    fgi_str = regime.get('fear_and_greed', '')
    try:
      fgi_val = int(re.search(r'\d+', fgi_str).group()) if re.search(r'\d+', fgi_str) else 50
    except: fgi_val = 50
    btc_rsi = btc_short.get('rsi', 50.0)
    #  [ 시 모드 환] BTC RSI 기반 로 CLASSIC/QUANTUM 결정
    if btc_rsi <= 42:
      current_regime_mode = "CLASSIC" 
      new_status = f"📉 Classic (BTC RSI:{btc_rsi} - Oversold Sniper)"
    elif btc_rsi >= 58:
      current_regime_mode = "QUANTUM" 
      new_status = f" Quantum (BTC RSI:{btc_rsi} - Trend Breakout)"
    if fgi_val <= 35 or (btc_short['trend'] == "단기 하락" and fgi_val <= 50):
      current_regime_mode = "CLASSIC" 
      new_status = f"📉 Classic (FGI Low - Deep Dip)"
    elif fgi_val >= 65 or (btc_short['trend'] == "단기 상승" and fgi_val >= 50):
      current_regime_mode = "QUANTUM" 
      new_status = f" Quantum (FGI High - Trend Ride)"
    else:
      current_regime_mode = "HYBRID" 
      new_status = f"⚖️ Hybrid (BTC RSI:{btc_rsi} - Adaptive)"
      SYSTEM_STATUS = "정상 감시 중"
    if is_deep_scan: 
      try:
        await asyncio.wait_for(update_top_volume_tickers(), timeout=60.0)
      except asyncio.TimeoutError:
        logging.error("⚠️ 상위 종목 리스트 갱신 시간 초과. 다음 턴을 노립니다.")
    balances = await execute_upbit_api(upbit.get_balances)
    if not isinstance(balances, list): return
    cash = safe_float(next((b.get('balance') for b in balances if isinstance(b, dict) and b.get('currency') == "KRW"), 0.0))
    held_dict = {f"KRW-{b.get('currency')}": safe_float(b.get('avg_buy_price')) for b in balances if isinstance(b, dict) and b.get('currency') != "KRW" and (safe_float(b.get('balance')) + safe_float(b.get('locked'))) * safe_float(b.get('avg_buy_price')) >= 5000}
    #  [보안 2] 령  기 (Ghost Position Sync)
    # 비 제 고  trade_data 조하 동 매도 으 한 불일 거
    # ( 최근 30 내 매수 코인  고 갱신 지 을 고려 여  명단 서 면제)
    now_ts = time.time()
    ghosts = [t for t in list(trade_data.keys()) if t not in held_dict and (now_ts - trade_data[t].get('buy_ts', 0)) > 30]
    if ghosts:
      for g in ghosts:
        logging.warning(f"🧹 [데이터 동기화] 유령 포지션 발견 및 제거: {g}")
        del trade_data[g]
      TRADE_DATA_DIRTY = True
    total_asset = cash
    for b in balances:
      if isinstance(b, dict) and b.get('currency') and b.get('currency') != "KRW":
        ticker = f"KRW-{b.get('currency')}"
        avg_p = safe_float(b.get('avg_buy_price'))
        p = safe_float(REALTIME_PRICES.get(ticker, avg_p))
        total_asset += (safe_float(b.get('balance')) + safe_float(b.get('locked'))) * p
    base_max_trades = STRAT.get('max_concurrent_trades', GLOBAL_MAX_POSITIONS)
    dynamic_max_trades = base_max_trades
    if btc_short.get('is_risky', False):
      dynamic_max_trades = max(1, base_max_trades // 2)
    elif fgi_val <= 25: 
      dynamic_max_trades = max(2, base_max_trades - 1)
    if cash < 6000 or len(held_dict) >= dynamic_max_trades:
      if is_deep_scan:
        reason = "현금 부족 (6,000원 미만)" if cash < 6000 else f"매수 슬롯 한도 도달 (현재 안전 한도: {dynamic_max_trades}개)"
        await send_msg(f"⏳ <b>매수 탐색 중단</b>: {reason}. 현금 비중을 유지하며 관망합니다.")
      last_global_buy_time = time.time(); return
    async def fetch_data(ticker):
      async with GLOBAL_API_SEMAPHORE:
        p, c = await get_indicators(ticker)
        return ticker, p, c #  MTF 거 ( 기 출 
    fetch_tasks = [fetch_data(t) for t in STRAT['tickers']]
    indicator_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
    #  결과 구조 변 (p, c) 3개짜리로 받음
    indicator_results = [res for res in indicator_results if isinstance(res, tuple) and len(res) == 3]
    #  [병렬 1 계] 1 차 사 (API 미호 구간 - 0.001  
    passed_1st_stage = []
    current_loop_max_score = 0
    new_scan_data = {}
    for t, prev, curr in indicator_results:
      if curr is None or prev is None: continue
      if isinstance(prev, pd.Series): prev = prev.to_dict()
      if isinstance(curr, pd.Series): curr = curr.to_dict()
      if not isinstance(prev, dict) or not isinstance(curr, dict): continue
      score_1st, fatal_1st, pass_cut_1st, mode_1st = evaluate_coin_fundamental_sync(t, prev, curr, current_regime_mode, fgi_val, btc_short["trend"], mtf_data=None)
      if fatal_1st or score_1st < pass_cut_1st:
        new_scan_data[t] = {"score": score_1st, "reason": fatal_1st if fatal_1st else "PASS", "price": safe_float(curr.get("close")), "mode": mode_1st, "mtf": "스킵 (기준미달)"}
        continue
      passed_1st_stage.append((t, prev, curr, mode_1st, pass_cut_1st))
    #  [병렬 2 계] 1 격 들  MTF 시 조회   채점
    python_passed = []
    async def _fetch_mtf_and_eval(t, prev, curr, mode, pass_cut):
      mtf_res = await get_mtf_trend(t)
      #  2   사 (MTF 함)
      f_score, f_fatal, f_pass_cut, f_mode = evaluate_coin_fundamental_sync(t, prev, curr, current_regime_mode, fgi_val, btc_short['trend'], force_eval_mode=mode, mtf_data=mtf_res)
      return t, f_score, f_fatal, mtf_res, prev, curr, f_mode, f_pass_cut
    if passed_1st_stage:
      mtf_tasks = [_fetch_mtf_and_eval(*args) for args in passed_1st_stage]
      mtf_results = await asyncio.gather(*mtf_tasks, return_exceptions=True)
      for res in mtf_results:
        if isinstance(res, Exception): continue
        t, f_score, f_fatal, mtf_res, prev, curr, mode, pass_cut = res
        #  [ 정 2] 1차  과 코인 MTF 이 싱  Dict/Str) 러 벽 방어
        mtf_str_display = mtf_res.get('str', '조회 실패') if isinstance(mtf_res, dict) else str(mtf_res)
        new_scan_data[t] = {"score": f_score, "reason": f_fatal if f_fatal else "PASS", "price": safe_float(curr.get('close')), "mode": mode, "mtf": mtf_str_display}
        if f_fatal or f_score < pass_cut: continue
        if t in held_dict or (time.time() - last_sell_time.get(t, 0)) < 1800: continue
        python_passed.append({"t": t, "score": f_score, "data": curr, "prev_data": prev, "mtf": mtf_res, "mode": mode, "pass_cut": pass_cut})
    # 역 캐 이 데 트
    global LATEST_SCAN_RESULTS, LATEST_SCAN_TS
    LATEST_SCAN_RESULTS = new_scan_data
    LATEST_SCAN_TS = time.time()
    LATEST_TOP_PASS_SCORE = current_loop_max_score
    # ️ [Golden Balance] 고확 수 으 렬 ( 능 검 료)
    python_passed.sort(key=lambda x: x['score'], reverse=True)
    python_passed = python_passed[:3]
    if not python_passed:
      if is_deep_scan:
        await send_msg(f"🔍 <b>스캔 결과</b>: ❌ 현재 차트 조건을 만족하는 종목이 없습니다.")
        consecutive_empty_scans += 1
      else:
        await send_msg("🔍 <b>수동 스캔 결과</b>: ❌ 현재 차트 조건(점수)을 만족하는 코인이 하나도 없습니다.")
      return
    report_msg = "🔍 <b>[파이썬 엔진 1차 통과 종목]</b>\n"
    for p in python_passed:
      mode_icon = "🚀" if p['mode'] == "QUANTUM" else "📉"
      report_msg += f" {p['t']} : {p['score']:.1f} ({mode_icon} {p['mode']})\n"
    await send_msg(report_msg)
    #  [병렬 3 계]  님   이    리  )  AI 면접 모두 시 행!
    ai_approved = []
    ai_rejected = []
    success_count = 0 
    global_rag_context = await get_rag_context()
    # [ 기 AI 면접 리  계산 에 합 리스 기반 금액 용
    est_buy_amt = calculate_optimized_buy_amt(total_asset, cash, 2.0) # 기본 2% ATR 가 
    async def _prep_and_analyze_ai(p):
      ai_data = extract_ai_essential_data(p['data'].to_dict()) if hasattr(p['data'], 'to_dict') else p['data'].copy()
      ai_data['strategy_mode'] = p['mode']
      ai_data['python_pass_score'] = p['score']
      ai_data['prev_close'] = p['prev_data'].get('close', '알수없음') if isinstance(p.get('prev_data'), dict) else '알수없음'
      ai_data['realtime_cvd'] = REALTIME_CVD.get(p['t'], 0.0)
      ai_data['btc_short_trend'] = btc_short.get('trend', '알수없음')
      #  [극강 최적    이   리  계산조차 병렬( 시) 가 옵 다!
      ob_task = execute_upbit_api(pyupbit.get_orderbook, p['t'])
      slip_task = calculate_expected_slippage(p['t'], est_buy_amt)
      ob, exp_slip = await asyncio.gather(ob_task, slip_task, return_exceptions=True)
      if not isinstance(ob, Exception) and ob and 'total_bid_size' in ob and 'total_ask_size' in ob:
        tb, ta = ob['total_bid_size'], ob['total_ask_size']
        ai_data['ob_imbalance'] = round(ta / tb, 2) if tb > 0 else "알수없음"
      else:
        ai_data['ob_imbalance'] = "알수없음"
      exp_slip = exp_slip if not isinstance(exp_slip, Exception) else 0.0
      mtf_val = p.get('mtf', '알수없음')
      mtf_str_for_buy = mtf_val.get('str', '알수없음') if isinstance(mtf_val, dict) else str(mtf_val)
      exit_preview = get_exit_plan_preview(p['t'], ai_data, eval_mode=p['mode'])
      intent = "상승 추세 중 눌림목 매수 (Pullback)" if p['mode'] == "QUANTUM" else "낙폭 과대 구간 역추세 매매 (Deep Dip)"
      tier = get_coin_tier(p['t'], p['data'])
      ana = await ai_analyze(p['t'], ai_data, mode="BUY", eval_mode=p['mode'], ignore_cooldown=True, mtf_trend=mtf_str_for_buy, market_regime=regime, rag_context=global_rag_context, expected_slippage=round(exp_slip, 2), exit_plan_preview=exit_preview, strategy_intent=intent, coin_tier=tier)
      return p, ana
    #  3명의 격  3명의 면접관(  이) 방에 시 밀 습 다.
    if python_passed:
      ai_tasks = [_prep_and_analyze_ai(p) for p in python_passed]
      ai_results = await asyncio.gather(*ai_tasks, return_exceptions=True)
      for res in ai_results:
        if isinstance(res, Exception): continue
        p, ana = res
        if ana and ana.get('decision') == "BUY":
          #  [Step 5: Cross-Validation] 진 수  AI 수 호 검 (Consensus Rule)
          algo_score = p['score']
          ai_score = ana.get('score', 0)
          pass_cut = p['pass_cut']
          # 보수 관 채택: AI 수가 고리즘 과 들(pass_cut)  못하 기각
          if ai_score < pass_cut:
            reason = f"AI 점수 미달 ({ai_score} < {pass_cut})"
            ai_rejected.append({"t": p['t'], "reason": reason})
            continue
          ai_approved.append({
            "t": p['t'], "final_score": (algo_score + ai_score) / 2.0, "decision": "BUY", 
            "reason": ana['reason'], "exit_plan": ana['exit_plan'], 
            "data": p['data'], "mode": p['mode'], "pass_score": p['score']
          })
        elif ana:
          risk_reason = str(ana.get('risk_opinion', ana.get('reason', '사유 없음'))).replace('<', '&lt;').replace('>', '&gt;')
          ai_rejected.append({
            "t": p['t'], 
            "reason": risk_reason, 
            "is_system_error": ana.get('system_error', False)
          })
    reject_msg_str = ""
    if ai_rejected:
      reject_msg_str = "\n🚫 <b>[AI 거절 종목]</b>\n"
      for r in ai_rejected:
        reject_msg_str += f" {r['t']} : {r['reason']}\n"
    #  [추 ] 매수 코인 더 도, 면접 서 어 코인 다 미리 브리 을 니 
    if ai_approved and ai_rejected:
      await send_msg(f"📋 <b>[AI 면접 탈락 브리핑]</b>{reject_msg_str}")
    if ai_approved:
      ai_approved.sort(key=lambda x: x.get('final_score', 0), reverse=True)
      top_coin = ai_approved[0]
      final_buy_targets = [top_coin]
      skipped_coins = []
      for item in ai_approved[1:]:
        if is_highly_correlated(top_coin['t'], item['t']): 
          skipped_coins.append(item['t'])
        else: 
          final_buy_targets.append(item)
      if skipped_coins: 
        await send_msg(f"🔗 <b>유사성 필터]</b> 1위({top_coin['t']})와 85% 이상 중복되어 매수 취소: {', '.join(skipped_coins)}")
      # (success_count 단 서  0 로 초기 됨)
      for app in final_buy_targets:
        buy_succeeded = await process_buy_order(app['t'], app['final_score'], app['reason'], app['data'], total_asset, cash, len(held_dict), app['exit_plan'], buy_mode=app['mode'], pass_score=app['pass_score'])
        if buy_succeeded:
          success_count += 1
          cash -= (total_asset / STRAT.get('max_concurrent_trades', GLOBAL_MAX_POSITIONS))
          held_dict[app['t']] = 0
    else:
      await send_msg(f"🔍 <b>스캔 결과</b>: ❌ 파이썬 통과 종목 중 AI 승인 종목 없음.{reject_msg_str}")
    if is_deep_scan:
      if success_count > 0: consecutive_empty_scans = 0
      else: consecutive_empty_scans += 1
# --- [6. 합 메인 진  산 관 ---
async def background_scan_task(is_deep):
  try: 
    await run_full_scan(is_deep_scan=is_deep)
  except Exception as e: 
    logging.error(f"설정 파일 저장 중 최종 에러: {e}")
async def build_report(header="실시간 리포트", is_running=True):
  balances = await execute_upbit_api(upbit.get_balances)
  if not isinstance(balances, list): return "데이터 조회 실패"
  cash = safe_float(next((b.get('balance') for b in balances if isinstance(b, dict) and b.get('currency') == "KRW"), 0.0))
  coins = []
  total = cash
  for b in balances:
    if isinstance(b, dict) and b.get('currency') and b.get('currency') != "KRW":
      ticker = f"KRW-{b.get('currency')}"
      avg_p = safe_float(b.get('avg_buy_price'))
      qty = safe_float(b.get('balance')) + safe_float(b.get('locked'))
      curr_p = safe_float(REALTIME_PRICES.get(ticker, avg_p))
      val = qty * curr_p
      total += val
      invested_krw = qty * avg_p
      earned_krw = val
      net_profit = earned_krw - invested_krw
      net_rate = (net_profit / invested_krw) * 100 if invested_krw > 0 else 0
      coins.append({'t': ticker, 'r': net_rate, 'pft': net_profit, 'val': val})
  wr, tc, wc, tp, _, recent_losses = await get_performance_stats_db()
  scan_interval_min = STRAT.get('deep_scan_interval', 900) // 60
  #  [보고체계 복구 3] 재 가 중인 모드(Regime) 맞는 략 정 가 오 
  report_eval_mode = "CLASSIC" if "Classic" in SYSTEM_STATUS else "QUANTUM"
  current_strat = get_strat_for_mode(report_eval_mode)
  pass_score_threshold = current_strat.get('pass_score_threshold', 80)
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
  score_display = f"{int(current_pass_score)}점" if current_pass_score > -900 else "-점(대기중)"
  #  [보고체계 복구 4] 성 지  가중치, 안전 장치지침을 재 모드(Classic/Quantum) 맞게 더 
  guideline = str(current_strat.get('exit_plan_guideline', '특별한 지침 없음')).replace('<', '&lt;').replace('>', '&gt;')
  indicator_weights_str = ", ".join([f"{k.upper()}: {v}" for k, v in current_strat.get('indicator_weights', {}).items()])
  trend_logic_str = ", ".join(current_strat.get('trend_active_logic', []))
  range_logic_str = ", ".join(current_strat.get('range_active_logic', []))
  msg = (
    f" <b>[{header}]</b> {' 가동 중' if is_running else '🔴 정지 중'}"
    ""
    f"🎯 <b>상태: {SYSTEM_STATUS}</b>\n" 
    f"━━━━━━━━━━━━━━━━━\n"
    f"🏦 <b>자산 현황</b>\n"
    f" ├ 💰 총 자산: {total:,.0f}원\n"
    f" └ 💵 가용 현금: {cash:,.0f}원\n\n"
    f"📈 <b>누적 퍼포먼스</b>\n"
    f" ├ 💸 누적 손익: {tp:,.0f}원\n"
    f" └ 🎯 승률: {wr:.1f}% ({tc}전 {wc}승)\n\n"
    f"⚙️ <b>통합 엔진 세팅</b>\n"
    f" ├ ⏱️ 스캔 주기: {scan_interval_min}분\n"
    f" └ 스코어({score_label}): {score_display} / {pass_score_threshold}점\n\n"
    f"🚀 <b>활성 지표 (가중치)</b>\n"
    f" 추세: {trend_logic_str}\n"
    f" ├ 횡보: {range_logic_str}\n"
    f" {indicator_weights_str}\n\n"
    f"📜 <b>작전 지침</b>\n"
    f" {guideline}\n"
  )
  if coins:
    msg += "\n🎒 <b>[보유 종목 상세]</b>\n"
    for c in coins:
      icon = "🔴" if c['r'] < 0 else "🟢"
      msg += f" {icon} {c['t']} [{c['val']:,.0f} \n  {c['r']:+.2f}% ({c['pft']:,.0f} \n"
  return msg
#  [ 로 교체 코드] 최근 24 간 터  익 RRR) 계산 로직 재
async def daily_settlement_report():
  #  1. 확 24 간 의 간 구합 다.
  yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
  #  2. DB 서 최근 24 간 안 발생 '매도(SELL)' 기록 긁어 니 
  async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
    db.row_factory = aiosqlite.Row
    async with db.execute("SELECT profit_krw FROM trades WHERE side='SELL' AND timestamp >= ?", (yesterday_str,)) as cursor:
      rows = await cursor.fetchall()
      rows = list(rows)
  total_cnt = len(rows)
  wins = [row['profit_krw'] for row in rows if row['profit_krw'] > 0]
  losses = [row['profit_krw'] for row in rows if row['profit_krw'] <= 0]
  win_count = len(wins)
  loss_count = len(losses)
  #  3. 24 간 적 익  레 계산
  daily_profit = sum(wins) + sum(losses)
  win_rate = (win_count / total_cnt * 100) if total_cnt > 0 else 0.0
  #  4. 익 RRR) 계산: ( 균 익 / 균 실 
  avg_win = sum(wins) / win_count if win_count > 0 else 0
  avg_loss = abs(sum(losses) / loss_count) if loss_count > 0 else 0
  if avg_loss > 0:
    pl_ratio_str = f"{avg_win / avg_loss:.2f}"
  else:
    # 실 예 었 경우 처리
    pl_ratio_str = "무손 (MAX)" if avg_win > 0 else "0.00"
  return (
        f"📅 <b>통합 일일 결산 (최근 24H)</b>\n"
        f"💰 <b>일일 손익: {daily_profit:,.0f}원</b>\n"
        f"📈 승률: {win_rate:.1f}% ({total_cnt}전 {win_count}승)\n"
        f"⚖️ 손익비 (RRR): {pl_ratio_str}\n"
  )
async def generate_daily_proposal(bot_name="Hybrid"):
  try:
    today_str = datetime.now().strftime('%Y%m%d')
    async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
      cursor = await db.execute(
        "SELECT id, timestamp, ticker, status, reason, improvement "
        "FROM trades "
        "WHERE status != 'ENTERED' AND is_reported = 0 "
        "ORDER BY id ASC" 
      )
      rows = await cursor.fetchall()
      rows = list(rows)
    if not rows:
      await send_msg(f"📁 <b>{bot_name}</b>: 새로 추가된 AI 제언이 없습니다. (모두 읽음 처리됨)")
      return
    file_name = f"적용제안_{bot_name}_{today_str}.txt"
    file_path = os.path.join(BASE_PATH, file_name)
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
    async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
      reported_ids = [r[0] for r in rows]
      placeholders = ','.join(' ' for _ in reported_ids)
      await db.execute(f"UPDATE trades SET is_reported = 1 WHERE id IN ({placeholders})", reported_ids)
      await db.commit()
    #  [추 ]   습 ( 롬 트 진화) 로 
    proposals_str = ""
    for r in rows:
      if r[5] and r[5] != '없음':
        proposals_str += f"- [{r[2]} | {r[3]}] 제언: {r[5]}\n"
    if proposals_str.strip():
      await send_msg("🧬 <b>AI 자가 학습 시작</b>: 누적된 제언을 분석하여 시스템 프롬프트를 진화시킵니다...")
      for e_mode in ["CLASSIC", "QUANTUM"]:
        #  [ 리 버그 스] AI가 재 지침을 도 기존 지 old_guide) 먼 불러 니 
        conf = CLASSIC_CONF if e_mode == "CLASSIC" else QUANTUM_CONF
        conf_path = CLASSIC_CONFIG_PATH if e_mode == "CLASSIC" else CONFIG_PATH
        old_guide = conf['strategy'].get('exit_plan_guideline', '')
        #  기존 지 old_guide) rag_context 라미터 해 AI 게 달 니 
        evolve_res = await ai_analyze("ALL", proposals_str, mode="EVOLVE_PROMPT", eval_mode=e_mode, rag_context=old_guide)
        if evolve_res and evolve_res.get('new_guideline'):
          new_guide = evolve_res['new_guideline']
          #  변  존재 경우 만  기 시  림 송
          if new_guide and new_guide != old_guide:
            conf['strategy']['exit_plan_guideline'] = new_guide
            #  [ 러 스] 레그램 HTML 싱 러(unsupported start tag) 천 차단
            safe_old = str(old_guide).replace('<', '&lt;').replace('>', '&gt;')
            safe_new = str(new_guide).replace('<', '&lt;').replace('>', '&gt;')
            safe_reason = str(evolve_res.get('reason', 'N/A')).replace('<', '&lt;').replace('>', '&gt;')
            await send_msg(f"✨ <b>[{e_mode} 지침 진화 완료]</b>\n- 기존: {safe_old}\n- <b>신규: {safe_new}</b>\n(사유: {safe_reason})")
    try:
      with open(file_path, "rb") as doc:
        await bot.send_document(chat_id=TG_CONF['chat_id'], document=doc, caption=f"📁 {bot_name} 신규 적용 제안 리포트 도착!\n중복이 제거된 최신 내역입니다.")
    except Exception as e:
      logging.error(f"❌ 대시보드 서버 가동 실패: {e}")
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
• <b>롤백</b> : AI 최적화 이전 상태로 마스터 전략 긴급 복구
• <b>점수</b> : 🔍 [디버그] 감시 대상 종목 실시간 점수 랭킹 확인
"""
async def send_score_debug_report():
  if SCAN_LOCK.locked():
    await send_msg("⏳ 현재 자동 스캔 또는 다른 작업이 진행 중입니다. 조금만 대기해 주세요...")
  async with SCAN_LOCK:
    await send_msg("📊 <b>해당 시점의 모든 관심 종목 점수 산출 중... (잠시만 기다려주세요)</b>")
  regime = await get_market_regime()
  btc_short = await get_btc_short_term_data()
  fgi_str = regime.get('fear_and_greed', '')
  try: fgi_val = int(re.search(r'\d+', fgi_str).group()) if re.search(r'\d+', fgi_str) else 50
  except: fgi_val = 50
  if fgi_val <= 35 or (btc_short['trend'] == "단기 하락" and fgi_val <= 50):
    current_regime_mode = "CLASSIC" 
  elif fgi_val >= 65 or (btc_short['trend'] == "단기 상승" and fgi_val >= 50):
    current_regime_mode = "QUANTUM" 
  else:
    current_regime_mode = "HYBRID" 
  tickers = STRAT.get('tickers', [])
  if not tickers:
    await send_msg("⚠️ 감시 중인 종목이 없습니다.")
    return
  score_results = []
  async def fetch_and_score(t):
    async with GLOBAL_API_SEMAPHORE:
      p, c = await get_indicators(t)
      if p is None or c is None: return None
      if isinstance(p, pd.Series): p = p.to_dict()
      if isinstance(c, pd.Series): c = c.to_dict()
      if not isinstance(p, dict) or not isinstance(c, dict): return None
      #  [ 용 2] 버 모드  줄로 축 료!
      score, fatal_reason, sug_cut, mode = evaluate_coin_fundamental_sync(t, p, c, current_regime_mode, fgi_val, btc_short['trend'])
      return {"t": t, "score": score, "fatal_reason": fatal_reason, "mode": mode}
  tasks = [fetch_and_score(t) for t in tickers]
  results = await asyncio.gather(*tasks, return_exceptions=True)
  for res in results:
    if isinstance(res, dict):
      score_results.append(res)
  score_results.sort(key=lambda x: x['score'], reverse=True)
  #  [추 ] 시 코 황 발신  보고 용 최고 수 역 변 기 
  global LATEST_TOP_PASS_SCORE
  non_fatal_scores = [r['score'] for r in score_results if not r.get('fatal_reason')]
  if non_fatal_scores:
    LATEST_TOP_PASS_SCORE = max(non_fatal_scores)
  else:
    LATEST_TOP_PASS_SCORE = 0
  msg = f"📊 <b>[디버그] 실시간 종목 점수 (기준: {current_regime_mode})</b>\n\n"
  for i, res in enumerate(score_results[:20]): 
    icon = "🚀" if res['mode'] == "QUANTUM" else "📉"
    #  [버그 스] fatal_reason 의 부 호(<, >) 레그램 해   도 안전 장치게 치환
    safe_fatal_reason = str(res['fatal_reason']).replace('<', '&lt;').replace('>', '&gt;') if res['fatal_reason'] else ""
    fatal_tag = f" ({safe_fatal_reason})" if safe_fatal_reason else ""
    msg += f"{i+1}. {res['t']} : <b>{res['score']:.1f} /b> ({icon}){fatal_tag}\n"
  await send_msg(msg)
async def handle_telegram_updates():
  global last_update_id, is_running, TRADE_DATA_DIRTY
  logging.info("텔레그램 명령 처리 태스크 시작")
  if last_update_id is None:
    try:
      updates = await bot.get_updates(offset=-1, limit=1)
      if updates:
        last_update_id = updates[-1].update_id + 1
      else:
        last_update_id = None
    except Exception:
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
        if cmd == "보고": await send_msg(await build_report("통합 실시간 보고", is_running))
        elif cmd == "명령어": await send_msg(COMMAND_HELP_MSG)
        elif cmd == "최적화": 
          regime = await get_market_regime()
          btc_short = await get_btc_short_term_data()
          fgi_str = regime.get('fear_and_greed', '')
          fgi_val = int(re.search(r'\d+', fgi_str).group()) if re.search(r'\d+', fgi_str) else 50
          if fgi_val <= 35 or (btc_short['trend'] == "단기 하락" and fgi_val <= 50):
            eval_mode = "CLASSIC"
          else:
            eval_mode = "QUANTUM"
          await ai_self_optimize(trigger="auto", eval_mode=eval_mode) # 합 략 동 최적 
          # 합 진  hybrid self-optimize 용 니 
        elif cmd == "시작": is_running = True; await send_msg("🟢 가동")
        elif cmd == "정지": is_running = False; await send_msg("🔴 정지")
        elif cmd == "매수": 
          #  [개선] SCAN_LOCK 직접 체크 여 중복 행 방 ( 시 행  에  
          await send_msg("🚀 <b>수동 정밀 스캔 가동</b> (방어막 무시)")
          asyncio.create_task(run_full_scan(is_deep_scan=False))  
        elif cmd == "제안":
          await send_msg("📁 <b>AI 제언 리포트 생성 중...</b>")
          asyncio.create_task(generate_daily_proposal())
        #  [Step 4 심: 롤백 명령 추 ]
        elif cmd == "롤백":
          try:
            backup_q_path = CONFIG_PATH.replace(".json", "_backup.json")
            backup_c_path = CLASSIC_CONFIG_PATH.replace(".json", "_backup.json")
            if os.path.exists(backup_q_path) and os.path.exists(backup_c_path):
              with open(backup_q_path, 'r', encoding='utf-8') as f: q_back = json.load(f)
              with open(backup_c_path, 'r', encoding='utf-8') as f: c_back = json.load(f)
              # 본 일  기
              await save_config_async(q_back, CONFIG_PATH)
              await save_config_async(c_back, CLASSIC_CONFIG_PATH)
              # 메모 태 즉시 반영
              global QUANTUM_CONF, CLASSIC_CONF, STRAT
              QUANTUM_CONF, CLASSIC_CONF = q_back, c_back
              STRAT = QUANTUM_CONF['strategy'] if "Quantum" in SYSTEM_STATUS else CLASSIC_CONF['strategy']
              #  [개선 3- 롤백 여 찌꺼 캐시) 안전 장치초기 
              async with INDICATOR_CACHE_LOCK: INDICATOR_CACHE.clear()
              async with OHLCV_CACHE_LOCK: OHLCV_CACHE.clear()
              await clean_unused_caches()
              await send_msg("⏪ <b>[긴급 롤백 완료]</b>\n전략 복구 및 인디케이터 캐시 초기화가 완료되었습니다.")
            else:
              await send_msg("⚠️ 백업 파일이 아직 존재하지 않습니다.")
          except Exception as e:
            await send_msg(f"❌ 롤백 실패: {e}")
        elif cmd == "점수":
          asyncio.create_task(send_score_debug_report())
        elif "매도" in cmd: # "/매도", "매도 " 모두 통 게 찰떡같이 식 니 
          balances = await execute_upbit_api(upbit.get_balances)
          # Type validation for balances response
          if not isinstance(balances, list):
            await send_msg("❌ 잔고 조회 실패 (API 오류)")
            continue
          # trade_data 더 도 제 5000 상 고 으 모두 강제 매도  에 함 ( 명 코인 방 )
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
            #  [ 심 방어] 비 는 5000 미만 매도 러 뿜습 다. 
            # 러가 무한 시 무한 루프) 발 여 레그램 봇을 마비 키 것을 천 차단!
            if qty * _avg_p < 5000:
              logging.warning(f"⚠️ {t_ticker} 잔고 5000원 미만으로 매도 스킵 (짜투리 코인)")
              continue
            invested_krw = _avg_p * qty * 1.0005
            earned_krw = qty * _avg_p * 0.9995
            p_krw = earned_krw - invested_krw
            await execute_upbit_api(upbit.sell_market_order, t_ticker, qty)
            t_data = trade_data.get(t_ticker, {})
            m = t_data.get('strategy_mode', 'UNKNOWN')
            await record_trade_db(t_ticker, 'SELL', _avg_p, qty, profit_krw=p_krw, reason=f"[{t_ticker}] {t_data.get('buy_reason', '')}", status="PARTIAL_SUCCESS", rating=80, pass_score=t_data.get('pass_score', 0), strategy_mode=m)
            now_ts = time.time()
            last_sell_time[t_ticker] = now_ts
            sold_count += 1
          #  [고아 코인 발생 차단] 째 리지 고, 번 동 로 '매도 도 종목' 추려 어  니 
          for t_ticker in held_for_sell.keys():
            if t_ticker in trade_data:
              del trade_data[t_ticker]
          TRADE_DATA_DIRTY = True
          await send_msg(f"🚨 <b>통합 수동 전량 매도 완료 ({sold_count}개 종목 청산)</b>")
        elif cmd == "주소" or cmd == "링크":
          dashboard_url = STRAT.get('external_dashboard_url', 'http://localhost:8080')
          await send_msg(f"🌐 <b>ATS 대시보드 접속 주소</b>\n\n대시보드: {dashboard_url}\n로그 확인: {dashboard_url}/log\n\n* 외부 접속 시 Tunnel(Cloudflare, Tailscale 등)이 설정되어 있어야 합니다.")
    except asyncio.TimeoutError: pass
    except telegram.error.NetworkError: await asyncio.sleep(1.0)
    except Exception as e:
      logging.error(f"❗ 텔레그램 루프 에러: {e}")
      await asyncio.sleep(1.0)
    await asyncio.sleep(0.5)
#  [ 술 료] 메인 감시 루프 레   애 한 백그 운 매도 리포 성 
async def background_sell_report(ticker, real_price, sell_qty, p_krw, p_rate, sell_reason_str, analyze_payload):
  try:
    eval_mode = analyze_payload.get('strategy_mode', 'QUANTUM')
    ai_r = await ai_analyze(ticker, analyze_payload, mode="SELL_REASON", eval_mode=eval_mode, ignore_cooldown=True) 
    ai_rating = ai_r.get('rating', 0) if isinstance(ai_r, dict) else 0
    ai_status = ai_r.get('status', 'UNKNOWN') if isinstance(ai_r, dict) else 'UNKNOWN'
    ai_msg = str(ai_r.get('reason', str(ai_r))).replace('<', '&lt;').replace('>', '&gt;') if isinstance(ai_r, dict) else str(ai_r)
    ai_improvement = str(ai_r.get('improvement', '없음')).replace('<', '&lt;').replace('>', '&gt;') if isinstance(ai_r, dict) else '없음'
    #  [3 언: 코인 DNA 진화 물리 용]
    dna_tweak = ai_r.get('dna_tweak') if isinstance(ai_r, dict) else None
    dna_msg = ""
    if dna_tweak and isinstance(dna_tweak, dict) and len(dna_tweak) > 0:
      global STRAT, QUANTUM_CONF, CLASSIC_CONF
      target_conf = QUANTUM_CONF if eval_mode == "QUANTUM" else CLASSIC_CONF
      conf_path = CONFIG_PATH if eval_mode == "QUANTUM" else CLASSIC_CONFIG_PATH
      if 'ticker_dna' not in target_conf['strategy']: target_conf['strategy']['ticker_dna'] = {}
      if ticker not in target_conf['strategy']['ticker_dna']: target_conf['strategy']['ticker_dna'][ticker] = {}
      #  [ 술 1] DNA 염 방  한 '  안전 장치병합' 수 (   언)
      def apply_dna_safely(old_dict, new_dict):
        for k, v in new_dict.items():
          if isinstance(v, dict):
            if k not in old_dict: old_dict[k] = {}
            apply_dna_safely(old_dict[k], v)
          elif isinstance(v, (int, float)):
            safe_v = float(v)
            #  1.   계 (Clipping): AI가 미쳐 극단 값을 줘도 물리 으 차단
            if 'stop' in k.lower() or 'hard_s' in k.lower(): safe_v = max(-5.0, min(-1.0, safe_v)) # 절  -5% ~ -1% 이
            elif 'target' in k.lower() or 'tp' in k.lower(): safe_v = max(1.0, min(8.0, safe_v))  # 절  1% ~ 8% 이
            elif 'penalty' in k.lower(): safe_v = max(-50.0, min(0.0, safe_v))           # 감점  0 ~ -50 
            elif 'bonus' in k.lower(): safe_v = max(0.0, min(50.0, safe_v))            # 가  0 ~ +50 
            #  2. 기하급수 동 균 (EMA Learning Rate = 0.4)
            # 안전 장치값이 존재 다 기존 DNA 60% + 로 안 40% 어 서 변 무 킵 다.
            if k in old_dict and isinstance(old_dict[k], (int, float)):
              safe_v = (float(old_dict[k]) * 0.6) + (safe_v * 0.4)
            old_dict[k] = round(safe_v, 2)
          else:
            old_dict[k] = v # 문자 불리  그   기
      # 안전 장치병합 수 행
      apply_dna_safely(target_conf['strategy']['ticker_dna'][ticker], dna_tweak)
      # DB(JSON)   메모 시 반영
      await save_config_async(target_conf, conf_path)
      if 'ticker_dna' not in STRAT: STRAT['ticker_dna'] = {}
      if ticker not in STRAT['ticker_dna']: STRAT['ticker_dna'][ticker] = {}
      STRAT['ticker_dna'][ticker].update(target_conf['strategy']['ticker_dna'][ticker])
      dna_msg = f"\n🧬 <b>[DNA 진화]</b> {ticker} 전용 파라미터가 영구 업데이트되었습니다. ({list(dna_tweak.keys())})"
      ai_improvement += f" (DNA 반영 완료)"
    await record_trade_db(ticker, 'SELL', real_price, sell_qty, profit_krw=p_krw, reason=f"[{sell_reason_str}] {ai_msg}", status=ai_status, rating=ai_rating, improvement=ai_improvement, pass_score=analyze_payload.get('pass_score', 0), strategy_mode=eval_mode)
    mode_label = f"[{eval_mode}]"
    mode_icon = "📉" if eval_mode == "CLASSIC" else "🚀"
    telegram_message = f"🔕 <b>최종 청산 완료</b> {mode_label} {mode_icon}\n- 종목: ({ticker})\n- 상태: {ai_status} ({ai_rating}점)\n- 사유: {sell_reason_str}\n- 수익률: {p_rate:+.2f}%\n- 수익금: {p_krw:,.0f}원\n- AI: {ai_msg}"
    if ai_improvement and ai_improvement != '없음': 
      telegram_message += f"\n\n💡 <b>제언</b>: {ai_improvement}{dna_msg}"
    await send_msg(telegram_message)
  except Exception as e:
    logging.error(f"백그라운드 매도 리포트 에러 ({ticker}): {e}")
    await record_trade_db(ticker, "SELL", real_price, sell_qty, profit_krw=p_krw, reason=f"[{sell_reason_str}] AI 통신 지연 (백업 기록)", status="ERROR_FALLBACK", rating=50, pass_score=analyze_payload.get("pass_score", 0), strategy_mode=eval_mode)
    await send_msg(f"🔕 <b>최종 청산 완료 (비상 모드)</b> {mode_label} {mode_icon}\n- 종목: ({ticker})\n- 수익률: {p_rate:+.2f}%\n- 사유: {sell_reason_str}")
#  [Step 4 심: 스 스 체크 (Watchdog)]
# 메인 루프 소켓이 모종 유 멈추 레그램 로 즉시 비상 림 보냅 다.

async def system_watchdog():
  global API_FATAL_ERRORS, last_main_loop_time
  await asyncio.sleep(60) #  초기  
  while True:
    try:
      await asyncio.sleep(60)
      now = time.time()
      #  [개선 3-  치 림 3 계 분 
      # Level 3 (치명)
      if API_FATAL_ERRORS >= 3:
        await send_msg(f"🚨 <b>[FATAL] API 호출 연속 실패!</b>\n누적 치명적 오류가 {API_FATAL_ERRORS}회 발생했습니다. 계정 권한이나 네트워크를 확인하세요.")
        API_FATAL_ERRORS = 0 # 람 초기 
      # Level 2 ( 각)
      elapsed_loop = now - last_main_loop_time
      if elapsed_loop > 180: 
        await send_msg(f"🔥 <b>[CRITICAL] 메인 엔진 정지 감지!</b>\n마지막 심장 박동 후 {int(elapsed_loop)}초가 경과했습니다. 즉시 서버 확인 요망.")
        last_main_loop_time = now 
      # Level 1 (경고)
      active_tickers = set(STRAT.get('tickers', []) + list(trade_data.keys()) + ["KRW-BTC"])
      dead_tickers = [t for t, ts in REALTIME_PRICES_TS.items() if t in active_tickers and now - ts > 300]
      if len(dead_tickers) > 15:
        await send_msg(f"⚠️ <b>데이터 수신 지연 감지</b>\n{len(dead_tickers)}개 종목의 실시간 틱 데이터가 5분 이상 없습니다. (거래량이 마른 코인이거나 업비트 지연)")
        for dt in dead_tickers: REALTIME_PRICES_TS[dt] = now
    except Exception as e:
      logging.error(f"Watchdog 에러: {e}")
async def main():
  global trade_data, BALANCE_CACHE, last_sell_time, is_running, last_global_buy_time, last_deep_scan_ts
  global TRADE_DATA_DIRTY, SYSTEM_STATUS, REALTIME_PRICES, REALTIME_PRICES_TS, INDICATOR_CACHE
  global API_FATAL_ERRORS, last_main_loop_time, instance_lock
  
  try:
    instance_lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    instance_lock.bind(('127.0.0.1', 65433))
  except OSError:
    logging.error("❌ 이미 ATS_Hybrid 봇이 실행 중입니다. 중복 실행을 방지하기 위해 즉시 종료합니다.")
    return
  
  startup_jitter = random.uniform(1.0, 10.0)
  logging.info(f"🚀 API 병목 방지를 위해 {startup_jitter:.2f}초 후 엔진 가동을 시작합니다...")
  await asyncio.sleep(startup_jitter)
  asyncio.create_task(handle_telegram_updates())
  await asyncio.sleep(0.1) 
  
  btc_short_initial = await get_btc_short_term_data()
  regime_initial = await get_market_regime()
  fgi_str_initial = regime_initial.get('fear_and_greed', '')
  try: fgi_val_initial = int(re.search(r'\d+', fgi_str_initial).group()) if re.search(r'\d+', fgi_str_initial) else 50
  except: fgi_val_initial = 50
  
  if fgi_val_initial <= 35 or (btc_short_initial['trend'] == "단기 하락" and fgi_val_initial <= 50):
    SYSTEM_STATUS["status"] = "📉 Classic (Deep Dip Sniper)"
  elif fgi_val_initial >= 65 or (btc_short_initial['trend'] == "단기 상승" and fgi_val_initial >= 50):
    SYSTEM_STATUS["status"] = " Quantum (Trend Breakout)"
  else:
    SYSTEM_STATUS["status"] = "⚖️ Hybrid (Adaptive Monitoring)"
    
  logging.info(f"ATS 통합 엔진 시작 ({SYSTEM_STATUS['status']} 모드)")
  await send_msg(f"⚔️ <b>ATS_Hybrid 가동 시작</b> ({SYSTEM_STATUS['status']} 모드)\n\n{COMMAND_HELP_MSG}")
  await init_db()
  trade_data = await load_trade_status_db()
  asyncio.create_task(websocket_ticker_task())
  asyncio.create_task(system_watchdog()) #  치 행!
  asyncio.create_task(run_fastapi_server()) #   보 버 합
  last_report_time = time.time()
  last_loss_check_time = time.time()
  last_checked_win_rate = 100.0
  last_daily_report_day = datetime.now().day
  last_proposal_day = None
  #  [ 비] 역 변 초기 는 일 단(L1255)  main() 작 L3090) 서 료 
  async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
    async with db.execute("SELECT ticker, timestamp FROM trades WHERE side='SELL' ORDER BY id DESC LIMIT 50") as cursor:
      async for row in cursor:
        ticker, ts_str = row[0], row[1]
        t_time = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').timestamp()
        if time.time() - t_time < 1800:
          if ticker not in last_sell_time or last_sell_time[ticker] < t_time:
            last_sell_time[ticker] = t_time
  current_balances = await execute_upbit_api(upbit.get_balances)
  if isinstance(current_balances, list):
    # 재 비 에 제 5,000 상 보유 중인 코인 목록
    real_held = [f"KRW-{b['currency']}" for b in current_balances if b['currency'] != 'KRW' and (float(b['balance']) + float(b['locked'])) * float(b['avg_buy_price']) >= 5000]
    #  1.  령 코인  (최근 30 내 매수 건  외)
    now_ts = time.time()
    ghost_coins = [t for t in list(trade_data.keys()) if t not in real_held and (now_ts - trade_data[t].get('buy_ts', 0)) > 30]
    for gc in ghost_coins:
      logging.warning(f"🧹 [데이터 동기화] 유령 코인 정리: {gc} (실제 잔고 없음)")
      del trade_data[gc]
      TRADE_DATA_DIRTY = True
    #  2.  미아 코인 양 ( 제 고 는 DB 는 경우)
    for t in real_held:
      if t not in trade_data:
        logging.warning(f"👶 미아 코인 입양: {t} (DB 누락 복구)")
        b = next(x for x in current_balances if f"KRW-{x['currency']}" == t)
        avg_p = float(b['avg_buy_price'])
        #  [Pylance 방어] 양 이 화 로직 강화
        _, curr_ind_raw = await get_indicators(t)
        if curr_ind_raw is None:
          curr_ind_dict = {}
        else:
          curr_ind_dict = curr_ind_raw if isinstance(curr_ind_raw, dict) else curr_ind_raw.to_dict()
        real_atr = curr_ind_dict.get('ATR', avg_p * 0.02) if curr_ind_dict else (avg_p * 0.02)
        tier_params = get_coin_tier_params(t, curr_ind_dict, strat_config=get_strat_for_mode(initial_eval_mode))
        #  [ 양 로직 개선] 재 장 황 맞춰 strategy_mode 결정
        initial_eval_mode = "QUANTUM" if safe_float(curr_ind_dict.get('adx')) > 25 else "CLASSIC"
        if "Classic" in SYSTEM_STATUS: initial_eval_mode = "CLASSIC"
        elif "Quantum" in SYSTEM_STATUS: initial_eval_mode = "QUANTUM"
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
          'pass_score': 80, 'is_runner': False, 'score_history': [],
          'strategy_mode': initial_eval_mode
        }
        TRADE_DATA_DIRTY = True
  await send_msg(await build_report("초기 보고", True))
  #  [버그 스] 중복 캔 방  해 작 캔 행  머 미리 팅 니 
  global last_deep_scan_ts
  last_deep_scan_ts = time.time()
  asyncio.create_task(background_scan_task(True)) #  [ 정] 로그램 작 바로 캔 작
  last_global_buy_time = time.time()
  asyncio.create_task(db_flush_task())
  asyncio.create_task(cache_cleanup_task())
  await asyncio.sleep(3)
  while True:
    try:
      await asyncio.sleep(0.1) 
      if not is_running:
        await asyncio.sleep(0.5)
        continue
      now_ts, now_dt = time.time(), datetime.now()
      global last_main_loop_time
      last_main_loop_time = now_ts #  메인 루프가 상 으 고 음 치 에 보고 ( 장 박동)
      if now_ts - BALANCE_CACHE['timestamp'] > BALANCE_CACHE_SEC: 
        BALANCE_CACHE['data'] = await execute_upbit_api(upbit.get_balances)
        BALANCE_CACHE['timestamp'] = now_ts
      balances = BALANCE_CACHE['data']
      if not balances or not isinstance(balances, list): 
        await asyncio.sleep(1.0)
        continue
      #  [Pylance 방어] cash 안전 장치추출
      #  [FIX: 변 명 복구  방어] main 루프 서 held_dict가 니 held 용 야 며, 값도 float 닌 b( 셔 리) 체 야 니 
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
      #  [추 ] 반복문을 기 에 재 장 씨(Regime) 번만 악 니 ( 도  상)
      regime = await get_market_regime()
      fgi_str = regime.get('fear_and_greed', '')
      try: fgi_val = int(re.search(r'\d+', fgi_str).group()) if re.search(r'\d+', fgi_str) else 50
      except: fgi_val = 50
      if fgi_val <= 35 or (btc_short.get('trend') == "단기 하락" and fgi_val <= 50):
        current_regime_mode = "CLASSIC" 
      elif fgi_val >= 65 or (btc_short.get('trend') == "단기 상승" and fgi_val >= 50):
        current_regime_mode = "QUANTUM" 
      else:
        current_regime_mode = "HYBRID"
      #  [Final Shield] 지 24 간 안 실 기록 가   패 방어 준 
      _, _, _, _, _, recent_losses = await get_performance_stats_db()
      last_24h_ts = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
      recent_losses = [l for l in recent_losses if l.get('timestamp', '0000') > last_24h_ts]
      # 제 개별 코인 검   작 니 
      for ticker in monitoring_tickers:
        #  [Final Shield] 최근 24 간 2 패 중인 종목  진입 금 
        ticker_loss_count = sum(1 for l in recent_losses if l['ticker'] == ticker)
        if ticker not in held and ticker_loss_count >= 2:
          if random.random() < 0.01: logging.info(f"🛡️ {ticker} 연패 방어 쿨다운 중 (Skip)")
          continue
        
        current_live_score = None
        if ticker not in held and ticker in last_sell_time and (now_ts - last_sell_time.get(ticker, 0)) < 1800: 
          continue
        
        if ticker in held:
          #  [ 정 료] 15초에 번만 지  갱신 도 쿨 용
          t_data = trade_data.get(ticker, {})
          if now_ts - t_data.get('last_ind_update_ts', 0) > 15:
            asyncio.create_task(get_indicators(ticker))
            t_data['last_ind_update_ts'] = now_ts
            TRADE_DATA_DIRTY = True
          
          coin = held[ticker]
          #  [Pylance 추 방어] coin 셔 리 서 단가 꺼낼 도 수 safe_float) 과 킵 다.
          avg_p = safe_float(coin.get('avg_buy_price'))
          real_price = REALTIME_PRICES.get(ticker)
          #  [좀 방어 가  이   예 거 15 상 갱신 멈췄 면 
          if not real_price or (time.time() - last_update > 15):
            # 소켓이 죽었거나 당 코인 거래가 멈춘 것이므 REST API 폐 생(직접 조회)
            real_price = safe_float(await execute_upbit_api(pyupbit.get_current_price, ticker))
            REALTIME_PRICES[ticker] = real_price # 가 온 싱 가격으  기
            REALTIME_PRICES_TS[ticker] = time.time() # 간 갱신
          
          if not real_price: continue
          
          # 현재 수익률 계산
          p_rate = ((real_price * 0.9995) / (avg_p * 1.0005) - 1) * 100
          
          # 실시간 지표 및 점수 확보
          _, curr_ind = await get_indicators(ticker)
          current_live_score = 0
          if curr_ind:
              # 동기 함수이므로 await 제거, 4개 변수 언패킹, 명시적 파라미터 맵핑(mtf_data=None, btc_short=btc_short)
              current_live_score, _, _, _ = evaluate_strategy_sync(
                  ticker, curr_ind, curr_ind, fgi_val, mtf_data=None, p_dict=OPTIMIZED_PARAMS, btc_short=btc_short
              )
              t_data['score_history'] = t_data.get('score_history', [])[-19:] + [current_live_score]
          
          ma_live_score = sum(t_data.get('score_history', [50])) / len(t_data.get('score_history', [50]))
          
          # 중앙화된 매도 조건 판단 호출
          eval_mode = t_data.get('strategy_mode', 'QUANTUM')
          # [개선] JSON 설정값과 최적화 파라미터를 병합하여 매도 로직에 전달
          from dataclasses import asdict
          combined_conf = dict(QUANTUM_STRAT if eval_mode == "QUANTUM" else CLASSIC_STRAT)
          combined_conf.update(asdict(OPTIMIZED_PARAMS))
          
          is_sell, is_partial, ratio, reason, urgency, step = evaluate_sell_conditions(
              ticker, t_data, avg_p, real_price, p_rate, now_ts, 
              current_live_score, ma_live_score, curr_ind, combined_conf
          )
          
          if is_sell or is_partial:
              sell_qty = (coin.get('balance', 0) + coin.get('locked', 0)) * ratio
              if sell_qty * real_price >= 5000:
                  logging.info(f"🚨 [{ticker}] 매도 실행: {reason} (비율: {ratio*100}%, 긴급도: {urgency})")
                  res = await execute_upbit_api(upbit.sell_market_order, ticker, sell_qty)
                  
                  if res:
                    invested_krw = avg_p * sell_qty * 1.0005
                    earned_krw = real_price * sell_qty * 0.9995
                    p_krw = earned_krw - invested_krw
                    
                    status = "PARTIAL_SUCCESS" if is_partial else "COMPLETED"
                    
                    # background_sell_report 내부에서 record_trade_db를 호출하므로 여기서 직접 호출하지 않음
                    analyze_payload = {
                        'pass_score': t_data.get('pass_score', 0),
                        'strategy_mode': eval_mode,
                        'original_buy_reason': t_data.get('buy_reason', ''),
                        'original_exit_plan': t_data.get('exit_plan', {}),
                        'buy_ind': t_data.get('buy_ind', {}),
                        'sell_ind': curr_ind,
                        'actual_sell_reason': reason
                    }
                    asyncio.create_task(background_sell_report(ticker, real_price, sell_qty, p_krw, p_rate, reason, analyze_payload))
                    
                    if is_partial:
                        t_data['qty'] = t_data.get('qty', sell_qty) - sell_qty
                        t_data['scale_out_step'] = step
                    else:
                        if ticker in trade_data: del trade_data[ticker]
                        last_sell_time[ticker] = now_ts
                    
                    TRADE_DATA_DIRTY = True
        
        #  [Step 4 심: 스 스 체크 (Watchdog)]
        # 메인 루프 소켓이 모종 유 멈추 레그램 로 즉시 비상 림 보냅 다.
        last_main_loop_time = now_ts #  메인 루프가 상 으 고 음 치 에 보고 ( 장 박동)
    except Exception:
      logging.error(f"❗ 통합 메인 루프 예외 발생: {traceback.format_exc()}")
      await asyncio.sleep(5)
# --- [  보수  동 고도 션] ---
def apply_ema_update_internal():
  """
    최적화 결과(opt_results.json)를 읽어와 기존 설정에 EMA(지수 이동 평균) 방식으로 반영합니다.
    이 작업은 봇의 전략 표류(Strategy Drift)를 막고 점진적 진화를 유도합니다.
  """
  OPT_RESULTS_PATH = os.path.join(BASE_PATH, "optimization_results", "opt_results.json")
  HISTORY_DIR = os.path.join(BASE_PATH, "config_history")
  os.makedirs(HISTORY_DIR, exist_ok=True)
  if not os.path.exists(OPT_RESULTS_PATH):
        logging.info("유지보수: 최적화 결과 파일(opt_results.json)이 없습니다. 업데이트를 건너뜁니다.")
        return False, "최적화 결과 파일 없음"
  try:
    with open(OPT_RESULTS_PATH, "r", encoding="utf-8") as f:
      opt_data = json.load(f)
    best_params = opt_data.get("best_params")
    if not best_params:
            return False, "best_params 데이터 누락"
    updated_configs = []
    for config_name in ["config_quantum.json", "config_classic.json"]:
      config_path = os.path.join(BASE_PATH, config_name)
      if not os.path.exists(config_path): continue
      with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
      # 백업 성
      ts = datetime.now().strftime("%Y%m%d_%H%M%S")
      bak_path = os.path.join(HISTORY_DIR, f"{config_name}.{ts}.bak")
      shutil.copy2(config_path, bak_path)
      # EMA 용 (0.4 가중치)
      alpha = 0.4
      updated_count = 0
      #  1. 메인 략 라미터 데 트
      strat = config.get("strategy", {})
      for key, new_val in best_params.items():
        if key in strat and isinstance(new_val, (int, float)):
          old_val = strat[key]
          smoothed_val = (new_val * alpha) + (old_val * (1 - alpha))
          # 수 4 리까 반올 
          strat[key] = round(smoothed_val, 4)
          updated_count += 1
      #  2. 어 라미터 (major_params, mid_vol_params  데 트
      for tier_key in ["major_params", "mid_vol_params", "high_vol_params"]:
        tier_params = strat.get(tier_key, {})
        for key, new_val in best_params.items():
          if key in tier_params and isinstance(new_val, (int, float)):
            old_val = tier_params[key]
            smoothed_val = (new_val * alpha) + (old_val * (1 - alpha))
            tier_params[key] = round(smoothed_val, 4)
            updated_count += 1
      # 일  
      with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
      updated_configs.append(f"{config_name}({updated_count}개)")
    return True, f"업데이트 완료: {', '.join(updated_configs)}"
  except Exception as e:
    logging.error(f"EMA 업데이트 중 오류: {e}")
    return False, str(e)
# --- [OOS 검 진  동  줄러] ---
class BacktestEngine:
  """OOS 검증을 위한 경량 백테스트 엔진"""
  def __init__(self, initial_capital=10000000, commission=0.0005):
    self.capital = initial_capital
    self.cash = initial_capital
    self.commission = commission
    self.positions = {}
    self.trades = []
    self.all_scores = {}
  def run_ticker_oos(self, ticker, df, fgi_val=50):
    if df is None or len(df) < 100: return []
    cache_data = []
    for i in range(100, len(df)):
      cache_data.append((i, df.iloc[i-1], df.iloc[i]))
    for _, prev_s, curr_s in cache_data:
      ts = curr_s.name.timestamp() if hasattr(curr_s.name, 'timestamp') else 0
      prev_i, curr_i = prev_s.to_dict(), curr_s.to_dict()
      price = safe_float(curr_i.get('close'))
      # 수 계산 (   수 용)
      # evaluate_coin_fundamental_sync  비동기이므 출 방식주의 ( 기 는 기 퍼 요 음)
      #   백그 운 스  서 asyncio.run 는 직접 await 가 하 록 계
      # OOS 서 순   해 _run_sub_eval_sync 직접 출 고려
      pass
  async def run_simulation(self, ticker, df, eval_mode="QUANTUM"):
    """OOS용 단순화 시뮬레이션 (비동기 처리)"""
    if df is None or len(df) < 100: return 0.0
    initial_price = safe_float(df['close'].iloc[100])
    final_price = safe_float(df['close'].iloc[-1])
    bh_return = (final_price / initial_price - 1) * 100
    # 제 략 수 기반  이 
    cash = 2000000 # 종목 200만원 가 당
    qty = 0
    in_pos = False
    total_pnl = 0
    # 가 mtf_data
    fake_mtf = {"1h_trend": 1, "4h_macd": 1} 
    for i in range(100, len(df)):
      prev_i = df.iloc[i-1].to_dict()
      curr_i = df.iloc[i].to_dict()
      price = safe_float(curr_i.get('close'))
      score, fatal, thr, _ = evaluate_coin_fundamental_sync(ticker, prev_i, curr_i, "HYBRID", 50, "상승", force_eval_mode=eval_mode)
      if not in_pos and score >= thr and not fatal:
        qty = (cash * 0.999) / price
        cash -= (qty * price * 1.0005)
        in_pos = True
      elif in_pos:
        # 간단 절/ 절 (3% 절, 2% 절)
        avg_p = (2000000 - cash) / qty
        p_rate = (price / avg_p - 1) * 100
        if p_rate >= 3.5 or p_rate <= -2.5 or score < 60:
          cash += (qty * price * 0.9995)
          in_pos = False
          qty = 0
    final_val = cash + (qty * final_price if in_pos else 0)
    strat_return = (final_val / 2000000 - 1) * 100
    return strat_return, bh_return
async def run_oos_validation_internal():
  """최근 14일 데이터를 기반으로 현재 전략의 유효성을 검증합니다."""
  TEST_TICKERS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
  DAYS = 14
  count = DAYS * 24 * 4
  results = []
  engine = BacktestEngine()
  for ticker in TEST_TICKERS:
    try:
      df = await execute_upbit_api(pyupbit.get_ohlcv, ticker, interval="minute15", count=count)
      if df is None or df.empty: continue
      # 요 지 계산
      import pandas_ta as ta
      df.ta.ema(length=20, append=True)
      df.ta.ema(length=60, append=True)
      df.ta.rsi(length=14, append=True)
      df.ta.atr(length=14, append=True)
      df.ta.macd(append=True)
      df.ta.bbands(append=True)
      s_ret, b_ret = await engine.run_simulation(ticker, df)
      results.append({"t": ticker, "strat": s_ret, "bh": b_ret})
    except: continue
  if not results: return "검증 데이터 부족"
  avg_strat = sum(r['strat'] for r in results) / len(results)
  avg_bh = sum(r['bh'] for r in results) / len(results)
  status = "PASS" if avg_strat > avg_bh else "FAIL"
  report = f"📊 [OOS 검증 결과: {status}]\n- 엔진 평균: {avg_strat:.2f}%\n- 시장 평균: {avg_bh:.2f}%"
  return report
async def maintenance_background_task():
  """매일 오전 9시 10분에 실행되는 자동 유지보수 루프"""
  logging.info("유지보수 스케줄러 가동 시작 (주기: 24시간)")
  while True:
    try:
      now = datetime.now()
      # 음 안전 장치9 10 계산
      target = now.replace(hour=9, minute=10, second=0, microsecond=0)
      if now >= target:
        target += timedelta(days=1)
      wait_sec = (target - now).total_seconds()
      logging.info(f"다음 유지보수 예정: {target} (약 {wait_sec/3600:.1f}시간 후)")
      await asyncio.sleep(wait_sec)
      # 1. EMA 데 트 행
      success, msg = apply_ema_update_internal()
      await send_msg(f"🔄 <b>[자동 파라미터 업데이트]</b>\n{msg}")
      # 2. OOS 검 행
      if success:
        oos_report = await run_oos_validation_internal()
        await send_msg(oos_report)
    except Exception as e:
      logging.error(f"❌ 대시보드 서버 가동 실패: {e}")
      await asyncio.sleep(600)
if __name__ == "__main__":
  # --- [ 정] 메인 루프 작  보수 스 록 ---
  async def main_with_maintenance():
    # 기존 캔 스 들 께  보수 스 행
    maintenance_task = asyncio.create_task(maintenance_background_task())
    background_tasks.add(maintenance_task)
    maintenance_task.add_done_callback(background_tasks.discard)
    await main()
  try:
    asyncio.run(main_with_maintenance())
  except KeyboardInterrupt:
    logging.info("\n🛑 봇이 종료되었습니다.")
  except Exception:
    logging.error(f"\n❌ 실행 중 치명적 오류:\n{traceback.format_exc()}")
  finally:
    sys.stdout = original_stdout
    sys.stderr = original_stderr
    print(f"로그 파일 저장됨: {log_filepath}")
def prepare_bulk_indicators(full_df, btc_df, strategy_config):
  """모든 캔들에 대해 지표를 중앙화된 로직(_calculate_ta_indicators_sync)으로 한 번에 계산합니다."""
  df = full_df.copy()
  # 중앙화된 공통 지표 엔진 호출 (Live와 100% 동일 로직 보장)
  df = _calculate_ta_indicators_sync(df, btc_df, strategy_config)
  
  # 데이터 고정 (NaN 처리)
  df = df.ffill().fillna(0)
  # 2. 리스트 형태 변환 후 반환
  bulk_data = []
  # 지 계산 요 최소 도 100) 후부 작
  for i in range(100, len(df)):
    curr_i = df.iloc[i]
    prev_i = df.iloc[i-1]
    bulk_data.append((df.index[i], prev_i, curr_i))
  return bulk_data