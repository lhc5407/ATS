import pyupbit
import pandas as pd
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
import json
import os
import re
import sys
import traceback
import requests
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
import webbrowser
from typing import Any, Optional, Tuple, Dict, List

# 🟢 [대시보드 통합] FastAPI 엔진 추가설정
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

def get_coin_tier(ticker: str, curr_data: dict = None) -> str:
    """코인의 변동성 지수를 기반으로 티어(Major/Mid/Small) 명칭을 반환합니다."""
    try:
        if not isinstance(curr_data, dict): return "Major"
        close_val = safe_float(curr_data.get('close'))
        atr_val = safe_float(curr_data.get('ATR'))
        if close_val <= 0 or atr_val <= 0: return "Major"
        vol_idx = (atr_val / close_val) * 100
        if vol_idx > 3.5: return "Small (High Vol)"
        elif vol_idx > 1.5: return "Mid"
        else: return "Major"
    except: return "Major"

def get_coin_tier_params(ticker: str, curr_data: dict, eval_mode: str = "QUANTUM") -> dict:
    try:
        tier_name = get_coin_tier(ticker, curr_data)
        if tier_name == "Small (High Vol)": return get_dynamic_strat_value('high_vol_params', mode=eval_mode, default={})
        elif tier_name == "Mid": return get_dynamic_strat_value('mid_vol_params', mode=eval_mode, default={})
        else: return get_dynamic_strat_value('major_params', mode=eval_mode, default={})
    except Exception as e:
        logging.error(f"티어 분류 오류 ({ticker}): {e}")
        return get_dynamic_strat_value('major_params', mode=eval_mode, default={})

# --- [0.1 DB 유틸리티] ---
async def save_trade_status_db(trade_data_dict):
    """현재 거래 중인 종목들의 상태를 DB에 저장합니다 (JSON 직렬화 및 정화 포함)."""
    try:
        async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
            await db.execute("DELETE FROM trade_status") # 기존 상태 초기화 (UPSERT 대용)
            for ticker, data in trade_data_dict.items():
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
            await db.commit()
    except Exception as e:
        logging.error(f"DB 상태 저장 오류: {e}")

async def load_trade_status_db():
    """DB에서 이전 거래 상태를 복구합니다."""
    trade_data_dict = {}
    try:
        if not os.path.exists(DB_FILE): return {}
        async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
            async with db.execute("SELECT ticker, data_json FROM trade_status") as cursor:
                async for row in cursor:
                    try: trade_data_dict[row[0]] = json.loads(row[1])
                    except: pass
    except Exception as e:
        logging.error(f"DB 상태 로드 오류: {e}")
    return trade_data_dict

async def record_trade_db(ticker, side, price, amount, profit_krw=0.0, reason="", status="UNKNOWN", rating=0, improvement="", pass_score=0):
    """개별 거래 기록을 히스토리 DB에 영구 저장합니다."""
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
            await db.execute("""INSERT INTO trade_history 
                (timestamp, ticker, side, price, amount, profit_krw, reason, status, rating, improvement, pass_score) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
                (timestamp, ticker, side, price, amount, profit_krw, reason, status, rating, improvement, pass_score))
            await db.commit()
    except Exception as e:
        logging.error(f"DB 거래 기록 오류: {e}")

# 🟢 [최적화] TA 스레드 풀 고정 (OS 레벨 스레드 경합 방지 + 예측 가능한 성능)
_TA_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="TA_Worker")

# 🟢 로그 파일 설정
if getattr(sys, 'frozen', False): base_path = os.path.dirname(sys.executable)
else: base_path = os.path.dirname(os.path.abspath(__file__))

log_dir = os.path.join(base_path, "log")
os.makedirs(log_dir, exist_ok=True)

log_filename = datetime.now().strftime("ats_hybrid_log_%Y%m%d_%H%M%S.log")
log_filepath = os.path.join(log_dir, log_filename)

# 🟢 PyInstaller 외 환경에서는 stderr를 안전하게 가져오기
_safe_stderr = getattr(sys, '__stderr__', None) or getattr(sys, 'stderr', None)

_log_handlers: list = [
    RotatingFileHandler(log_filepath, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'),
]
if _safe_stderr is not None:
    _log_handlers.append(logging.StreamHandler(_safe_stderr))

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=_log_handlers)

# 🟢 콘솔이 있는 경우 WARNING 이상만 표시 (파일에는 INFO 전체 기록)
if len(logging.getLogger().handlers) > 1:
    logging.getLogger().handlers[1].setLevel(logging.WARNING)

# 🔇 외부 라이브러리의 과도한 HTTP/API 로그 파일로만 기록
for _noisy in [
    "httpx",         # Telegram Bot HTTP 요청
    "httpcore",
    "hpack",
    "h11",
    "google",        # Gemini API
    "google.ai",
    "google.generativeai",
    "uvicorn",       # 대시보드 접속 로그
    "uvicorn.access",
    "uvicorn.error",
    "fastapi",
]:
    logging.getLogger(_noisy).setLevel(logging.WARNING)
    logging.getLogger(_noisy).propagate = True

def cleanup_old_logs(days=3):
    try:
        now = time.time()
        # ats_hybrid_log_*.log 패턴의 파일들 검색
        for f in glob.glob(os.path.join(log_dir, "ats_hybrid_log_*.log")):
            if os.path.isfile(f):
                if os.stat(f).st_mtime < now - (days * 86400):
                    os.remove(f)
                    print(f"🧹 오래된 로그 삭제됨: {os.path.basename(f)}")
    except Exception as e:
        print(f"⚠️ 로그 정리 중 오류: {e}")

# 시작 시 로그 정리 실행
cleanup_old_logs(days=3)

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

logging.info("ATS 통합 엔진 시작 (Classic + Quantum)")

# --- [0. 시스템 절대 규칙서 및 전역 변수] ---
AI_SYSTEM_INSTRUCTION_CLASSIC = """
You are the 'Chief Strategy Officer' of an elite quantitative trading system called 'ATS-Classic'.
[IDENTITY]: You are a 'Mean Reversion & Deep Dip Sniper' (낙폭 과대 역추세 매매 전문가). You specialize in catching extreme oversold conditions and extreme gaps from the mean.

[ABSOLUTE RULES FOR AI]
1. OUTPUT FORMAT (CRITICAL): You MUST output ONLY valid JSON. 
   - DO NOT wrap the JSON in markdown code blocks.
   - STRICT SCHEMA RULE: Use the exact top-level keys provided.

2. LANGUAGE RULE: All string values MUST be written in Korean.

3. TRADING PHILOSOPHY (CLASSIC):
   - Buy the Panic: Look for RSI oversold (<35), Bollinger Band lower bounds, and large negative distance from SMA20 (dist_sma20).
   - Mean Reversion: Your goal is to catch the 'rubber band' snap-back. The larger the 'dist_sma20' (negative), the stronger the potential bounce.
   - Ignore Macro Downtrend: Downward trends are your hunting ground.
   - Risk/Reward: Target fast +0.4% to +1.2% scalp profits.

4. HARDCODED SYSTEM OVERRIDES (CRITICAL CONTEXT):
   - Fatal Flaw Locks: Python blocks trades if RSI > 55, Volume < 1.3x, or CVD is declining.
   - V-Shape Exception: Python allows entries up to RSI 60 IF Volume > 1.7x AND CVD (Net Buying) is improving. This is a high-conviction reversal.
   - Nano/Micro Timeout: Python auto-ejects if a bounce doesn't happen within 3-15 mins. Rate these as 'Excellent Risk Management' in SELL_REASON.
   - R:R Lock: Python compresses Stop Loss to 0.7x of Target (e.g. Target 1.0% -> SL -0.7%).

5. MODE-SPECIFIC OUTPUT SCHEMAS:
   - [BUY] or [POST_BUY_REPORT]: {"risk_agent_opinion": "string", "trend_agent_opinion": "string", "reason": "string", "score": int, "decision": "BUY"|"SKIP", "exit_plan": {...}}
"""

AI_SYSTEM_INSTRUCTION_QUANTUM = """
You are the 'Chief Strategy Officer' of an elite quantitative trading system called 'ATS-Quantum'.
[IDENTITY]: You are a 'Trend Follower & Pullback Sniper' (추세 추종 및 눌림목 매매 전문가). You specialize in catching trends during temporary market dips.

[ABSOLUTE RULES FOR AI]
1. OUTPUT FORMAT (CRITICAL): You MUST output ONLY valid JSON.
2. LANGUAGE RULE: All string values MUST be written in Korean.

3. TRADING PHILOSOPHY (QUANTUM):
   - Buy the Pullback: Actively look for price support near SMA20 (is_pullback_zone), cooled down RSI (50-65), and volume stability.
   - Ride the Wave: Focus on "Let Winners Run". Use trailing stops to maximize gains.
   - Macro Alignment: Only buy if the 1H trend is Bullish.
   - Breakout as Secondary: Only approve a breakout (price > BB Upper) if Volume is exceptionally high (>2.0x SMA).

4. HARDCODED SYSTEM OVERRIDES (CRITICAL CONTEXT):
   - Fatal Flaw Locks: Python blocks trades if 1H trend is DOWN or CVD is NEGATIVE.
   - Breakout Guard: Requires RSI < 70 and momentum support.
   - Volatility Shield: Blocks buys if BTC is dropping sharply.
   - Pullback Exception: Python allows entries even if 15m Supertrend is RED, provided the 1H trend is BULLISH and price is holding SMA20 support (is_pullback_zone).
   - Dynamic Trailing Stop Lock: Python actively tightens trailing stops to lock in gains at +0.6%, +1.0%, etc.
   - R:R Lock: Python enforces SL <= 0.7x of Target to ensure favorable Risk/Reward.

5. MODE-SPECIFIC OUTPUT SCHEMAS:
   - [BUY] or [POST_BUY_REPORT]: {"risk_agent_opinion": "string", "trend_agent_opinion": "string", "reason": "string", "score": int, "decision": "BUY"|"SKIP", "exit_plan": {...}}
"""

AI_SYSTEM_INSTRUCTION_OPTIMIZE = """
You are the 'Lead Quantitative Strategist' of ATS (Antigravity Trading System).
Your role is to analyze recent trade performance and market regimes to optimize the core trading parameters.

[IDENTITY]: You are a mathematical optimization engine. You do not make trading decisions. You provide strategy configuration overrides.

[ABSOLUTE RULES]:
1. OUTPUT FORMAT: You MUST output ONLY valid JSON.
2. SCHEMA: You MUST use the following schema:
   {
     "strategy": {
       "trend_active_logic": ["indicator1", "indicator2", ...],
       "range_active_logic": ["indicator1", "indicator2", ...],
       "indicator_weights": { ... },
       "scoring_modifiers": { ... },
       "major_params": { "target_atr_multiplier": float, "stop_loss": float, "timeout_candles": int, ... },
       "mid_vol_params": { ... },
       "high_vol_params": { ... },
       "fgi_v_curve_bottom": float,
       "fgi_v_curve_min": float,
       "fgi_v_curve_max": float,
       ... (other allowed parameters)
     },
     "reason": "Detailed explanation of changes in Korean"
   }
3. NO TRADING DECISIONS: Do NOT output 'decision', 'score', 'risk_agent_opinion', or 'exit_plan' in the root level. These are for trade analysis only.
4. LANGUAGE: The 'reason' field MUST be in Korean.
"""

VALID_INDICATORS = [
    "supertrend", "vwap", "volume", "rsi", "bollinger", "macd", "stoch_rsi", 
    "bollinger_bandwidth", "atr_trend", "ssl_channel", 
    "stochastics", "obv", "keltner_channel", "ichimoku",
    "sma_crossover", "bollinger_breakout", "rs","z_score"
]

def get_strategy_score(name: str, prev: dict, curr: dict, price: float, mode: str = "QUANTUM") -> float:
    try:
        if not isinstance(curr, dict) or not isinstance(prev, dict): return 0.0
        if name not in VALID_INDICATORS: return 0.0
        
        def calc_dist_score(val, baseline, weight=10.0):
            if baseline <= 0: return 0.0
            dist_pct = ((val - baseline) / baseline) * 100
            return min(100.0, max(0.0, 50.0 + (dist_pct * weight)))

        # --- [CLASSIC MODE: 낙폭 과대] ---
        if mode == "CLASSIC":
            if name == "rsi": return min(100.0, max(0.0, (35.0 - safe_float(curr.get('rsi'), 50.0)) * 2.5 + 50))
            if name == "bollinger": 
                bb_range = curr.get('bb_u', 1) - curr.get('bb_l', 0)
                if bb_range <= 0: return 50.0
                return min(100.0, max(0.0, 100.0 - (((price - curr.get('bb_l', 0)) / bb_range) * 110)))
            if name == "z_score": 
                z = safe_float(curr.get('z_score'), 0.0)
                # CLASSIC: Z-score가 낮을수록(과매도) 점수 대폭 상승
                return min(100.0, max(0.0, 50.0 + (z * -30.0)))
            if name == "macd":
                macd_diff = safe_float(curr.get('macd_h_diff'), 0.0)
                macd_diff_sma = safe_float(curr.get('macd_h_diff_sma'), 0.0001)
                if macd_diff > 0:
                    if macd_diff >= (macd_diff_sma * 1.5): return 100.0
                    return min(99.0, (macd_diff / max(macd_diff_sma * 1.5, 0.0001)) * 100)
                return 0.0
            if name == "volume":
                vol_sma = safe_float(curr.get('vol_sma'), 0.0001)
                return min(100.0, (safe_float(curr.get('volume')) / (vol_sma * 1.5)) * 100)

        # --- [QUANTUM MODE: 추세 추종] ---
        if mode == "QUANTUM":
            if name == "bollinger_breakout":
                if price < curr.get('bb_u', 0): return 0.0
                bw_expansion = max(0, (curr.get('bb_bw', 0) - prev.get('bb_bw', 0)) / max(prev.get('bb_bw', 0), 0.0001))
                return min(100.0, 70.0 + (bw_expansion * 500))
            if name == "rsi":
                curr_rsi = safe_float(curr.get('rsi'), 50.0)
                # QUANTUM 눌림목: RSI가 50~65 사이로 '식었을 때' 가장 높은 점수
                if 50 <= curr_rsi <= 65: return 100.0
                if curr_rsi > 85: return 30.0 
                return max(0.0, curr_rsi - 10)
            if name == "macd":
                macd_h, macd_h_diff = safe_float(curr.get('macd_h'), 0.0), safe_float(curr.get('macd_h_diff'), 0.0)
                if macd_h > 0 and macd_h_diff > 0: return 100.0
                if macd_h > 0: return 70.0
                return 0.0
            if name == "z_score":
                z = safe_float(curr.get('z_score'), 0.0)
                # QUANTUM 눌림목: Z-score가 0.0 ~ 1.2 사이(평균 부근 지지)일 때 고점
                if 0.0 <= z <= 1.2: return 100.0
                if z > 2.5: return 40.0 # 과매수 구간 감점
                return max(0.0, 50.0 + (z * 20))
            if name == "bollinger":
                bb_range = curr.get('bb_u', 1) - curr.get('bb_l', 0)
                if bb_range <= 0: return 0.0
                return min(100.0, max(0.0, ((price - curr.get('bb_l', 0)) / bb_range) * 100))
            if name == "volume":
                vol_sma = safe_float(curr.get('vol_sma'), 0.0001)
                return min(100.0, (safe_float(curr.get('volume')) / max(vol_sma * 2.0, 0.0001)) * 100)

        # --- [공통 지표] ---
        if name == "vwap": return calc_dist_score(price, curr.get('vwap', price))
        if name == "ssl_channel": return calc_dist_score(price, curr.get('ssl_up', price))
        if name == "sma_crossover":
            p_above_20 = price > curr.get('sma_long', 0)
            ma_20_above_50 = curr.get('sma_long', 0) > curr.get('sma_50', 0)
            return 100.0 if p_above_20 and ma_20_above_50 else (60.0 if p_above_20 else 0.0)
        if name == "ichimoku": return calc_dist_score(price, max(curr.get('span_a', 0), curr.get('span_b', 0)))
        if name == "stoch_rsi": 
            diff = curr.get('st_rsi_k', 0) - curr.get('st_rsi_d', 0)
            base, mult = (60.0, 2) if mode == "QUANTUM" else (50.0, 3)
            return min(100.0, max(0.0, base + (diff * mult)))
        if name == "stochastics": 
            diff = curr.get('stoch_k', 0) - curr.get('stoch_d', 0)
            base, mult = (60.0, 2) if mode == "QUANTUM" else (50.0, 3)
            return min(100.0, max(0.0, base + (diff * mult)))
        if name == "bollinger_bandwidth" or name == "atr_trend":
            key = 'bb_bw' if name == "bollinger_bandwidth" else 'ATR'
            diff_pct = ((curr.get(key, 0) - prev.get(key, 0)) / max(prev.get(key, 0.0001), 0.0001)) * 100
            return min(100.0, max(0.0, 50.0 + diff_pct * 5))
        if name == "obv":
            diff_pct = ((curr.get('obv', 0) - prev.get('obv', 0)) / max(abs(prev.get('obv', 0.0001)), 0.0001)) * 100
            return min(100.0, max(0.0, 50.0 + diff_pct * 10))
        if name == "supertrend": return 100.0 if curr.get('ST_DIR', 1) == 1 else 0.0
        
        return 0.0
    except: return 0.0


def determine_regime_mode(fgi_str: str, btc_short: dict) -> str:
    try:
        fgi_val = int(re.search(r'\d+', str(fgi_str)).group()) if re.search(r'\d+', str(fgi_str)) else 50
    except: fgi_val = 50

    if fgi_val <= 35 or (btc_short.get('trend') == "단기 하락" and fgi_val <= 50):
        return "CLASSIC"
    if fgi_val >= 65 or (btc_short.get('trend') == "단기 상승" and fgi_val >= 50):
        return "QUANTUM"
    return "HYBRID"


def determine_eval_mode(current_regime_mode: str, curr: dict) -> str:
    if current_regime_mode == "CLASSIC":
        return "CLASSIC"
    if current_regime_mode == "QUANTUM":
        return "QUANTUM"
    return "QUANTUM" if safe_float(curr.get('adx')) > 25 else "CLASSIC"


def get_logic_list_for_mode(eval_mode: str, curr_data: dict) -> list:
    strat_config = get_strat_for_mode(eval_mode)
    adx_val = safe_float(curr_data.get('adx', 0))
    adx_threshold = safe_float(strat_config.get('major_params', {}).get('adx_strong_trend_threshold', 25.0))
    
    if adx_val > adx_threshold:
        return strat_config.get('trend_active_logic', [])
    else:
        return strat_config.get('range_active_logic', [])


def get_indicator_multipliers(eval_mode: str, fgi_val: float) -> dict:
    v_min = safe_float(get_dynamic_strat_value('fgi_v_curve_min', mode=eval_mode, default=0.5))
    v_max = safe_float(get_dynamic_strat_value('fgi_v_curve_max', mode=eval_mode, default=3.0))

    if eval_mode == "CLASSIC":
        v_bottom = safe_float(get_dynamic_strat_value('fgi_v_curve_bottom', mode=eval_mode, default=70.0))
        dynamic_fgi_mult = v_max - ((fgi_val / v_bottom) * (v_max - v_min)) if fgi_val <= v_bottom else v_min
        normalized_regime_val = max(0.0, min(1.0, (dynamic_fgi_mult - v_min) / max(v_max - v_min, 0.0001)))
        return {
            'rsi': 0.5 + (1.5 * normalized_regime_val),
            'bollinger': 1.0 + (0.5 * normalized_regime_val),
            'volume': 2.0 - (1.0 * normalized_regime_val)
        }

    dynamic_fgi_mult = v_min + (((fgi_val - 50) / 30) * (v_max - v_min)) if fgi_val >= 50 else v_min
    normalized_regime_val = max(0.0, min(1.0, (dynamic_fgi_mult - v_min) / max(v_max - v_min, 0.0001)))
    return {
        'rsi': 1.0 + (1.0 * normalized_regime_val),
        'bollinger_breakout': 1.5 + (1.5 * normalized_regime_val),
        'volume': 1.0 + (1.5 * normalized_regime_val)
    }


def evaluate_coin_fundamental(ticker, prev_i, curr_i, current_regime_mode, fgi_val, btc_short_trend, force_eval_mode=None, mtf_data=None):
    # force_eval_mode가 주어지면 시장 상황을 무시하고 그 모드로만 채점합니다.
    eval_mode = force_eval_mode if force_eval_mode else determine_eval_mode(current_regime_mode, current_regime_mode)
    logic_list = get_logic_list_for_mode(eval_mode, curr_i)
    indicator_mults = get_indicator_multipliers(eval_mode, fgi_val)
    weights = get_dynamic_strat_value('indicator_weights', mode=eval_mode, default={})
    
    earned_score, total_w = 0.0, 0.0
    curr_close = safe_float(curr_i.get('close'))
    curr_vol = safe_float(curr_i.get('volume'))
    
    # 🚨 [데이터 무결성 검증] 기본 시세 데이터 누락 시 즉각 하드락 사유 반환
    if curr_close <= 0 or curr_vol <= 0:
        return 0, "데이터오류", eval_mode
        
    # 모든 지표 플래그 초기화
    is_volume_spike, is_bullish_recovery, cvd_improving, v_shape_special = False, False, False, False
    is_pullback_zone = False
    
    for name in logic_list:
        w = safe_float(weights.get(name, 1.0), 1.0)
        m = safe_float(indicator_mults.get(name, 1.0), 1.0)
        s = safe_float(get_strategy_score(name, prev_i, curr_i, curr_close, mode=eval_mode), 0.0)
        earned_score += (s * m * w)
        total_w += (m * w)
    
    score = int(earned_score / total_w) if total_w > 0 else 0

    def calc_gradient_val(val, target, window, mode='DECREASE'):
        diff = abs(val - target)
        if mode == 'DECREASE': 
            if val <= target: return 1.0
            if val >= target + window: return 0.0
            return 1.0 - (diff / window)
        else:
            if val >= target: return 1.0
            if val <= target - window: return 0.0
            return 1.0 - (diff / window)

    current_score_mods = get_dynamic_strat_value('scoring_modifiers', mode=eval_mode, default={})
    if eval_mode == "QUANTUM":
        bb_u = safe_float(curr_i.get('bb_u'))
        if curr_close >= bb_u:
            score += current_score_mods.get('bonus_volume_explosion', 30)
        if btc_short_trend == "단기 하락": score += current_score_mods.get('penalty_btc_weakness', -15)
        kc_u = safe_float(curr_i.get('kc_u', 99999999))
        if curr_close >= kc_u: score += current_score_mods.get('bonus_all_time_high', 15)
        rsi_val = safe_float(curr_i.get('rsi', 50))
        if rsi_val < 55:
            penalty = current_score_mods.get('penalty_weak_momentum', -15)
            score += (penalty * calc_gradient_val(rsi_val, 55, 10, 'DECREASE'))
        sma_long_val = safe_float(curr_i.get('sma_long', 0))
        is_pullback_zone = (curr_close >= sma_long_val * 0.99) and (curr_close <= sma_long_val * 1.04)
        if is_pullback_zone:
            score += current_score_mods.get('bonus_pullback_support', 30)
            
    else: # CLASSIC
        rsi_val = safe_float(curr_i.get('rsi', 50))
        if fgi_val <= 35:
            golden_bonus = current_score_mods.get('bonus_golden_combo', 35)
            score += (golden_bonus * calc_gradient_val(rsi_val, 35, 10, 'DECREASE'))
        if btc_short_trend == "단기 하락": score += current_score_mods.get('bonus_btc_panic_dip', 10)
        if curr_i.get('ST_DIR', 1) == -1:
            st_bonus = current_score_mods.get('bonus_st_oversold_bounce', 10)
            score += (st_bonus * calc_gradient_val(rsi_val, 35, 10, 'DECREASE'))
        sma20 = safe_float(curr_i.get('sma_long', curr_close))
        gap_pct = ((curr_close - sma20) / sma20) * 100 if sma20 > 0 else 0
        if gap_pct < -5.0:
            score += min(25, abs(gap_pct) * 3)
        if safe_float(curr_i.get('rs', 0)) < 0: score += current_score_mods.get('penalty_rs_weakness', -10)
        if mtf_data and safe_float(mtf_data.get('4h_macd', 0)) < 0:
            mtf_bonus = current_score_mods.get('bonus_mtf_panic_dip', 15)
            score += (mtf_bonus * calc_gradient_val(rsi_val, 35, 10, 'DECREASE'))
        dist_sma = safe_float(curr_i.get('dist_sma20', 0))
        if dist_sma < -5.0:
            score += min(30, abs(dist_sma) * 3)

    # 🟢 하드락(Fatal Flaw) 판별부
    fatal_reason = ""
    if mtf_data is None: mtf_data = {"4h_macd": 0, "1h_trend": 0}
    
    if eval_mode == "QUANTUM":
        sma_long_val = safe_float(curr_i.get('sma_long', 0))
        is_pullback_zone = (curr_close >= sma_long_val * 0.985) and (curr_close <= sma_long_val * 1.03)
        mtf_bullish = mtf_data.get('1h_trend', 0) == 1
        if curr_i.get('ST_DIR', 1) == -1 or curr_close < sma_long_val: 
            if not (mtf_bullish and is_pullback_zone):
                fatal_reason = "단기상승세이탈"
        if not fatal_reason and safe_float(curr_i.get('cvd', 0)) < 0:
            score -= 25 # 🟢 [유연화] 하드락에서 감점으로 변경
        if not fatal_reason and safe_float(mtf_data.get("4h_macd", 0)) < 0:
            score -= 20 # 🟢 [유연화] 하드락에서 감점으로 변경
            
    else: # CLASSIC
        if safe_float(curr_i.get('rsi')) > 60: fatal_reason = "RSI과열" # 🟢 55 -> 60 상향
        curr_vol = safe_float(curr_i.get('volume'), 0)
        curr_vol_sma = safe_float(curr_i.get('vol_sma'), 1)
        prev_vol = safe_float(prev_i.get('volume'), 0)
        is_volume_spike = (curr_vol > curr_vol_sma * 1.3) or (prev_vol > safe_float(prev_i.get('vol_sma'), 1) * 1.3)
        is_bullish_recovery = curr_close > curr_i.get('open', curr_close)
        cvd_improving = safe_float(curr_i.get('cvd', 0)) > safe_float(prev_i.get('cvd', 0))
        ob_imbalance = safe_float(curr_i.get('ob_imbalance', 0))
        is_ob_bad = ob_imbalance < -75.0

        if not fatal_reason:
            if not (is_volume_spike and is_bullish_recovery): fatal_reason = "반등신호대기 (거래량/양봉)"
            elif not cvd_improving: fatal_reason = "실매수세부족 (CVD)"
            elif is_ob_bad: fatal_reason = "매도벽압박 (OB)"
            
        if cvd_improving and (curr_vol > curr_vol_sma * 1.7 or prev_vol > safe_float(prev_i.get('vol_sma'), 1) * 1.7):
            if safe_float(curr_i.get('rsi')) <= 60:
                fatal_reason = "" # V자 반등 특례
                v_shape_special = True

    # 데이터 주입 (보고서용)
    curr_i['is_volume_spike'] = is_volume_spike
    curr_i['is_bullish_recovery'] = is_bullish_recovery
    curr_i['cvd_improving'] = cvd_improving
    curr_i['v_shape_special'] = v_shape_special
    if eval_mode == "QUANTUM":
        curr_i['is_pullback_zone'] = is_pullback_zone
        curr_i['is_rsi_cooling'] = (50 <= safe_float(curr_i.get('rsi')) <= 65)
    
    score = round(max(0.0, min(100.0, score)), 1)
    return score, fatal_reason, eval_mode

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


def get_exit_plan_preview(ticker: str, curr_data: dict, eval_mode: str = "QUANTUM") -> str:
    """기대 수익과 동적 손절선을 계산하여 AI 분석용 컨텍스트 문자열을 생성합니다."""
    try:
        tier_params = get_coin_tier_params(ticker, curr_data, eval_mode=eval_mode)
        target_mult = tier_params.get('target_atr_multiplier', 4.5)
        sl_cap = tier_params.get('stop_loss', -3.0)
        
        close_p = safe_float(curr_data.get('close', 1))
        atr_val = safe_float(curr_data.get('ATR', 0))
        atr_pct = (atr_val / close_p) * 100 if close_p > 0 else 0
        
        expected_target = round(atr_pct * target_mult, 2)
        sl_atr_mult = tier_params.get('atr_mult', 2.0)
        dynamic_sl = -(atr_pct * sl_atr_mult)
        
        # 실제 process_buy_order에 적용된 압착 로직과 동일하게 계산
        final_sl = max(dynamic_sl, sl_cap)
        if abs(final_sl) > (expected_target * 0.7):
            final_sl = -(expected_target * 0.7)
            
        final_sl = round(final_sl, 2)
        rr_ratio = round(expected_target / abs(final_sl), 2) if final_sl != 0 else 1.0
        
        return f"기대수익 +{expected_target}% / 예상손절 {final_sl}% (손익비 {rr_ratio}:1)"
    except Exception as e:
        logging.error(f"Exit Plan Preview 생성 오류 ({ticker}): {e}")
        return "데이터 부족으로 산출 불가"

def load_config():
    if getattr(sys, 'frozen', False): base_path = os.path.dirname(sys.executable)
    else: base_path = os.path.dirname(os.path.abspath(__file__))
    quantum_path = os.path.join(base_path, "config_quantum.json")
    classic_path = os.path.join(base_path, "config_classic.json")

    if not os.path.exists(quantum_path): print(f"❌ Quantum 설정 파일 없음 ({quantum_path})"); sys.exit()
    if not os.path.exists(classic_path): print(f"❌ Classic 설정 파일 없음 ({classic_path})"); sys.exit()

    with open(quantum_path, 'r', encoding='utf-8') as f: quantum_conf = json.load(f)
    with open(classic_path, 'r', encoding='utf-8') as f: classic_conf = json.load(f)
    return quantum_conf, classic_conf, quantum_path, classic_path


def get_strat_for_mode(mode="QUANTUM"):
    if isinstance(mode, str) and mode.upper() == "CLASSIC":
        return CLASSIC_STRAT
    return QUANTUM_STRAT


def get_dynamic_strat_value(key, mode=None, default=None):
    if isinstance(mode, str) and mode.upper() in ("CLASSIC", "QUANTUM"):
        config = get_strat_for_mode(mode)
        if key in config:
            return config.get(key, default)
    return STRAT.get(key, default)


async def save_config_async(config_data, path):
    def _save():
        import time
        import shutil
        
        # 1. 백업 파일 생성 (안전장치)
        bak_path = path + ".bak"
        try:
            if os.path.exists(path):
                shutil.copy2(path, bak_path)
        except:
            pass # 백업 실패는 무시하고 진행
            
        # 2. 메인 파일 파일 쓰기 시도 (최대 5회 재시도)
        success = False
        last_err = None
        
        for i in range(5):
            try:
                # 윈도우 잠금 해제를 위해 잠시 대기
                if i > 0: time.sleep(0.3)
                
                with open(path, 'w', encoding='utf-8') as f: 
                    json.dump(config_data, f, indent=4, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                success = True
                break
            except Exception as e:
                last_err = e
                # 잠금 오류일 확률이 높으므로 다시 루프 실행
                continue
        
        if not success:
            # 최종 실패 시 백업에서 복구 시도
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
# 🟢 [전역 제어 객체] 시스템 부하 및 스캔 충돌 방지
SCAN_LOCK = asyncio.Lock()
GLOBAL_API_SEMAPHORE = asyncio.Semaphore(15) # 🟢 동시 API 호출 제한 상향 (15 권장)

INDICATOR_CACHE = {} 
INDICATOR_CACHE_LOCK = asyncio.Lock()
INDICATOR_CACHE_SEC = 60 

OHLCV_CACHE = {} 
OHLCV_CACHE_LOCK = asyncio.Lock()
QUANTUM_STRAT = QUANTUM_CONF['strategy']
CLASSIC_STRAT = CLASSIC_CONF['strategy']
STRAT = dict(QUANTUM_STRAT)
STRAT['tickers'] = sorted(list(set(QUANTUM_STRAT.get('tickers', []) + CLASSIC_STRAT.get('tickers', []))))
STRAT['external_dashboard_url'] = "http://localhost:8080"  # 외부 접속용 대시보드 주소 (실제 포트 8080에 맞춤)

upbit = pyupbit.Upbit(API_CONF['access_key'], API_CONF['secret_key'])
bot = telegram.Bot(token=TG_CONF['token'])
client = genai.Client(api_key=API_CONF['gemini_api_key'], http_options=types.HttpOptions(api_version='v1beta'))
MODEL_ID = 'gemini-2.5-flash-lite'

GLOBAL_COOLDOWN, last_ai_call_time = 0.5, 0 
last_coin_ai_call, last_sell_time, last_buy_time = {}, {}, {}
trade_data = {}  # 🟢 [추가] 빈 방패를 먼저 세워 에러 원천 차단!
last_global_buy_time = 0  

# 🟢 [BTC 급등 비정규 스캔 트리거] 한번에 1%+ 이상 스파이크 시 즉시 알트 매수 기회 포선을 위한 상태 변수
BTC_SURGE_TRIGGERED = False      # 주 루프가 확인하는 트리거 플래그
BTC_PRICE_WINDOW = {}            # {timestamp: price} 슬라이딩 윈도우
BTC_SURGE_COOLDOWN_TS = 0        # 마지막 트리거 시각 (연속 트리거 방지)
BTC_SURGE_THRESHOLD = 1.5        # 트리거 기준 상승률 (%) - AI OPTIMIZE로 조정 가능
LATEST_TOP_PASS_SCORE = 0
BOT_START_TIME = time.time()  
last_deep_scan_ts = 0  # 🟢 딥스캔 전용 타이머 분리
last_auto_optimize_time = 0  
consecutive_empty_scans = 0 
REALTIME_PRICES = {}
REALTIME_PRICES_TS = {}
REALTIME_CVD = {} # 🟢 실시간 Taker CVD 저장소
LATEST_SCAN_RESULTS = {} # 🟢 모든 종목의 최신 스캐너 정보 (대시보드 노출용)
LATEST_SCAN_TS = 0
API_FATAL_ERRORS = 0 # 🟢 API 연속 실패 카운터

is_running = True
last_update_id = None
SYSTEM_STATUS = "🟢 정상 감시 중"

background_tasks = set()

INDICATOR_CACHE_LOCK = asyncio.Lock()
OHLCV_CACHE_LOCK = asyncio.Lock()

# 🟢 [FIX: API Rate Limit 방어용 MTF 캐싱 도입]
MTF_CACHE = {}
MTF_CACHE_SEC = 300

instance_lock = None  # 🟢 [Pylance 완벽 방어] 미선언 상태로 global 참조 시 발생하는 경고를 해결하기 위해 전역 초기화

TRADE_DATA_DIRTY = False  # 메모리 데이터가 변경되었는지 확인하는 플래그

# 🟢 [대시보드 전용 서버 세팅]
app = FastAPI(title="ATS Command Center", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 🟢 PyInstaller 환경에서는 빌트인된 _MEIPASS 임시 폴더에서 정적 파일을 찾습니다.
if getattr(sys, 'frozen', False):
    dashboard_dir = os.path.join(sys._MEIPASS, "dashboard")
else:
    dashboard_dir = os.path.join(base_path, "dashboard")

@app.get("/api/dashboard")
async def api_get_dashboard(timeframe: str = 'all'):
    wins, losses, total_profit = 0, 0, 0.0
    chart_data = []
    
    try:
        async with aiosqlite.connect(DB_FILE, timeout=5.0) as db:
            query = "SELECT timestamp, profit_krw FROM trade_history WHERE side='SELL' ORDER BY timestamp ASC"
            async with db.execute(query) as cursor:
                cumulative_profit = 0.0
                async for row in cursor:
                    ts_str = str(row[0])
                    profit = safe_float(row[1])
                    
                    total_profit += profit
                    cumulative_profit += profit
                    
                    if profit > 0: wins += 1
                    elif profit < 0: losses += 1
                    
                    chart_data.append({"time": ts_str, "profit": cumulative_profit})
                    
        # Apply timeframe filtering
        if timeframe in ['day', 'week'] and chart_data:
            now = datetime.now()
            cutoff = now - timedelta(days=1 if timeframe == 'day' else 7)
            
            # 필터링 라인: 기준 시간 이후의 데이터만 남깁니다.
            filtered_data = []
            for d in chart_data:
                try:
                    t_obj = datetime.strptime(d['time'], '%Y-%m-%d %H:%M:%S')
                    if t_obj >= cutoff:
                        filtered_data.append(d)
                except:
                    filtered_data.append(d) # 형식이 이상하면 그냥 유지
            
            chart_data = filtered_data
            
    except Exception as e:
        logging.error(f"대시보드 DB 쿼리 오류: {e}")
    
    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0

    active_trades = []
    for t_name, t_data in trade_data.items():
        entry = safe_float(t_data.get('high_p', 0))
        amount = safe_float(t_data.get('amount', 0))
        cur_p = safe_float(REALTIME_PRICES.get(t_name, entry))
        pnl = ((cur_p - entry) / entry) * 100 if entry > 0 else 0
        
        buy_amount_krw = entry * amount
        current_amount_krw = cur_p * amount
        
        active_trades.append({
            "ticker": t_name,
            "entry_price": entry,
            "current_price": cur_p,
            "amount": amount,
            "buy_amount": buy_amount_krw,
            "current_amount": current_amount_krw,
            "pnl_pct": pnl,
            "score": t_data.get('pass_score', 0),
            "mode": t_data.get('strategy_mode', 'UNKNOWN'),
            "reason": t_data.get('buy_reason', '데이터 없음')
        })

    btc_trend_str = "알 수 없음"
    try:
        btc_trend_str = "단기 상승" if "Quantum" in SYSTEM_STATUS else ("단기 하락" if "Classic" in SYSTEM_STATUS else "균형")
    except: pass

    return {
        "system_status": SYSTEM_STATUS,
        "btc_trend": btc_trend_str,
        "win_rate": win_rate,
        "total_profit": total_profit,
        "active_trades": active_trades,
        "chart_data": chart_data
    }

@app.get("/api/history")
async def api_get_history():
    history_data = []
    try:
        async with aiosqlite.connect(DB_FILE, timeout=5.0) as db:
            # 최근 100건의 매매 역사 (역순)
            query = "SELECT timestamp, ticker, side, price, profit_krw, reason, pass_score FROM trade_history ORDER BY id DESC LIMIT 100"
            async with db.execute(query) as cursor:
                async for row in cursor:
                    # reason 문자열 처리에 따라 None일 수 있으므로 보호
                    ai_reason = row[5] if row[5] else "System default closed."
                    history_data.append({
                        "time": str(row[0]),
                        "ticker": str(row[1]),
                        "side": str(row[2]),
                        "price": safe_float(row[3]),
                        "profit_krw": safe_float(row[4]),
                        "reason": ai_reason,
                        "score": safe_float(row[6])
                    })
    except Exception as e:
        logging.error(f"히스토리 DB 쿼리 오류: {e}")
        
    return {"history": history_data}

@app.get("/api/scanner")
async def api_get_scanner():
    results = []
    # 딕셔너리를 리스트 형태로 변환하여 전송
    for t, info in LATEST_SCAN_RESULTS.items():
        results.append({
            "ticker": t,
            "score": info["score"],
            "reason": info["reason"],
            "price": info["price"],
            "mode": info["mode"],
            "mtf": info["mtf"]
        })
    # 점수 높은 순으로 정렬
    results.sort(key=lambda x: x['score'], reverse=True)
    return {"scanner": results, "timestamp": LATEST_SCAN_TS}

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
            # 1. 잔고 조회 후 즉시 시장가 매도
            balances = await execute_upbit_api(upbit.get_balances)
            coin = next((b for b in balances if f"KRW-{b['currency']}" == ticker), None)
            if not coin:
                return {"status": "error", "message": "해당 종목의 잔고가 없습니다."}
            
            qty = safe_float(coin['balance']) + safe_float(coin['locked'])
            if qty <= 0:
                return {"status": "error", "message": "매도 가능한 수량이 없습니다."}
            
            # 매수 시점의 점수 인계 시도
            t_data = trade_data.get(ticker, {})
            p_score = t_data.get('pass_score', 0)
            
            # 매도 실행
            await execute_upbit_api(upbit.sell_market_order, ticker, qty)
            
            # 수익률 계산 (보고서용)
            avg_p = safe_float(coin['avg_buy_price'])
            real_p = safe_float(REALTIME_PRICES.get(ticker, avg_p))
            invested = qty * avg_p * 1.0005
            earned = qty * real_p * 0.9995
            p_krw = earned - invested
            
            await record_trade_db(ticker, 'SELL', real_p, qty, profit_krw=p_krw, reason="[대시보드 수동매도]", pass_score=p_score)
            
            if ticker in trade_data:
                del trade_data[ticker]
                global TRADE_DATA_DIRTY
                TRADE_DATA_DIRTY = True
            
            await send_msg(f"🛑 <b>대시보드 수동 매도 완료</b>: {ticker}\n- 예상 수익금: {p_krw:,.0f}원")
            return {"status": "success", "message": f"{ticker} 매도 주문이 완료되었습니다."}
            
        elif action == "buy":
            # 1. 한도 체크
            max_concurrent = STRAT.get('max_concurrent_trades', 5)
            if len(trade_data) >= max_concurrent:
                return {"status": "error", "message": f"매수 슬롯 한도({max_concurrent}개)에 도달했습니다."}
                
            # 2. 실시간 기준 정보 획득
            cur_p = safe_float(REALTIME_PRICES.get(ticker))
            if cur_p <= 0:
                # 웹소켓 가격이 없으면 REST API로 시도
                cur_p = safe_float(await execute_upbit_api(pyupbit.get_current_price, ticker))
            
            if cur_p <= 0:
                return {"status": "error", "message": "현재가를 불러올 수 없어 매수를 중단합니다."}

            # 3. 매수 실행 (기본 설정 금액 사용)
            buy_amt = STRAT.get('base_trade_amount', 5000)
            await execute_upbit_api(upbit.buy_market_order, ticker, buy_amt)
            
            # 수량 역산 (기록용)
            qty = buy_amt / cur_p if cur_p > 0 else 0
            
            # DB 기록 및 알림 (스캐너에 점수가 있으면 가져다 쓰고, 없으면 기본 80점 부여)
            manual_score = LATEST_SCAN_RESULTS.get(ticker, {}).get('score', 80.0)
            await record_trade_db(ticker, 'BUY', cur_p, qty, profit_krw=0, reason="[대시보드 수동매수]", status="ENTERED", pass_score=manual_score) 
            
            # 🟢 [핵심 수정] 대시보드 즉시 반영을 위한 trade_data 등록
            
            # 티어별 파라미터 미리 계산
            dummy_curr = {'close': cur_p, 'ATR': 0, 'volume': 0} # 평단가 기준 최소 정보
            eval_m = "QUANTUM" if "Quantum" in SYSTEM_STATUS else "CLASSIC"
            t_params = get_coin_tier_params(ticker, dummy_curr, eval_mode=eval_m)
            
            trade_data[ticker] = {
                'entry_price': cur_p,
                'buy_time': time.time(),
                'qty': qty,
                'pass_score': manual_score,
                'buy_reason': "[대시보드 수동매수]",
                'strategy_mode': eval_m,
                'tier_params': t_params,
                'last_ind_update_ts': time.time()
            }
            TRADE_DATA_DIRTY = True
            
            # 즉시 DB 영속성 확보
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
        "max_concurrent_trades": st.get("max_concurrent_trades", 5),
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
        
        # 파일 수동 기록 (비동기로 안전하게)
        await save_config_async(QUANTUM_CONF, CONFIG_PATH)
        await save_config_async(CLASSIC_CONF, CLASSIC_CONFIG_PATH)
        
        # 봇의 메모리 전역 변수에 바로 복사하여 실시간 반영!
        if 'STRAT' in globals() and isinstance(STRAT, dict):
            STRAT["max_concurrent_trades"] = data.max_concurrent_trades
            STRAT["base_trade_amount"] = data.base_trade_amount
            STRAT["max_slippage_pct"] = data.max_slippage_pct
            
        if 'CLASSIC_STRAT' in globals() and isinstance(CLASSIC_STRAT, dict):
            CLASSIC_STRAT["max_concurrent_trades"] = data.max_concurrent_trades
            CLASSIC_STRAT["base_trade_amount"] = data.base_trade_amount
            CLASSIC_STRAT["max_slippage_pct"] = data.max_slippage_pct
            
        logging.info("🌐 웹 대시보드(Settings)에서 봇의 핵심 파라미터가 실시간 오버라이드 되었습니다.")
        return {"status": "success", "message": "Settings perfectly updated and hot-reloaded!"}
        
    except Exception as e:
        logging.error(f"설정 저장 오류: {e}")
        return {"status": "error", "message": str(e)}

if os.path.exists(dashboard_dir):
    app.mount("/", StaticFiles(directory=dashboard_dir, html=True), name="static")
else:
    logging.warning("⚠️ 대시보드 정적 파일 폴더가 없습니다. 웹 UI를 불러올 수 없습니다.")

async def run_fastapi_server():
    try:
        logging.warning("🌐 대시보드 서버 가동 중 (접속: http://localhost:8080)")
        
        # 🟢 서버가 준비되었을 것으로 예상되는 시점에 브라우저를 자동으로 엽니다.
        def open_browser():
            time.sleep(2) # 서버가 기동될 시간을 줍니다.
            webbrowser.open("http://localhost:8080")
        
        asyncio.create_task(asyncio.to_thread(open_browser))

        # 🟢 uvicorn 고유의 로거가 PyInstaller 환경의 stdout과 충돌하여 크래시를 유발하므로 log_config=None 으로 비활성화
        config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_config=None)
        server = uvicorn.Server(config)
        await server.serve()
    except Exception as e:
        logging.error(f"❌ 대시보드 서버 가동 실패: {e}")

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

async def cache_cleanup_task():
    while True:
        try:
            await asyncio.sleep(3600)
            await clean_unused_caches()
        except Exception as e:
            logging.error(f"캐시 청소 에러: {e}")
            await asyncio.sleep(60)

def robust_clean(data):
    if isinstance(data, dict): return {k: robust_clean(v) for k, v in data.items()}
    elif isinstance(data, list): return [robust_clean(v) for v in data]
    # 🟢 [개선] 소수점 8자리 -> 4자리로 줄여 AI 프롬프트 토큰 절약 및 인지력 집중
    elif isinstance(data, (int, float)): return 0 if pd.isna(data) or np.isinf(data) else round(data, 4)
    else: return data

from typing import Any # 파일 맨 위에 추가하시거나 여기에 넣어도 됩니다.

# 🟢 [Pylance 완벽 방어] Any 타입을 명시하여 Pylance의 오탐을 강제로 잠재웁니다.
def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return float(default)
    try:
        return float(val)
    except (ValueError, TypeError):
        try:
            # 🟢 AI가 '-1.5%' 처럼 기호를 섹어넣는 경우 숫자와 마이너스만 췘읠 변환한다
            cleaned = re.sub(r'[^0-9.\-]', '', str(val))
            return float(cleaned) if cleaned else float(default)
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
    global API_FATAL_ERRORS
    for attempt in range(5):
        try:
            res = await asyncio.to_thread(api_call, *args, **kwargs)
            
            # 🟢 [안정성] 호출 성공 시 치명적 에러 카운트 초기화 (장기 가동 시 오알람 방지)
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

# 🟢 비동기 SQLite DB 설정 (경로를 실행파일 폴더로 고정)
DB_FILE = os.path.join(base_path, "ats_unified.db")

async def init_db():
    async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("""CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, ticker TEXT, side TEXT, 
            price REAL, amount REAL, profit_krw REAL, reason TEXT, status TEXT, rating INTEGER, improvement TEXT, pass_score INTEGER)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS trade_status (
            ticker TEXT PRIMARY KEY, data_json TEXT)""")
        try: await db.execute("ALTER TABLE trade_history ADD COLUMN is_reported INTEGER DEFAULT 0")
        except: pass
        await db.commit()



# 🟢 [개선 2-① & 1-②] RAG 컨텍스트 추출 전용 함수 (중복 호출 방지 및 극단적 사례 포함)
async def get_rag_context():
    try:
        async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
            db.row_factory = aiosqlite.Row
            # 1. 가장 크게 수익 난 사례 (최대 2건)
            c1 = await db.execute("SELECT ticker, profit_krw, reason FROM trade_history WHERE side='SELL' AND profit_krw > 0 ORDER BY profit_krw DESC LIMIT 2")
            best_wins = [dict(r) for r in await c1.fetchall()]
            
            # 2. 가장 크게 손실 난 사례 (최대 2건)
            c2 = await db.execute("SELECT ticker, profit_krw, reason FROM trade_history WHERE side='SELL' AND profit_krw < 0 ORDER BY profit_krw ASC LIMIT 2")
            worst_losses = [dict(r) for r in await c2.fetchall()]
            
            # 3. 가장 최근 거래 (최대 2건)
            c3 = await db.execute("SELECT ticker, profit_krw, reason FROM trade_history WHERE side='SELL' ORDER BY id DESC LIMIT 2")
            recent = [dict(r) for r in await c3.fetchall()]
            
            return f"\n[RAG CONTEXT: Learn from Past Trades]\n- Biggest Wins: {best_wins}\n- Biggest Losses: {worst_losses}\n- Recent Trades: {recent}\n* CRITICAL: Avoid setups identical to the 'Biggest Losses'."
    except Exception as e:
        logging.error(f"RAG 데이터 추출 실패: {e}")
        return ""

# 🟢 [Pylance 방어] profit_krw의 기본값을 0.0(float)으로 명시하여 타입 에러를 해결합니다.

async def get_performance_stats_db():
    async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
        db.row_factory = aiosqlite.Row 
        async with db.execute("SELECT ticker, side, price, amount, profit_krw, reason, status, rating, improvement FROM trade_history WHERE side='SELL' ORDER BY id DESC") as cursor:
            rows = await cursor.fetchall()
            rows = list(rows) # Explicitly convert to list to ensure len() is supported
            
    total_cnt = len(rows)
    history = [dict(row) for row in rows]
    wins = [t for t in history if t['profit_krw'] > 0]
    losses = [t for t in history if t['profit_krw'] <= 0]
    win_rate = (len(wins) / total_cnt * 100) if total_cnt >= 1 and total_cnt > 0 else 50.0
    total_profit = sum(t['profit_krw'] for t in history)
    return win_rate, total_cnt, len(wins), total_profit, wins, losses

# [OHLCV 정리용 헬퍼 함수 추가]
async def clean_unused_caches():
    global OHLCV_CACHE, INDICATOR_CACHE, STRAT, trade_data
    active_tickers = set(STRAT.get('tickers', []) + list(trade_data.keys()) + ["KRW-BTC"])
    
    async with OHLCV_CACHE_LOCK:
        for t in list(OHLCV_CACHE.keys()):
            if t not in active_tickers:
                del OHLCV_CACHE[t]

    # 🟢 [버그픽스] INDICATOR_CACHE: Lock 보호 하에 안전하게 삭제
    async with INDICATOR_CACHE_LOCK:
        for t in list(INDICATOR_CACHE.keys()):
            if t not in active_tickers:
                del INDICATOR_CACHE[t]
            
    for t in list(REALTIME_CVD.keys()):
        if t not in active_tickers:
            if t in REALTIME_CVD: del REALTIME_CVD[t]
            if t in REALTIME_PRICES_TS: del REALTIME_PRICES_TS[t]
            if t in REALTIME_PRICES: del REALTIME_PRICES[t]

async def update_top_volume_tickers():
    global STRAT
    try:
        tickers = await execute_upbit_api(pyupbit.get_tickers, fiat="KRW")
        if not tickers: return STRAT.get('tickers', [])
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
        await clean_unused_caches()  # 불필요한 OHLCV/지표 캐시 정리
        return top_tickers
    except Exception as e:
        logging.error(f"❌ update_top_volume_tickers 오류: {e}")
        await clean_unused_caches()  # 오류가 나도 캐시 정리는 시도
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
        
        try:
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
        return FGI_CACHE['data']
    except Exception as e:
        # 에러 발생 시 기존에 캐싱된 값을 반환하여 봇이 절대 멈추지 않도록 방어
        logging.error(f"⚠️ FGI 지수 갱신 실패 (기존 값 유지): {e}")
        return FGI_CACHE['data']

# 👇 [새로 추가할 코드] 실시간 웹소켓 가격 수신 엔진
async def websocket_ticker_task():
    global REALTIME_PRICES, STRAT, trade_data, REALTIME_CVD
    uri = "wss://api.upbit.com/websocket/v1"

    # 🟢 [추가] certifi를 이용해 안전한 SSL/TLS 컨텍스트 생성
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    while True:
        try:
            # 🟢 [수정] websockets.connect에 ssl=ssl_context 파라미터 추가!
            async with websockets.connect(uri, ping_interval=60, ping_timeout=30, ssl=ssl_context) as websocket:
                logging.info("🌐 업비트 실시간 웹소켓 연결 성공 (Ticker & Trade)")

                # 현재 감시해야 할 종목 리스트 (보유종목 + 스캔대상 + BTC)
                current_tickers = list(set(STRAT.get('tickers', []) + ["KRW-BTC"] + list(trade_data.keys())))

                # 🟢 [개선 2-②] ticker와 함께 'trade'(체결) 데이터도 구독합니다!
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
                    # 1. 중간에 코인이 매수/매도되거나 스캔 대상이 바뀌면 동적으로 웹소켓 '재구독' 처리
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

                    # 🟢 [Half-Open 감지] 120초간 데이터 수신이 전혀 없으면 '죽은 연결'로 간주하고 재접속 시도
                    now_ws = time.time()
                    if now_ws - ws_last_check_ts >= 120:
                        if ws_recv_count == 0:
                            logging.warning("⚠️ 웹소켓 수신 지연(120초) 감지. 강제 재연결을 시도합니다.")
                            break  # Inner loop 탈출 -> outer while: reconnect
                        ws_recv_count = 0
                        ws_last_check_ts = now_ws

                    # 2. 데이터 수신 (Timeout을 짧게 주어 루프가 멈추지 않고 종목 변경을 체크할 수 있게 함)
                    try:
                        raw_data = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        ws_recv_count += 1
                        if isinstance(raw_data, bytes):
                            data = json.loads(raw_data.decode('utf-8'))
                        elif isinstance(raw_data, str):
                            data = json.loads(raw_data)
                        else:
                            data = raw_data

                        # dict 타입 확인 후 키 접근 (타입 체커 대응)
                        if isinstance(data, dict):
                            code_str = str(data.get('code'))
                            
                            if data.get('type') == 'ticker':
                                price = float(data['trade_price'])
                                REALTIME_PRICES[code_str] = price
                                REALTIME_PRICES_TS[code_str] = time.time()
                                await asyncio.sleep(0)
                                
                                # 🟢 [BTC 급등 감지] BTC 가격을 슬라이딩 윈도우에 누적
                                if code_str == 'KRW-BTC':
                                    global BTC_SURGE_TRIGGERED, BTC_PRICE_WINDOW, BTC_SURGE_COOLDOWN_TS
                                    now_ws = time.time()
                                    BTC_PRICE_WINDOW[now_ws] = price
                                    # 1분 답는 데이터만 유지 (60작 윈도우)
                                    cutoff = now_ws - 60
                                    BTC_PRICE_WINDOW = {t: p for t, p in BTC_PRICE_WINDOW.items() if t >= cutoff}
                                    # 1분 전 기준값 vs 현재 가격으로 상승률 산정
                                    if len(BTC_PRICE_WINDOW) >= 2:
                                        oldest_ts = min(BTC_PRICE_WINDOW.keys())
                                        oldest_price = BTC_PRICE_WINDOW[oldest_ts]
                                        if oldest_price > 0:
                                            pct_change = (price - oldest_price) / oldest_price * 100
                                            cooldown_ok = (now_ws - BTC_SURGE_COOLDOWN_TS) >= 180  # 3분 쿨다운
                                            if pct_change >= BTC_SURGE_THRESHOLD and not BTC_SURGE_TRIGGERED and cooldown_ok:
                                                BTC_SURGE_TRIGGERED = True
                                                BTC_SURGE_COOLDOWN_TS = now_ws
                                                logging.warning(f"🚨 BTC 급등 감지! 1분 +{pct_change:.2f}% → 비정규 딥스캔 트리거")
                                
                            # 🟢 실시간 Taker Buy/Sell 누적 로직 (강력한 선행 지표)
                            elif data.get('type') == 'trade':
                                vol = float(data.get('trade_volume', 0))
                                ask_bid = data.get('ask_bid') # ASK=매도호가체결(시장가매수), BID=매수호가체결(시장가매도)
                                
                                if ask_bid == 'ASK':
                                    REALTIME_CVD[code_str] = REALTIME_CVD.get(code_str, 0.0) + vol
                                elif ask_bid == 'BID':
                                    REALTIME_CVD[code_str] = REALTIME_CVD.get(code_str, 0.0) - vol

                    except asyncio.TimeoutError:
                        continue # 1초 동안 시장에 거래가 없으면 다음 루프로 넘어가서 종목 변경 유무만 체크

        except Exception as e:
            logging.error(f"⚠️ 웹소켓 연결 끊김 ({e}). 3초 후 재연결 자동 시도...")
            await asyncio.sleep(3.0)
            

# 👇 [새로 추가할 함수] 순수 CPU 연산(pandas_ta)을 전담할 백그라운드 스레드용 함수

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
        
        # 🟢 [추가 1] CVD (Cumulative Volume Delta) 근사치 계산 로직
        # 고가-저가 범위 내에서 종가의 위치를 기반으로 매수/매도 압력을 분리합니다.
        high_low_range = df['high'] - df['low']
        high_low_range = high_low_range.replace(0, 0.00001) # 0으로 나누기 방지
        
        buy_pressure = df['volume'] * ((df['close'] - df['low']) / high_low_range)
        sell_pressure = df['volume'] * ((df['high'] - df['close']) / high_low_range)
        df['vol_delta'] = buy_pressure - sell_pressure
        
        # 최근 20캔들 동안의 순매수/순매도 누적량 (CVD)
        df['cvd'] = df['vol_delta'].rolling(window=20).sum()
        
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
        
        # 4. 일목균형표(Ichimoku) 수동 계산 방어코드
        # 🟢 [코드 레벨 픽스] pandas-ta의 ichimoku 함수 내의 datetime offset('d') 등 미래에 폐기(Deprecated)될 
        # 판다스 문법을 원천 차단하기 위해 순수 수치 연산만으로 일목균형표를 수동 구현했습니다.
        t_len = int(float(strat_params.get('ichimoku_conversion_len', 9)))
        k_len = int(float(strat_params.get('ichimoku_base_len', 26)))
        s_len = int(float(strat_params.get('ichimoku_lead_span_b_len', 52)))
        
        tenkan_max = df['high'].rolling(window=t_len).max()
        tenkan_min = df['low'].rolling(window=t_len).min()
        tenkan_sen = (tenkan_max + tenkan_min) / 2
        
        kijun_max = df['high'].rolling(window=k_len).max()
        kijun_min = df['low'].rolling(window=k_len).min()
        kijun_sen = (kijun_max + kijun_min) / 2
        
        senkou_span_a_raw = (tenkan_sen + kijun_sen) / 2
        
        senkou_b_max = df['high'].rolling(window=s_len).max()
        senkou_b_min = df['low'].rolling(window=s_len).min()
        senkou_span_b_raw = (senkou_b_max + senkou_b_min) / 2
        
        # 선행 스팬: 앞으로 이동(과거의 가격이 현재의 구름대를 형성)
        df['span_a'] = senkou_span_a_raw.shift(k_len - 1).fillna(df['close'])
        df['span_b'] = senkou_span_b_raw.shift(k_len - 1).fillna(df['close'])
        
        ssl_len = strat_params.get('ssl_len', 70)
        sma_h, sma_l = df.ta.sma(close=df['high'], length=ssl_len), df.ta.sma(close=df['low'], length=ssl_len)
        df['c'] = np.where(df['close'] > sma_h, 1, np.where(df['close'] < sma_l, -1, 0))
        
        # 🟢 [코드 레벨 픽스] .replace 의 암묵적 다운캐스팅 경고를 회피하기 위한 명시적 마스킹 처리
        df['c'] = df['c'].astype(float)
        df.loc[df['c'] == 0.0, 'c'] = np.nan
        df['d'] = df['c'].ffill().fillna(1)
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

INDICATOR_CACHE, INDICATOR_CACHE_SEC = {}, 60  # 🟢 [최적화] 14초→60초: 15분봉 불필요한 재계산 방지
OHLCV_CACHE = {} 
BALANCE_CACHE, BALANCE_CACHE_SEC = {"data": None, "timestamp": 0}, 10

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
            await asyncio.sleep(0.15)  # 🟢 [최적화] 캐시 미스 시에만 딜레이 (캐시 히트 시 12초 절약)
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
        
        # 🟢 [최적화] 고정된 스레드 풀으로 TA 계산 (스레드 경합 최소화 + 안정적 성능)
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

# 🟢 [FIX: 거시 트렌드 스캔 시 API 병목(Rate Limit)을 막기 위한 MTF 캐싱]
async def get_mtf_trend(ticker):
    global MTF_CACHE
    now = time.time()
    if ticker in MTF_CACHE and (now - MTF_CACHE[ticker]['time'] < MTF_CACHE_SEC):
        return MTF_CACHE[ticker]['data']

    try:
        await asyncio.sleep(0.05)
        df_1h = await execute_upbit_api(pyupbit.get_ohlcv, ticker, interval="minute60", count=30)
        df_4h = await execute_upbit_api(pyupbit.get_ohlcv, ticker, interval="minute240", count=30)
        
        if df_1h is None or df_1h.empty or df_4h is None or df_4h.empty: 
            return {"str": "알수없음", "4h_macd": 0, "1h_trend": 0}

        ema20_1h = df_1h.ta.ema(length=20).iloc[-1]
        macd_4h = df_4h.ta.macd(fast=12, slow=26, signal=9)
        macd_hist_4h = macd_4h[macd_4h.columns[1]].iloc[-1] if macd_4h is not None else 0

        trend_1h = "상승(EMA20 위)" if df_1h['close'].iloc[-1] > ema20_1h else "하락/횡보"
        trend_4h = "강세(MACD>0)" if macd_hist_4h > 0 else "약세(MACD<0)"
        
        # 🟢 [추가 2] 파이썬 로직에서 써먹기 위해 수치형 데이터를 함께 반환
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

def extract_ai_essential_data(curr_data):
    # AI가 차트를 판단하는 데 꼭 필요한 핵심 지표만 필터링 (고도화 지표 추가)
    essential_keys = [
        'close', 'volume', 'rsi', 'macd_h', 'ST_DIR', 'adx', 'z_score', 'bb_bw', 'cvd',
        'dist_sma20', 'atr_pct', 'v_shape_special', 'is_volume_spike', 'is_bullish_recovery', 
        'cvd_improving', 'ob_imbalance', 'is_pullback_zone', 'is_rsi_cooling'
    ]
    return {k: round(v, 4) if isinstance(v, (int, float)) else v for k, v in curr_data.items() if k in essential_keys}

# --- [4. AI 분석 엔진] ---
async def ai_analyze(ticker, data, mode="BUY", eval_mode="CLASSIC", no_trade_hours=0.0, win_rate=50.0, recent_wins=None, mtf_trend="알수없음", buy_price=0.0, market_regime=None, ignore_cooldown=False, rag_context="", expected_slippage=0.0, exit_plan_preview=None, strategy_intent="알수없음", coin_tier="알수없음"):
    global last_ai_call_time, last_coin_ai_call
    if mode == "BUY" and not ignore_cooldown and (time.time() - last_coin_ai_call.get(ticker, 0)) < 300: return None
    clean_data = robust_clean(data)

    if mode == "OPTIMIZE":
        # 🟢 [수정 1] 전역 STRAT이 아닌, 최적화하려는 '해당 모드'의 진짜 설정값을 가져옵니다.
        target_strat = get_strat_for_mode(eval_mode)
        
        forbidden_keys = ['tickers', 'max_concurrent_trades', 'interval', 'report_interval_seconds', 'history_win_count', 'history_loss_count', 'exit_plan_guideline']
        allowed_keys = [k for k in target_strat.keys() if k not in forbidden_keys]
        s_count = target_strat.get('success_reference_count', 8)
        f_count = target_strat.get('failure_reference_count', 8)
        
        # 기본 공통 허용 키
        common_keys = ['indicator_weights', 'scoring_modifiers', 'btc_short_term_vol_threshold', 'sleep_depth_threshold', 'risk_per_trade', 'high_vol_params', 'mid_vol_params', 'major_params', 'success_reference_count', 'failure_reference_count']
        for k in common_keys:
            if k not in allowed_keys: allowed_keys.append(k)

        # 🟢 [수정 2] 클래식과 퀀텀 모드의 Allowed Keys와 Important Ranges 철저히 분리
        if eval_mode == "CLASSIC":
            classic_keys = ['bonus_mtf_panic_dip', 'bonus_btc_panic_dip', 'bonus_golden_combo', 'bonus_st_oversold_bounce', 'penalty_st_downtrend', 'penalty_rs_weakness']
            for k in classic_keys: 
                if k not in allowed_keys: allowed_keys.append(k)
                
            strategy = "Deep Dip / Oversold Mean Reversion (낙폭 과대 역추세 매매)"
            important_ranges = """
            - pass_score_threshold: MUST be between 75 and 85 (Higher is safer)
            - guard_score_threshold: MUST be between 50 and 60
            - sell_score_threshold: MUST be between 30 and 45
            - bonus_golden_combo: MUST be between 25 and 45
            - bonus_mtf_panic_dip: MUST be between 15 and 35
            - bonus_st_oversold_bounce: MUST be between 10 and 25
            - penalty_st_downtrend: MUST be between -10 and 0 (Keep low for dips)
            - major_params/target_atr_multiplier: 1.5 ~ 3.0 (FOR QUICK SCALPS)
            - mid/high_vol_params/target_atr_multiplier: 2.5 ~ 4.5
            - timeout_candles: 3 ~ 8 (CRITICAL: Keep this low for scalping)
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

        # 🟢 [수정 3] AI에게 오염된 전역 STRAT이 아닌, 깨끗한 target_strat을 넘깁니다.
        # 수치 할루시네이션 방지를 위해 "Key: Value" 리스트로 변환하여 명시적으로 전달
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
        {mission}
        """
        
    elif mode == "SELL_REASON":
        strategy_mode = clean_data.get('strategy_mode', 'UNKNOWN')
        if eval_mode == "CLASSIC":
            strategy_desc = "Mean Reversion"
        else:
            strategy_desc = "Trend Following"
            
        # 🟢 [추가 및 보강] 최고 도달 수익률, 보유 시간, 원래 계획을 모두 프롬프트에 노출시킵니다!
        prompt = f"""
        [X_SELL_REASON]
        Ticker: {ticker} | Mode: {strategy_mode}
        Final Profit: {clean_data.get('p_rate')}% | Max Reached Profit: {clean_data.get('max_p_rate', '알수없음')}%
        Hold Duration: {clean_data.get('elapsed_min', '알수없음')} minutes
        BTC Change: {clean_data.get('btc_change')}%
        
        Original Buy Reason: {clean_data.get('original_buy_reason')}
        Original Exit Plan: {clean_data.get('original_exit_plan')}
        * Note for AI: 1) 'timeout' in Exit Plan is in CANDLES (15m each). 2) The Python engine now also uses 'Nano Timeout' (3 min) and 'Micro Timeout' (15 min) for immediate exit if a trade fails to bounce or breaks momentum early. Recognize these as excellent "Immediate Risk Cuts", NOT failure of the strategy.
        
        Buy Indicators: {clean_data.get('buy_ind')}
        Sell Indicators: {clean_data.get('sell_ind')}
        Actual Sell Reason: {clean_data.get('actual_sell_reason')}
        
        Mission: Rate the trade performance (0-100) based on the {strategy_desc} strategy, and suggest improvements in Korean.
        Did it follow the Original Exit Plan? Should it have taken profit earlier based on Max Reached Profit? 
        * CRITICAL NOTES: 
        1. If closed via 'Trailing Stop' or 'Breakeven Lock' with positive profit, rate it highly (>75) as successful risk management.
        2. 'Buy Indicators' are from an INCOMPLETE candle (live data). Do not overly penalize low volume if other oversold signals were extremely strong.
        Provide JSON ONLY in this exact format:
        {{"rating": 85, "status": "SUCCESS" or "FAIL" or "ACCEPTABLE", "reason": "상세한 분석 및 개선점(한국어)"}}
        """
        
    elif mode == "BUY": 
        strategy_mode = clean_data.get('strategy_mode', 'QUANTUM')
        guideline = get_dynamic_strat_value('exit_plan_guideline', mode=strategy_mode, default='Follow Tier Params.')
        warning_msg = f"🚨 WARNING: {clean_data['warning']}" if (isinstance(clean_data, dict) and clean_data.get('warning')) else ""
        
        if eval_mode == "CLASSIC":
            strategy_desc = "Deep Dip / Oversold Mean Reversion (낙폭 과대 역추세 매매)"
        else:
            strategy_desc = "Trend Follower & Pullback Sniper (상승 추세 눌림목 매매)"
        
        # 🟢 [Step 2 핵심: 에이전트 워크플로우(Agentic Workflow) 프롬프트]
        prompt = f"""
        [X_BUY]
        Ticker: {ticker} | Slot: {STRAT.get('max_concurrent_trades', 5)}
        Strategy Intent: {strategy_intent} | Coin Tier: {coin_tier}
        Mode: {eval_mode} | MTF: {mtf_trend} | Regime: {market_regime}
        Current Price: {clean_data.get('close')} | Prev Close: {clean_data.get('prev_close', '알수없음')}
        Orderbook Ask/Bid Imbalance: {clean_data.get('ob_imbalance', '알수없음')}
        Expected Slippage: {expected_slippage}% (If > 0.3%, consider SKIP or reduce score)
        
        Indicators: {clean_data}
        Expected Exit Plan: {exit_plan_preview}
        Python Score: {clean_data.get('python_pass_score')}
        Guideline: {guideline}
        {warning_msg}
        {rag_context}
        
        Mission: Execute an AGENTIC WORKFLOW. You are a committee of 3 experts.
        [KEY INDICATORS TO CHECK]:
        - 'is_pullback_zone': TRUE if price is currently holding SMA20 support (CRITICAL for Quantum Pullback).
        - 'dist_sma20': Percentage gap from SMA20. Large negative means extreme oversold (CRITICAL for Classic).
        - 'is_volume_spike' / 'is_bullish_recovery' / 'cvd_improving': These are mandatory confirmations for a safe entry.
        
        Step 1. [Risk Agent]: Analyze downside risks, orderbook imbalance, and confirm if 'is_bullish_recovery' is TRUE.
        Step 2. [Trend Agent]: Analyze upside potential, volume validation ('is_volume_spike'), and CVD strength ('cvd_improving').
        Step 3. [Chief Strategy Officer]: Synthesize opinions and make the ultimate decision.
        
        Output "BUY" if the synthesized AI Score >= 70. Otherwise "SKIP". Provide JSON.
        """
        
    elif mode == "POST_BUY_REPORT": 
        strategy_mode = clean_data.get('strategy_mode', 'QUANTUM')
        warning_msg = f"🚨 WARNING: {clean_data['warning']}" if (isinstance(clean_data, dict) and clean_data.get('warning')) else ""
        
        if eval_mode == "CLASSIC":
            strategy_desc = "'Deep Dip / Oversold Mean Reversion' (낙폭 과대 역추세 매매)"
        else:
            strategy_desc = "'Trend Follower & Pullback Sniper' (상승 추세 눌림목 매매)"
        
        prompt = f"""
        [X_POST_BUY_REPORT]
        Ticker: {ticker} | Mode: {strategy_mode} | Tier: {coin_tier}
        Entry Price: {buy_price:,.0f} | Intent: {strategy_intent}
        Indicators: {clean_data}
        Expected Exit Plan: {exit_plan_preview}
        {warning_msg}
        Situation: Python preemptive purchase based on {strategy_desc}.
        Mission: Re-verify entry quality.
        - Check 'is_pullback_zone': Is it holding support?
        - Check 'dist_sma20': Is the dip deep enough?
        - Check 'is_volume_spike' / 'is_bullish_recovery' / 'cvd_improving': Mandatory confirmations.
        If 'v_shape_special' is TRUE, it was a high-conviction V-reversal attempt.
        Your final decision is BUY or SKIP. Provide JSON.
        """
        
    elif mode == "EVOLVE_PROMPT":
        target_strat = get_strat_for_mode(eval_mode)
        current_guideline = target_strat.get('exit_plan_guideline', '없음')
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
                    "improvement": str(res_json.get('improvement', '없음'))
                }

            if mode in ("POST_BUY_REPORT", "BUY"):
                score = int(res_json.get('score', 50 if mode == "POST_BUY_REPORT" else 0))
                decision = str(res_json.get('decision', 'SKIP')).upper()
                if mode == "POST_BUY_REPORT" and decision not in ('BUY', 'SKIP'): decision = 'BUY' if score >= 50 else 'SKIP'
                if mode == "BUY" and decision not in ('BUY', 'SKIP'): decision = 'SKIP'
                
                extracted_reason = res_json.get('reason')
                if not extracted_reason:
                    cso_opinion = res_json.get('chief_strategy_officer_opinion')
                    if isinstance(cso_opinion, dict): 
                        extracted_reason = cso_opinion.get('reason', 'N/A')
                    elif isinstance(cso_opinion, str): 
                        extracted_reason = cso_opinion
                    else: 
                        extracted_reason = 'N/A'
                        
                raw_plan = res_json.get('exit_plan', {})
                strategy_mode = clean_data.get('strategy_mode', 'QUANTUM')
                default_stop = -1.6 if strategy_mode == "QUANTUM" else -2.5
                default_atr = 1.0 if strategy_mode == "QUANTUM" else 1.5
                default_timeout = 5 if strategy_mode == "QUANTUM" else 10
                exit_plan = {
                    "target_atr_multiplier": max(1.0, min(10.0, safe_float(raw_plan.get('target_atr_multiplier', 3.5)))),
                    "stop_loss": max(-4.0, min(-0.5, safe_float(raw_plan.get('stop_loss', default_stop)))),
                    "atr_mult": max(0.5, min(4.0, safe_float(raw_plan.get('atr_mult', default_atr)))),
                    "timeout": max(2, min(15, int(safe_float(raw_plan.get('timeout', default_timeout)))))
                }
                return {"score": score, "decision": decision, "reason": str(extracted_reason), "exit_plan": exit_plan}
                
        except Exception as e:
            err_str = str(e).lower()
            # 🟢 [개선] 503 과부하 에러 시 더 긴 시간 대기 (서버에 숨 고를 시간을 부여)
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
                if msg_parts: changes.append(f"• 🚀 <b>강추세 지표</b>: {' / '.join(msg_parts)}")
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
                    if old_v != v: weight_changes.append(f"{k}({old_v}→{v})")
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
                    mod_changes.append(f"{mk}({old_mv}→{clamped_mods[mk]})")
                    
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
            table_str += "<pre>Tier |  SL  | TAM |  ABB  | ASTH | ADX\n"
            table_str += "----------------------------------------\n"
            for tk, name in zip(tier_keys, ['High ', 'Mid  ', 'Major']):
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
                        # 🟢 [개선] CLASSIC 모드는 더 낮은 임계값(30점)에서도 버틸 수 있게 허용
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
                    changes.append(f"• {k}: {target_strat.get(k)} → <b>{v}</b>")
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
                    await execute_upbit_api(upbit.sell_market_order, ticker, actual_rem)

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
    global TRADE_DATA_DIRTY, trade_data # ?? [ ȭ] Pylance    Ȯ
    await asyncio.sleep(1.0) 
    regime = await get_market_regime()
    wr, _, _, _, _, _ = await get_performance_stats_db()
    
    global TRADE_DATA_DIRTY
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
            await send_msg(f"🚨 <b>AI 긴급 철수 발령</b>: {ticker} 위험 감지!\n👉 <b>최소 손실 탈출 모드로 전환합니다!</b>")
            t['exit_plan'] = {'target_atr_multiplier': 1.0, 'stop_loss': -0.7, 'atr_mult': 0.5, 'timeout': 2}
        else:
            t['exit_plan'] = ai_res.get('exit_plan', {})
            await send_msg(f"📝 <b>AI 사후 결재 (스나이퍼)</b>: {ticker} (파이썬:{pass_score}점 ➡️ AI:{score}점)\n- 작전: {t['exit_plan']}\n- 코멘트: {safe_reason}")
            
        t['buy_reason'] = f"[스나이퍼 선제공격] {safe_reason}"
        TRADE_DATA_DIRTY = True

# --- [5. 공통 스캔 모듈] ---
async def process_buy_order(ticker, score, reason, curr_data, total_asset, cash, held_count, exit_plan, buy_mode="COUNCIL", pass_score=0, eval_mode="QUANTUM"):
    global last_global_buy_time, TRADE_DATA_DIRTY
    
    strat = get_strat_for_mode(buy_mode)
    max_trades = strat.get('max_concurrent_trades', STRAT.get('max_concurrent_trades', 5)) 
    if held_count >= max_trades: return False

    wr_pct, total_cnt, _, _, wins, losses = await get_performance_stats_db()
    
    base_risk = strat.get('risk_per_trade', STRAT.get('risk_per_trade', 2.0)) / 100.0
    risk_pct = base_risk
    
    if total_cnt >= 10:
        W = wr_pct / 100.0
        
        win_pcts = [(w['profit_krw'] / (safe_float(w.get('price')) * safe_float(w.get('amount')))) for w in wins if safe_float(w.get('price')) > 0 and safe_float(w.get('amount')) > 0]
        loss_pcts = [abs(l['profit_krw'] / (safe_float(l.get('price')) * safe_float(l.get('amount')))) for l in losses if safe_float(l.get('price')) > 0 and safe_float(l.get('amount')) > 0]
        
        avg_win_pct = sum(win_pcts) / len(win_pcts) if win_pcts else 0.01
        avg_loss_pct = sum(loss_pcts) / len(loss_pcts) if loss_pcts else 0.01
        
        R = avg_win_pct / avg_loss_pct if avg_loss_pct > 0 else 1.5
        
        kelly_fraction = W - ((1.0 - W) / R)
        
        if kelly_fraction > 0:
            risk_pct = max(0.005, min(0.04, kelly_fraction / 2.0))
        else:
            risk_pct = 0.005

    atr_pct = (curr_data['ATR'] / curr_data['close']) if curr_data['close'] > 0 else 0.01
    atr_pct = max(0.005, atr_pct) 
    
    risk_parity_amt = (total_asset * risk_pct) / atr_pct
    max_slot_amt = (total_asset / max_trades) * 1.2

    
    buy_amt = min(risk_parity_amt, max_slot_amt, cash * 0.99)
    if (cash * 0.99) - buy_amt < 6000: buy_amt = cash * 0.99
        
    if buy_amt >= 6000: 
        max_tolerable_price = curr_data['close'] * 1.005 
        buy_success, fail_reason = await execute_smart_buy(ticker, buy_amt, max_tolerable_price)
        
        if buy_success:
            await asyncio.sleep(1.5)
            current_balances = await execute_upbit_api(upbit.get_balances)
            coin_currency = ticker.split('-')[1]
            
            if isinstance(current_balances, list):
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
            
            tier_params = get_coin_tier_params(ticker, curr_data, eval_mode=eval_mode)
            
            if exit_plan:
                temp_exit_plan = exit_plan  
            else:
                # 🟢 [손익비 최적화] ATR 기반 동적 손실 제한 도입 (Risk/Reward 균형)
                atr_pct = (curr_data.get('ATR', 0) / curr_data.get('close', 1)) * 100
                target_mult = tier_params.get('target_atr_multiplier', 4.5)
                # 손절 멀티플라이어는 익절의 약 50~70% 수준으로 자동 산정 (익절 기대치보다 손절이 크지 않게)
                sl_atr_mult = tier_params.get('atr_mult', 2.0) 
                
                dynamic_sl = -(atr_pct * sl_atr_mult)
                hard_sl_cap = tier_params.get('stop_loss', -3.0)
                
                # 최종 손절선은 '동적 손절'과 '하드 캡' 중 더 촘촘한 것으로 선택
                final_sl = max(dynamic_sl, hard_sl_cap)
                
                # 🚨 [안전장치] 손익비 최적화 (손실을 기대수익의 약 70% 이내로 압착)
                expected_target = atr_pct * target_mult
                if abs(final_sl) > (expected_target * 0.7):
                    final_sl = -(expected_target * 0.7)
                
                temp_exit_plan = {
                    "target_atr_multiplier": target_mult,
                    "stop_loss": round(final_sl, 2),
                    "atr_mult": sl_atr_mult,
                    "timeout": tier_params.get('timeout_candles', 8)
                }
            
            # 클래식 모드는 0.4% 이상의 본절점(Breakeven) 버퍼를 명시적으로 강화
            temp_exit_plan['adaptive_breakeven_buffer'] = tier_params.get('adaptive_breakeven_buffer', 0.007)

            buy_ind_dict = curr_data if isinstance(curr_data, dict) else curr_data.to_dict()

            trade_data[ticker] = {
                'high_p': final_buy_price, 'entry_atr': curr_data.get('ATR', 0), 'guard': False,
                'buy_ind': buy_ind_dict, 
                'last_notified_step': 0, 'buy_ts': now_ts,
                'exit_plan': temp_exit_plan, 'buy_reason': reason, 'btc_buy_price': REALTIME_PRICES.get('KRW-BTC', 0),
                'pass_score': pass_score, 'is_runner': False, 'score_history': [pass_score],
                'strategy_mode': buy_mode
            }
            TRADE_DATA_DIRTY = True
            await record_trade_db(ticker, 'BUY', final_buy_price, buy_amt, profit_krw=0, reason=reason, status="ENTERED", rating=int(score), pass_score=pass_score)        
            
            if buy_mode == "SNIPER":
                await send_msg(f"🎯 <b>스나이퍼 선제 매수 완료</b>: {ticker} (파이썬:{pass_score:.1f}점)\n- <b>매수 금액: {buy_amt:,.2f}원</b>\n👉 <b>사후 결재 대기중.</b>")
                mtf = await get_mtf_trend(ticker)
                asyncio.create_task(background_ai_post_report(ticker, curr_data, mtf, final_buy_price, pass_score, eval_mode))
            else:
                safe_reason = str(reason).replace('<', '&lt;').replace('>', '&gt;')
                await send_msg(f"✅ <b>참모회의 매수 승인</b>: {ticker} (파이썬:{pass_score:.1f}점 ➡️ AI:{score:.1f}점)\n- <b>매수 금액: {buy_amt:,.2f}원</b>\n- 분석: {safe_reason}")
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

        if fgi_val <= 35 or (btc_short['trend'] == "단기 하락" and fgi_val <= 50):
            current_regime_mode = "CLASSIC" 
            new_status = "📉 Classic (Deep Dip Sniper)"
        elif fgi_val >= 65 or (btc_short['trend'] == "단기 상승" and fgi_val >= 50):
            current_regime_mode = "QUANTUM" 
            new_status = "🚀 Quantum (Trend Breakout)"
        else:
            current_regime_mode = "HYBRID" 
            new_status = "⚖️ Hybrid (Adaptive Monitoring)"

        SYSTEM_STATUS = new_status 
        if is_deep_scan: 
            try:
                await asyncio.wait_for(update_top_volume_tickers(), timeout=60.0)
            except asyncio.TimeoutError:
                logging.error("⚠️ 상위 종목 리스트 갱신 시간 초과. 다음 턴을 노립니다.")

        balances = await execute_upbit_api(upbit.get_balances)
        if not isinstance(balances, list): return
        cash = safe_float(next((b.get('balance') for b in balances if isinstance(b, dict) and b.get('currency') == "KRW"), 0.0))
        held_dict = {f"KRW-{b.get('currency')}": safe_float(b.get('avg_buy_price')) for b in balances if isinstance(b, dict) and b.get('currency') != "KRW" and (safe_float(b.get('balance')) + safe_float(b.get('locked'))) * safe_float(b.get('avg_buy_price')) >= 5000}
        
        total_asset = cash
        for b in balances:
            if isinstance(b, dict) and b.get('currency') and b.get('currency') != "KRW":
                ticker = f"KRW-{b.get('currency')}"
                avg_p = safe_float(b.get('avg_buy_price'))
                p = safe_float(REALTIME_PRICES.get(ticker, avg_p))
                total_asset += (safe_float(b.get('balance')) + safe_float(b.get('locked'))) * p

        base_max_trades = STRAT.get('max_concurrent_trades', 5)
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
                await asyncio.sleep(0.05) # 🟢 딜레이 단축 (0.1 -> 0.05)
                p, c = await get_indicators(ticker)
                mtf = await get_mtf_trend(ticker) # 🟢 MTF 추세를 병렬 단계로 전진 배치
                return ticker, p, c, mtf

        fetch_tasks = [fetch_data(t) for t in STRAT['tickers']]
        indicator_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        # 🟢 결과 구조 변경 반영 (p, c, mtf)
        indicator_results = [res for res in indicator_results if isinstance(res, tuple) and len(res) == 4]

        python_passed = []
        current_loop_max_score = 0
        
        # 🟢 [대시보드 스캐너] 이번 루프의 스캔 결과를 취합합니다.
        new_scan_data = {}

        for t, prev, curr, mtf_res in indicator_results:
            if curr is None or prev is None: continue
            
            if isinstance(prev, pd.Series): prev = prev.to_dict()
            if isinstance(curr, pd.Series): curr = curr.to_dict()
            if not isinstance(prev, dict) or not isinstance(curr, dict): continue

            # get_mtf_trend 호출 제거 (이미 fetch_data에서 가져옴)
            score_1st, fatal_reason_1st, mode = evaluate_coin_fundamental(t, prev, curr, current_regime_mode, fgi_val, btc_short['trend'], mtf_data=mtf_res)

            # 🟢 [수정] 하드락이 아니면 대기 최고 점수 갱신에 우선 반영 (보고서 동기화용)
            if not fatal_reason_1st:
                current_loop_max_score = max(current_loop_max_score, score_1st)

            # 스캐너 데이터 저장 (필터링 전 모든 종목 기록)
            new_scan_data[t] = {
                "score": score_1st,
                "reason": fatal_reason_1st if fatal_reason_1st else "PASS",
                "price": safe_float(curr.get('close')),
                "mode": mode,
                "mtf": mtf_res.get('str', '알수없음')
            }

            pass_cut = get_dynamic_strat_value('pass_score_threshold', mode=mode, default=80)
            
            # 🟢 [최적화] 중복 채점(evaluate_coin_fundamental 2회 호출) 제거
            final_score = score_1st
            final_fatal_reason = fatal_reason_1st

            if final_fatal_reason or final_score < pass_cut: 
                continue

            if t in held_dict or (time.time() - last_sell_time.get(t, 0)) < 1800: continue
            
            python_passed.append({"t": t, "score": final_score, "data": curr, "prev_data": prev, "mtf": mtf_res["str"], "mode": mode})

        # 전역 스캐너 데이터 업데이트
        global LATEST_SCAN_RESULTS, LATEST_SCAN_TS
        LATEST_SCAN_RESULTS = new_scan_data
        LATEST_SCAN_TS = time.time()
        
        LATEST_TOP_PASS_SCORE = current_loop_max_score

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
            report_msg += f"• {p['t']} : {p['score']:.1f}점 ({mode_icon} {p['mode']})\n"
        await send_msg(report_msg)

        ai_approved = []
        ai_rejected = []
        success_count = 0 # 🟢 [버그 수정] UnboundLocalError 방지를 위해 스코어를 여기로 이동
        
        global_rag_context = await get_rag_context()
        est_buy_amt = total_asset * 0.02

        for p in python_passed:
            ai_data = extract_ai_essential_data(p['data'].to_dict()) if hasattr(p['data'], 'to_dict') else p['data']
            ai_data['strategy_mode'] = p['mode']
            ai_data['python_pass_score'] = p['score']
            
            ai_data['prev_close'] = p['prev_data'].get('close', '알수없음') if isinstance(p.get('prev_data'), dict) else '알수없음'
            ai_data['realtime_cvd'] = REALTIME_CVD.get(p['t'], 0.0)
            
            ob = await execute_upbit_api(pyupbit.get_orderbook, p['t'])
            if ob and 'total_bid_size' in ob and 'total_ask_size' in ob:
                tb, ta = ob['total_bid_size'], ob['total_ask_size']
                ai_data['ob_imbalance'] = round(ta / tb, 2) if tb > 0 else "알수없음"
            else:
                ai_data['ob_imbalance'] = "알수없음"
                
            exp_slip = await calculate_expected_slippage(p['t'], est_buy_amt)
            mtf_val = p.get('mtf', '알수없음')
            mtf_str_for_buy = mtf_val.get('str', '알수없음') if isinstance(mtf_val, dict) else str(mtf_val)
            exit_preview = get_exit_plan_preview(p['t'], ai_data, eval_mode=p['mode'])
            intent = "상승 추세 중 눌림목 매수 (Pullback)" if p['mode'] == "QUANTUM" else "낙폭 과대 구간 역추세 매매 (Deep Dip)"
            tier = get_coin_tier(p['t'], p['data'])

            ana = await ai_analyze(p['t'], ai_data, mode="BUY", eval_mode=p['mode'], ignore_cooldown=True, mtf_trend=mtf_str_for_buy, market_regime=regime, rag_context=global_rag_context, expected_slippage=round(exp_slip, 2), exit_plan_preview=exit_preview, strategy_intent=intent, coin_tier=tier)
            
            if ana and ana.get('decision') == "BUY":
                ai_approved.append({
                    "t": p['t'], "final_score": ana['score'], "decision": "BUY", 
                    "reason": ana['reason'], "exit_plan": ana['exit_plan'], 
                    "data": p['data'], "mode": p['mode'], "pass_score": p['score']
                })
            elif ana:
                safe_reason = str(ana.get('reason', '사유 없음')).replace('<', '&lt;').replace('>', '&gt;')
                ai_rejected.append({
                    "t": p['t'], 
                    "reason": safe_reason, 
                    "is_system_error": ana.get('system_error', False)
                })

        reject_msg_str = ""
        if ai_rejected:
            reject_msg_str = "\n🚫 <b>[AI 거절 종목]</b>\n"
            for r in ai_rejected:
                reject_msg_str += f"• {r['t']} : {r['reason']}\n"
        
        # 🟢 [추가] 매수할 코인이 있더라도, 면접에서 떨어진 코인이 있다면 미리 브리핑을 쏩니다!
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
                await send_msg(f"🔗 <b>[유사성 필터]</b> 1위({top_coin['t']})와 85% 이상 중복되어 매수 취소: {', '.join(skipped_coins)}")

            # (success_count는 상단에서 이미 0으로 초기화됨)
            for app in final_buy_targets:
                buy_succeeded = await process_buy_order(app['t'], app['final_score'], app['reason'], app['data'], total_asset, cash, len(held_dict), app['exit_plan'], buy_mode=app['mode'], pass_score=app['pass_score'])
                if buy_succeeded:
                    success_count += 1
                    cash -= (total_asset / STRAT.get('max_concurrent_trades', 5))
                    held_dict[app['t']] = 0
        else:
            await send_msg(f"🔍 <b>스캔 결과</b>: ❌ 파이썬 통과 종목 중 AI 승인 종목 없음.{reject_msg_str}")
        
        if is_deep_scan:
            if success_count > 0: consecutive_empty_scans = 0
            else: consecutive_empty_scans += 1

# --- [6. 통합 메인 엔진 및 자산 관리] ---
async def background_scan_task(is_deep):
    try: 
        await run_full_scan(is_deep_scan=is_deep)
    except Exception as e: 
        logging.error(f"⚠️ 백라운드 스캔 에러: {e}")

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

    wr, tc, wc, tp, _,_ = await get_performance_stats_db()
    scan_interval_min = STRAT.get('deep_scan_interval', 900) // 60

    # 🟢 [보고체계 복구 3] 현재 가동 중인 모드(Regime)에 맞는 전략 설정집 가져오기
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

    score_display = f"{int(current_pass_score)}점" if current_pass_score > -900 else "-점 (대기중)"

    # 🟢 [보고체계 복구 4] 활성 지표와 가중치, 작전 지침을 현재 모드(Classic/Quantum)에 맞게 렌더링
    guideline = str(current_strat.get('exit_plan_guideline', '특별한 지침 없음')).replace('<', '&lt;').replace('>', '&gt;')

    indicator_weights_str = ", ".join([f"{k.upper()}: {v}" for k, v in current_strat.get('indicator_weights', {}).items()])
    trend_logic_str = ", ".join(current_strat.get('trend_active_logic', []))
    range_logic_str = ", ".join(current_strat.get('range_active_logic', []))

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
        f"⚙️ <b>통합 엔진 세팅</b>\n"
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
    async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
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
        
        async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
            reported_ids = [r[0] for r in rows]
            placeholders = ','.join('?' for _ in reported_ids)
            await db.execute(f"UPDATE trade_history SET is_reported = 1 WHERE id IN ({placeholders})", reported_ids)
            await db.commit()

        # 🟢 [추가] 자가 학습 (프롬프트 진화) 플로우
        proposals_str = ""
        for r in rows:
            if r[5] and r[5] != '없음':
                proposals_str += f"- [{r[2]} | {r[3]}] 제언: {r[5]}\n"
        
        if proposals_str.strip():
            await send_msg("🧬 <b>AI 자가 학습 시작</b>: 누적된 제언을 분석하여 시스템 프롬프트를 진화시킵니다...")
            
            for e_mode in ["CLASSIC", "QUANTUM"]:
                evolve_res = await ai_analyze("ALL", proposals_str, mode="EVOLVE_PROMPT", eval_mode=e_mode)
                if evolve_res and evolve_res.get('new_guideline'):
                    new_guide = evolve_res['new_guideline']
                    conf = CLASSIC_CONF if e_mode == "CLASSIC" else QUANTUM_CONF
                    conf_path = CLASSIC_CONFIG_PATH if e_mode == "CLASSIC" else CONFIG_PATH
                    old_guide = conf['strategy'].get('exit_plan_guideline', '')
                    
                    # 🟢 변화가 존재할 경우에만 덮어쓰기 실시 및 알림 전송
                    if new_guide and new_guide != old_guide:
                        conf['strategy']['exit_plan_guideline'] = new_guide
                        # 런타임 메모리 즉시 반영 (STRAT 변수 오염 방지)
                        if "Classic" in SYSTEM_STATUS and e_mode == "CLASSIC": STRAT['exit_plan_guideline'] = new_guide
                        if "Quantum" in SYSTEM_STATUS and e_mode == "QUANTUM": STRAT['exit_plan_guideline'] = new_guide
                        
                        await save_config_async(conf, conf_path)
                        await send_msg(f"✨ <b>[{e_mode} 지침 진화 완료]</b>\n- 기존: {old_guide}\n- <b>신규: {new_guide}</b>\n(사유: {evolve_res.get('reason', 'N/A')})")

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
            
            # 🟢 [적용 2] 디버그 모드 역시 단 한 줄로 압축 완료!
            score, fatal_reason, mode = evaluate_coin_fundamental(t, p, c, current_regime_mode, fgi_val, btc_short['trend'])
            return {"t": t, "score": score, "fatal_reason": fatal_reason, "mode": mode}
            
    tasks = [fetch_and_score(t) for t in tickers]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for res in results:
        if isinstance(res, dict):
            score_results.append(res)
            
    score_results.sort(key=lambda x: x['score'], reverse=True)
    
    # 🟢 [추가] 실시간 스코어 현황 발신 시, 보고서용 최고 점수 전역 변수 동기화
    global LATEST_TOP_PASS_SCORE
    non_fatal_scores = [r['score'] for r in score_results if not r.get('fatal_reason')]
    if non_fatal_scores:
        LATEST_TOP_PASS_SCORE = max(non_fatal_scores)
    else:
        LATEST_TOP_PASS_SCORE = 0
    
    msg = f"📊 <b>[디버그] 실시간 종목 점수 (기준: {current_regime_mode})</b>\n\n"
    for i, res in enumerate(score_results[:20]): 
        icon = "🚀" if res['mode'] == "QUANTUM" else "📉"
        fatal_tag = f" 💀({res['fatal_reason']})" if res['fatal_reason'] else ""
        msg += f"{i+1}. {res['t']} : <b>{res['score']:.1f}점</b> ({icon}){fatal_tag}\n"
        
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
                    await ai_self_optimize(eval_mode=eval_mode)
                elif cmd == "시작": is_running = True; await send_msg("🟢 가동")
                elif cmd == "정지": is_running = False; await send_msg("🔴 정지")
                elif cmd == "매수": 
                    # 🟢 [개선] SCAN_LOCK을 직접 체크하여 중복 실행 방지 (동시 실행은 큐에서 대기)
                    await send_msg("🚀 <b>수동 정밀 스캔 가동</b> (방어막 무시)")
                    asyncio.create_task(run_full_scan(is_deep_scan=False))    
                elif cmd == "제안":
                    await send_msg("📁 <b>AI 제언 리포트 생성 중...</b>")
                    asyncio.create_task(generate_daily_proposal())
                # 🟢 [Step 4 핵심: 롤백 명령어 추가]
                elif cmd == "롤백":
                    try:
                        backup_q_path = CONFIG_PATH.replace(".json", "_backup.json")
                        backup_c_path = CLASSIC_CONFIG_PATH.replace(".json", "_backup.json")
                        
                        if os.path.exists(backup_q_path) and os.path.exists(backup_c_path):
                            with open(backup_q_path, 'r', encoding='utf-8') as f: q_back = json.load(f)
                            with open(backup_c_path, 'r', encoding='utf-8') as f: c_back = json.load(f)
                            
                            # 원본 파일 덮어쓰기
                            await save_config_async(q_back, CONFIG_PATH)
                            await save_config_async(c_back, CLASSIC_CONFIG_PATH)
                            
                            # 메모리 상태 즉시 반영
                            global QUANTUM_CONF, CLASSIC_CONF, STRAT
                            QUANTUM_CONF, CLASSIC_CONF = q_back, c_back
                            STRAT = QUANTUM_CONF['strategy'] if "Quantum" in SYSTEM_STATUS else CLASSIC_CONF['strategy']
                            
                            # 🟢 [개선 3-①] 롤백 시 잔여 찌꺼기(캐시) 완전 초기화
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
                        # DB 기록 시 매수 시점의 점수(pass_score)를 찾아 함께 기록합니다.
                        t_data = trade_data.get(t_ticker, {})
                        await record_trade_db(t_ticker, 'SELL', real_p, qty, profit_krw=p_krw, reason="[수동청산]", pass_score=t_data.get('pass_score', 0))
                        
                        last_sell_time[t_ticker] = time.time()
                        sold_count += 1
                        
                    trade_data.clear()
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

# 🟢 [신규 추가] 매도 조건 검사 전용 모듈 (스파게티 코드 분리)
def evaluate_sell_conditions(ticker, t, avg_p, real_price, p_rate, now_ts, current_live_score, ma_live_score):
    global STRAT, INDICATOR_CACHE, TRADE_DATA_DIRTY
    
    # 🟢 [Pylance/Flake8 방어] 변수 초기화 및 타입 안전성 확보
    curr_p_rate = safe_float(p_rate, 0.0)
    curr_ma_score = float(ma_live_score) if ma_live_score is not None else 80.0
    
    eval_mode = t.get('strategy_mode', 'QUANTUM')
    
    # 🟢 [버그 수정] elapsed_sec 등 시간 관련 변수들을 최상단으로 이동 (하단 로직에서 참조 전 정의 필수)
    exit_plan = t.get('exit_plan', {})
    timeout_candles = exit_plan.get('timeout', get_dynamic_strat_value('timeout_candles', mode=eval_mode, default=8))
    interval_str = STRAT.get('interval', 'minute15')
    if interval_str.startswith('minute'):
        interval_sec = int(interval_str.replace('minute', '')) * 60
    elif interval_str == 'day': interval_sec = 86400  
    elif interval_str == 'week': interval_sec = 604800 
    elif interval_str == 'month': interval_sec = 2592000 
    else: interval_sec = 900 
        
    elapsed_sec = now_ts - t.get('buy_ts', now_ts)
    full_timeout_sec = timeout_candles * interval_sec
    half_timeout_sec = full_timeout_sec / 2
    micro_timeout_sec = interval_sec * 1 
    nano_timeout_sec = 180 
    entry_atr = t.get('entry_atr', 0)
    target_atr_multiplier = exit_plan.get('target_atr_multiplier', 4.5)
    
    target_p_price = avg_p + (entry_atr * target_atr_multiplier)
    target_p = ((target_p_price - avg_p) / avg_p) * 100 if avg_p > 0 else 999.0
    hard_s = exit_plan.get('stop_loss', -3.0) 

    current_atr_mult = exit_plan.get('atr_mult', get_dynamic_strat_value('atr_multiplier_for_stoploss', mode=eval_mode, default=1.8))
    
    entry_rsi = t.get('buy_ind', {}).get('rsi', 50)
    if entry_rsi >= 70.0:
        current_atr_mult = min(current_atr_mult, 1.5) 

    invested_high_krw = avg_p * 1.0005
    earned_high_krw = t['high_p'] * 0.9995
    max_p_rate = ((earned_high_krw - invested_high_krw) / invested_high_krw) * 100 if invested_high_krw > 0 else 0
    
    dynamic_mult = current_atr_mult
    if max_p_rate >= 5.0: dynamic_mult = current_atr_mult * 0.3  
    elif max_p_rate >= 3.0: dynamic_mult = current_atr_mult * 0.5
    elif max_p_rate >= 1.0: dynamic_mult = current_atr_mult * 0.7
        
    atr_stop = t['high_p'] - (entry_atr * dynamic_mult)
    chandelier_stop = t['high_p'] * 0.98 if max_p_rate >= 3.0 else 0
    stop_p = max(atr_stop, chandelier_stop)
    
    adaptive_buffer = exit_plan.get('adaptive_breakeven_buffer', 0.003) # 기본 0.3% 버퍼
    
    # 1. 기본 절대 손절선 세팅
    stop_p = max(stop_p, avg_p + (avg_p * (hard_s / 100.0)))
    if entry_atr == 0: stop_p = max(stop_p, avg_p * 0.98) 
    if t.get('is_runner', False): stop_p = max(stop_p, avg_p * 1.007)

    # 2. 🟢 다단계 바닥(Floor) 끌어올리기 (슬리피지 0.2% 흡수용 방어선 상향)
    hard_breakeven_floor = 0
    if max_p_rate >= 1.0:
        t['breakeven_locked'] = True
        hard_breakeven_floor = avg_p * 1.0065  # 최소 0.65% 보장
    elif max_p_rate >= 0.7:
        t['breakeven_locked'] = True
        hard_breakeven_floor = avg_p * 1.0045  # 최소 0.45% 보장
    elif max_p_rate >= 0.4:
        t['breakeven_locked'] = True
        # 🟢 [개선] CLASSIC 모드는 변동성이 작으므로 0.4% 도달 시 즉시 0.25% 지저분한 수익이라도 확정
        floor_pct = 1.0025 if eval_mode == "QUANTUM" else 1.003
        hard_breakeven_floor = avg_p * floor_pct

    # 3. 🟢 대표님 아이디어(꺾이면 팔자) + 촘촘한 샹들리에 추적
    calculated_guard_p = 0
    if t.get('breakeven_locked') or (t.get('guard') and max_p_rate > 0.6): 
        # 수익 구간별로 버퍼(하락 허용치)를 촘촘하게 조입니다.
        if max_p_rate >= 2.0:
            dynamic_buffer = adaptive_buffer * 0.4 
        elif max_p_rate >= 1.0:
            dynamic_buffer = adaptive_buffer * 0.6 
        elif max_p_rate >= 0.6:
            # 🟢 [개선] CLASSIC 모드에서 0.6% 이상 도달 시 '최대 수익의 50% 보존' 규칙 적용
            if eval_mode == "CLASSIC":
                 chandelier_stop = t['high_p'] - ((t['high_p'] - avg_p) * 0.5)
                 # 50% 보존 가격이 기존 계산보다 높으면 그것을 사용
                 calculated_guard_p = max(calculated_guard_p, chandelier_stop)
            dynamic_buffer = adaptive_buffer * 0.8 
        else:
            dynamic_buffer = adaptive_buffer 
            
        calculated_guard_p = max(calculated_guard_p, t['high_p'] * (1 - dynamic_buffer))

    # 4. 최종 트레일링 스탑라인 설정 (기존 스탑, 다단계 바닥, 꺾임 방어선 중 가장 '높은' 가격)
    stop_p = max(stop_p, hard_breakeven_floor, calculated_guard_p)

    # 🟢 [적응형 가드라인] 실시간 점수에 따른 익절/손절 강도(Tightness) 조절
    entry_score = safe_float(t.get('pass_score', 80), 80.0)
    curr_score_val = safe_float(ma_live_score, entry_score)
    
    # 강도(Tightness) 계수 계산: 점수가 높으면 0.8(여유), 낮으면 1.2(타이트)
    # 점수가 entry_score와 같으면 1.0, 최고점(100)이면 0.8, 최하점(0)이면 1.2 지향
    if curr_score_val >= entry_score:
        # 점수가 오를수록 tightness 감소 (최저 0.8)
        score_diff = curr_score_val - entry_score
        max_diff = 100 - entry_score if 100 > entry_score else 1
        tightness = 1.0 - (0.2 * (score_diff / max_diff))
    else:
        # 점수가 내릴수록 tightness 증가 (최고 1.2)
        score_diff = entry_score - curr_score_val
        max_diff = entry_score if entry_score > 0 else 1
        tightness = 1.0 + (0.2 * (score_diff / max_diff))
    
    tightness = max(0.8, min(1.2, tightness))
    
    # 🟢 [적용 1] 익절 가드라인 조절: tightness가 높을수록(1.2) 버퍼가 좁아져서 더 빨리 매도됨
    if calculated_guard_p > 0:
        # stop_p와 high_p 사이의 거리를 tightness에 맞춰 재조절
        original_gap = t['high_p'] - stop_p
        adjusted_gap = original_gap / tightness 
        stop_p = t['high_p'] - adjusted_gap

    # 🟢 [적용 2] 클래식 모드 초기 손절 캡 (tightness 연동하여 가변 적용)
    if eval_mode == "CLASSIC" and elapsed_sec < 300:
        # 기본 -1.5% 캡을 점수가 나쁘면 더 끌어올림 (예: 1.2배 타이트 -> -1.25% 지점에서 컷)
        capped_stop_pct = 1.5 / tightness
        stop_p = max(stop_p, avg_p * (1 - capped_stop_pct / 100.0))

    scale_out_step = t.get('scale_out_step', 0)

    # (시간 관련 변수들은 상단에서 정의됨)

    # 🟢 [버그픽스] Lock 없이 INDICATOR_CACHE 접근 시 에러 방지 (단일 get으로 원자적 참조)
    _ind_snap = INDICATOR_CACHE.get(ticker)
    curr_i_safe = _ind_snap[2] if _ind_snap else {}
    
    is_fundamental_broken = False
    if current_live_score is not None and ma_live_score < get_dynamic_strat_value('sell_score_threshold', mode=eval_mode, default=40):
        atr_1x_pct = (entry_atr / avg_p) * 100 if avg_p > 0 else 1.5
        fundamental_bailout_limit = -max(1.0, min(3.0, atr_1x_pct))
        # 🟢 [개선] 펀더멘털 손상 시에도 '현재 손실 중'이며 일정 시간 지났을 때만 즉각 매도
        if (elapsed_sec > (interval_sec * 2) or p_rate < fundamental_bailout_limit) and curr_p_rate < 0.0:
            is_fundamental_broken = True
    
    macd_diff_val = curr_i_safe.get('macd_h_diff', 0)
    if macd_diff_val is None: macd_diff_val = 0
    
    entry_score = t.get('pass_score', 0)
    
    sell_conditions = [
        (curr_p_rate >= (target_p * 1.5) and curr_i_safe.get('rsi', 50) >= 85 and scale_out_step == 0, "추세 과열 1차 익절 (RSI > 85)", 0.3, 1, "NORMAL"),
        (curr_p_rate >= (target_p * 2.5) and scale_out_step <= 1, "목표 수익 돌파 2차 익절", 0.5, 2, "NORMAL"),
        (curr_p_rate <= hard_s, "절대 손절선 이탈", 1.0, 0, "HIGH"),
        (real_price <= stop_p, "트레일링 스탑 이탈 (수익 보존/손절)", 1.0, 0, "HIGH"),
        
        # 🟢 [개선] V자 반등 실패 시 손절 한도를 ATR에 연동 (변동성 큰 종목은 더 넉넉히 대기)
        (elapsed_sec > nano_timeout_sec and max_p_rate < 0.2 and curr_p_rate <= -max(1.0, (entry_atr/avg_p)*100*0.8 if avg_p>0 else 1.2), f"⚡ V자 반등 실패 (투매 지속 즉각 컷)", 1.0, 0, "HIGH"),
        
        # 🟢 (수정) 3분(nano_timeout) 유예, 25점 폭락, 그리고 '현재 마이너스 손실 중일 때'만 발동 (수익 중일 땐 끝까지 버팀!)
        (elapsed_sec > nano_timeout_sec and curr_ma_score > 0 and (entry_score - curr_ma_score) >= 25 and curr_p_rate < 0.0, f"점수 급락 탈출 ({entry_score} ➡️ {curr_ma_score})", 1.0, 0, "HIGH"),

        (is_fundamental_broken, f"모멘텀 붕괴 ({ma_live_score}점)", 1.0, 0, "HIGH"),
        (elapsed_sec > full_timeout_sec and curr_p_rate <= 0.5, f"추세 정체 타임아웃 ({timeout_candles}캔들)", 1.0, 0, "NORMAL"),
        (elapsed_sec > half_timeout_sec and curr_p_rate < 0.0 and (macd_diff_val < 0 or curr_ma_score < 60), "⏳ 조기 타임아웃 (돌파 동력 상실)", 1.0, 0, "HIGH"),                        
        # 🟢 [개선] 15분(micro_timeout) 경과 후 수익권이 아닐 경우(0.1% 미만) 즉각 청산 (자금 회전율 최적화)
        (elapsed_sec > micro_timeout_sec and curr_p_rate < 0.1, "⏳ 중립 타임아웃 (반등 정체/횡보)", 1.0, 0, "NORMAL"),
        
        (elapsed_sec > micro_timeout_sec and curr_p_rate <= -1.0, "⏳ 가짜 돌파 컷 (즉각 탈출)", 1.0, 0, "HIGH"),
        (elapsed_sec > micro_timeout_sec and curr_p_rate <= -0.5 and macd_diff_val < 0, "⏳ 모멘텀 역전 컷 (돌파 실패)", 1.0, 0, "HIGH")
    ]

    for condition, reason, ratio, step, urgency_level in sell_conditions:
        if condition:
            # 조건 만족 시: is_sell, is_partial_sell, sell_qty_ratio, sell_reason_str, urgency, next_step
            return True, (ratio != 1.0), ratio, reason, urgency_level, step
            
    return False, False, 1.0, "", "NORMAL", scale_out_step

# 🟢 [수술 완료] 메인 감시 루프의 딜레이를 없애기 위한 백그라운드 매도 리포트 생성기
async def background_sell_report(ticker, real_price, sell_qty, p_krw, p_rate, sell_reason_str, analyze_payload):
    try:
        eval_mode = analyze_payload.get('strategy_mode', 'QUANTUM')
        # AI 분석을 메인 루프 밖에서 여유롭게 진행
        ai_r = await ai_analyze(ticker, analyze_payload, mode="SELL_REASON", eval_mode=eval_mode, ignore_cooldown=True) # 통합 엔진 AI 분석
        
        ai_rating = ai_r.get('rating', 0) if isinstance(ai_r, dict) else 0
        ai_status = ai_r.get('status', 'UNKNOWN') if isinstance(ai_r, dict) else 'UNKNOWN'
        ai_msg = str(ai_r.get('reason', str(ai_r))).replace('<', '&lt;').replace('>', '&gt;') if isinstance(ai_r, dict) else str(ai_r)
        
        ai_improvement = str(ai_r.get('improvement', '없음')).replace('<', '&lt;').replace('>', '&gt;') if isinstance(ai_r, dict) else '없음'
        
        # DB 저장 (매수 당시의 점수 pass_score를 유지)
        await record_trade_db(ticker, 'SELL', real_price, sell_qty, profit_krw=p_krw, reason=f"[{sell_reason_str}] {ai_msg}", status=ai_status, rating=ai_rating, improvement=ai_improvement, pass_score=analyze_payload.get('pass_score', 0))
        
        # 텔레그램 발송
        telegram_message = f"🔕 <b>최종 청산 완료</b> ({ticker})\n- 상태: {ai_status} ({ai_rating}점)\n- 사유: {sell_reason_str}\n- 수익률: {p_rate:+.2f}%\n- 수익금: {p_krw:,.0f}원\n- AI: {ai_msg}"
        if ai_improvement and ai_improvement != '없음': 
            telegram_message += f"\n\n💡 <b>제언</b>: {ai_improvement}"
            
        await send_msg(telegram_message)
    except Exception as e:
        logging.error(f"백그라운드 매도 리포트 에러 ({ticker}): {e}")
        # 🟢 [보고체계 복구 1] AI 통신 실패 시에도 매도 사실을 반드시 DB와 텔레그램에 남깁니다!
        await record_trade_db(ticker, 'SELL', real_price, sell_qty, profit_krw=p_krw, reason=f"[{sell_reason_str}] AI 통신 지연", status="ERROR_FALLBACK", rating=50, pass_score=analyze_payload.get('pass_score', 0))
        await send_msg(f"🔕 <b>최종 청산 완료 (비상 모드)</b> ({ticker})\n- 사유: {sell_reason_str}\n- 수익률: {p_rate:+.2f}%\n- 수익금: {p_krw:,.0f}원\n- AI: 구글 서버 지연으로 사후 분석 생략")

# 🟢 [Step 4 핵심: 시스템 헬스 체크 (Watchdog)]
# 메인 루프나 웹소켓이 모종의 이유로 멈추면 텔레그램으로 즉시 비상 알림을 보냅니다.
last_main_loop_time = time.time()

async def system_watchdog():
    global API_FATAL_ERRORS, last_main_loop_time
    await asyncio.sleep(60) # 봇 초기화 대기
    
    while True:
        try:
            await asyncio.sleep(60)
            now = time.time()
            
            # 🟢 [개선 3-②] 워치독 알림 3단계 세분화
            # Level 3 (치명)
            if API_FATAL_ERRORS >= 3:
                await send_msg(f"🚨 <b>[FATAL] API 호출 연속 실패!</b>\n누적 치명적 오류가 {API_FATAL_ERRORS}회 발생했습니다. 계정 권한이나 네트워크를 확인하세요.")
                API_FATAL_ERRORS = 0 # 알람 후 초기화
                
            # Level 2 (심각)
            elapsed_loop = now - last_main_loop_time
            if elapsed_loop > 180: 
                await send_msg(f"🔥 <b>[CRITICAL] 메인 엔진 정지 감지!</b>\n마지막 심장 박동 후 {int(elapsed_loop)}초가 경과했습니다. 즉시 서버 확인 요망.")
                last_main_loop_time = now 
                
            # Level 1 (경고)
            dead_tickers = [t for t, ts in REALTIME_PRICES_TS.items() if now - ts > 60]
            if len(dead_tickers) > 15:
                await send_msg(f"⚠️ <b>[WARNING] 네트워크 지연 감지</b>\n{len(dead_tickers)}개 종목의 실시간 데이터 수신이 1분 이상 끊겼습니다. (WebSocket 재구독 시도 중)")
                for dt in dead_tickers: REALTIME_PRICES_TS[dt] = now 
                
        except Exception as e:
            logging.error(f"Watchdog 에러: {e}")

async def main():
    # 🟢 [수정 완료] 전역 변수 참조 안정성 확보 (Pylance/Flake8 방어)
    global trade_data, BALANCE_CACHE, last_sell_time, is_running, last_global_buy_time, last_deep_scan_ts
    global TRADE_DATA_DIRTY, SYSTEM_STATUS, REALTIME_PRICES, REALTIME_PRICES_TS, INDICATOR_CACHE
    global API_FATAL_ERRORS, last_main_loop_time

    global instance_lock
    
    try:
        instance_lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        instance_lock.bind(('127.0.0.1', 65433)) # 통합 봇은 65433 포트를 사용하여 중복 실행을 방지합니다.
    except OSError:  # 🟢 [Pylance 방어] socket.error는 deprecated될 수 있으므로 표준 OSError로 교체
        logging.error("❌ 이미 ATS_Hybrid 봇이 실행 중입니다. 중복 실행을 방지하기 위해 즉시 종료합니다.")
        return # 이미 포트가 잠겨있다면 조용히 프로그램을 종료!
    
    # 🟢 API 호출 제한 분산 (Jitter): 다른 엔진과 동시에 시작되는 것을 방지하기 위해 1~10초 사이 랜덤 대기
    startup_jitter = random.uniform(1.0, 10.0)
    logging.info(f"🚀 API 병목 방지를 위해 {startup_jitter:.2f}초 후 엔진 가동을 시작합니다...")
    await asyncio.sleep(startup_jitter)

    asyncio.create_task(handle_telegram_updates())
    await asyncio.sleep(0.1) 
    
    # 🟢 [추가] 초기 시장 레짐 감지 및 시스템 상태 업데이트
    btc_short_initial = await get_btc_short_term_data()
    regime_initial = await get_market_regime()
    fgi_str_initial = regime_initial.get('fear_and_greed', '')
    try: fgi_val_initial = int(re.search(r'\d+', fgi_str_initial).group()) if re.search(r'\d+', fgi_str_initial) else 50
    except: fgi_val_initial = 50

    global SYSTEM_STATUS
    if fgi_val_initial <= 35 or (btc_short_initial['trend'] == "단기 하락" and fgi_val_initial <= 50):
        SYSTEM_STATUS = "📉 Classic (Deep Dip Sniper)"
    elif fgi_val_initial >= 65 or (btc_short_initial['trend'] == "단기 상승" and fgi_val_initial >= 50):
        SYSTEM_STATUS = "🚀 Quantum (Trend Breakout)"
    else:
        SYSTEM_STATUS = "⚖️ Hybrid (Adaptive Monitoring)"

    logging.info(f"ATS 통합 엔진 시작 ({SYSTEM_STATUS} 모드)")
    await send_msg(f"⚔️ <b>ATS_Hybrid 가동 시작</b> ({SYSTEM_STATUS} 모드)\n\n{COMMAND_HELP_MSG}")

    await init_db()
    trade_data = await load_trade_status_db()
    asyncio.create_task(websocket_ticker_task())
    asyncio.create_task(system_watchdog()) # 🟢 워치독 실행!
    asyncio.create_task(run_fastapi_server()) # 🟢 대시보드 서버 융합

    last_report_time = time.time()

    last_loss_check_time = time.time()
    last_checked_win_rate = 100.0
    last_daily_report_day = datetime.now().day
    last_proposal_day = None
    
    # 🟢 [정비] 전역 변수 초기화는 파일 상단(L1255) 및 main() 시작점(L3090)에서 완료됨
        

    async with aiosqlite.connect(DB_FILE, timeout=20.0) as db:
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
                
                # 🟢 [입양 로직 개선] 현재 시장 상황에 맞춰 strategy_mode 결정
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
    asyncio.create_task(background_scan_task(True)) # 🟢 [수정] 프로그램 시작 시 바로 딥 스캔 시작
    last_global_buy_time = time.time() # 🟢 [버그 픽스] 중복 스캔 방지를 위해 시작 시점을 현재로 리셋
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
            last_main_loop_time = now_ts # 🟢 메인 루프가 정상적으로 돌고 있음을 워치독에 보고 (심장 박동)
            
            
            if now_ts - BALANCE_CACHE['timestamp'] > BALANCE_CACHE_SEC: 
                BALANCE_CACHE['data'] = await execute_upbit_api(upbit.get_balances)
                BALANCE_CACHE['timestamp'] = now_ts
                
            balances = BALANCE_CACHE['data']
            if not balances or not isinstance(balances, list): 
                await asyncio.sleep(1.0)
                continue

            # 🟢 [Pylance 방어] cash 안전 추출
            
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

            # 🟢 [추가] 반복문을 돌기 전에 현재 시장의 날씨(Regime)를 딱 한 번만 파악합니다! (속도 대폭 향상)
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

            # 이제 개별 코인 검사를 시작합니다.
            for ticker in monitoring_tickers:
                current_live_score = None
                if ticker not in held and ticker in last_sell_time and (now_ts - last_sell_time.get(ticker, 0)) < 1800: 
                    continue                    

                if ticker in held:
                    # 🟢 [수정 완료] 15초에 한 번만 지표를 갱신하도록 쿨타임 적용
                    t = trade_data.get(ticker, {})
                    if now_ts - t.get('last_ind_update_ts', 0) > 15:
                        asyncio.create_task(get_indicators(ticker))
                        t['last_ind_update_ts'] = now_ts
                        TRADE_DATA_DIRTY = True
                    
                    coin = held[ticker]
                    # 🟢 [Pylance 추가 방어] coin 딕셔너리에서 평단가를 꺼낼 때도 정수기(safe_float)를 통과시킵니다.
                    avg_p = safe_float(coin.get('avg_buy_price'))
                    
                    real_price = REALTIME_PRICES.get(ticker)
                    last_update = REALTIME_PRICES_TS.get(ticker, 0)
                    
                    # 🟢 [좀비 방어막 가동] 데이터가 아예 없거나, 15초 이상 갱신이 멈췄다면?
                    if not real_price or (time.time() - last_update > 15):
                        # 웹소켓이 죽었거나 해당 코인 거래가 멈춘 것이므로, REST API로 심폐소생(직접 조회)
                        real_price = safe_float(await execute_upbit_api(pyupbit.get_current_price, ticker))
                        REALTIME_PRICES[ticker] = real_price  # 가져온 싱싱한 가격으로 덮어쓰기
                        REALTIME_PRICES_TS[ticker] = time.time()  # 시간도 갱신
                        
                    if not real_price: continue
                    
                    invested_krw_unit = avg_p * 1.0005
                    earned_krw_unit = real_price * 0.9995
                    p_rate = ((earned_krw_unit - invested_krw_unit) / invested_krw_unit) * 100 if invested_krw_unit > 0 else 0.0

                    if ticker not in trade_data:
                        continue
                    
                    t = trade_data[ticker]
                    eval_mode = t.get('strategy_mode', 'QUANTUM') # 매수 당시의 전략 모드 확인
                    changed = False

                    if real_price > t.get('high_p', real_price): t['high_p'] = real_price; changed = True
                    if int(p_rate) >= 1 and int(p_rate) > t.get('last_notified_step', 0): await send_msg(f"📈 {ticker} 랠리! {p_rate:+.2f}%"); t['last_notified_step'] = int(p_rate); changed = True
                    
                    current_live_score = None
                    # 🟢 [버그픽스] 루프 도중 캐시 삭제로 인한 KeyError 방지
                    _ind_snap = INDICATOR_CACHE.get(ticker)
                    if _ind_snap:
                        prev_i, curr_i = _ind_snap[1], _ind_snap[2]
                        
                        if isinstance(prev_i, pd.Series): prev_i = prev_i.to_dict()
                        if isinstance(curr_i, pd.Series): curr_i = curr_i.to_dict()
                        
                        if isinstance(prev_i, dict) and isinstance(curr_i, dict):
                            btc_short_trend = btc_short.get('trend', "혼조세")
                            # 🟢 [수정 완료] 코인에 내재된 eval_mode를 강제로 주입하여 잣대의 일관성 유지!
                            current_live_score, _, _ = evaluate_coin_fundamental(ticker, prev_i, curr_i, current_regime_mode, fgi_val, btc_short_trend, force_eval_mode=eval_mode)
                    ma_live_score = current_live_score # 기본값
                    if current_live_score is not None:
                        score_hist = t.get('score_history', [])
                        score_hist.append(current_live_score)
                        # 🟢 최근 30번의 틱(약 1분 분량) 유지하여 노이즈 제거 및 안정성 확보
                        if len(score_hist) > 30: 
                            score_hist.pop(0)
                        t['score_history'] = score_hist
                        
                        # 리스트의 평균값 계산 (소수점 1자리까지)
                        ma_live_score = round(sum(score_hist) / len(score_hist), 1)
                    
                    # 🟢 (이후 기존 방어 로직 계속)
                    if p_rate > 0.6 and current_live_score is not None and ma_live_score < get_dynamic_strat_value('guard_score_threshold', mode=eval_mode, default=60):
                        if not t.get('guard', False):
                            t['guard'] = True
                            changed = True
                            await send_msg(f"🛡️ <b>[펀더멘탈 둔화 방어]</b> {ticker} 평균 점수 하락({ma_live_score}점)! 즉시 본절 방어선 가동.")
                    
                    if changed: TRADE_DATA_DIRTY = True

                    # 🟢 [수술 완료] 약 100줄의 매도 판별 스파게티 코드를 모듈화하여 단 3줄로 종결!
                    is_sell, is_partial_sell, sell_qty_ratio, sell_reason_str, urgency, next_step = evaluate_sell_conditions(
                        ticker, t, avg_p, real_price, p_rate, now_ts, current_live_score, ma_live_score
                    )

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
                        if is_partial_sell:
                            sell_qty = math.floor((qty * sell_qty_ratio) * 1e8) / 1e8
                        else:
                            sell_qty = qty
                        
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
                            # 분할 매도 시에도 매수 당시의 점수를 정확히 인계합니다.
                            await record_trade_db(ticker, 'SELL', real_price, sell_qty, profit_krw=p_krw, reason=f"[{sell_reason_str}]", status="PARTIAL_SUCCESS", rating=80, pass_score=t.get('pass_score', 0))
                            await send_msg(f"💸 <b>{next_step}차 분할 익절</b> ({ticker})\n- 수익률: {p_rate:+.2f}%\n- 수익금: {p_krw:,.0f}원")
                            continue

                        _, curr = await get_indicators(ticker)
                        btc_sell_p = REALTIME_PRICES.get('KRW-BTC', 0)
                        btc_buy_p = t.get('btc_buy_price', btc_sell_p)
                        btc_change = ((btc_sell_p - btc_buy_p) / btc_buy_p * 100) if btc_buy_p > 0 else 0
                        
                        elapsed_sec = now_ts - t.get('buy_ts', now_ts)
                        
                        # 🟢 [해결 완료] 현재 코인의 데이터를 바탕으로 max_p_rate를 즉석에서 안전하게 재계산합니다!
                        invested_high_krw = avg_p * 1.0005
                        earned_high_krw = t.get('high_p', avg_p) * 0.9995
                        max_p_rate_local = ((earned_high_krw - invested_high_krw) / invested_high_krw) * 100 if invested_high_krw > 0 else 0.0
                        
                        analyze_payload = {
                            'p_rate': round(p_rate, 2), 'buy_ind': t.get('buy_ind'), 'sell_ind': curr.to_dict() if curr is not None else {},
                            'actual_sell_reason': sell_reason_str, 'original_buy_reason': t.get('buy_reason', ''), 'original_exit_plan': t.get('exit_plan', {}),
                            'btc_buy_price': btc_buy_p, 'btc_sell_price': btc_sell_p, 'btc_change': round(btc_change, 2),
                            'strategy_mode': t.get('strategy_mode', 'QUANTUM'),
                            'max_p_rate': round(max_p_rate_local, 2), # 🟢 즉석에서 구한 값을 매칭!
                            'elapsed_min': int(elapsed_sec / 60),
                            'pass_score': t.get('pass_score', 0) # 🟢 매수 시점 점수 인계
                        }
                        
                        last_sell_time[ticker] = now_ts
                        del trade_data[ticker]
                        TRADE_DATA_DIRTY = True
                        
                        # 2. AI 반성문과 텔레그램 발송은 백그라운드 태스크로 던져버림 (Fire and Forget)
                        # 🟢 파이썬 클로저 버그 방지: 선언하는 순간의 값을 매개변수(t, rp 등)로 꽉 잡아둡니다.
                        async def delayed_report_wrap(t=ticker, rp=real_price, sq=sell_qty, pk=p_krw, pr=p_rate, sr=sell_reason_str, ap=analyze_payload):
                            try:
                                await asyncio.wait_for(background_sell_report(ticker=t, real_price=rp, sell_qty=sq, p_krw=pk, p_rate=pr, sell_reason_str=sr, analyze_payload=ap), timeout=120.0)
                            except Exception as e:
                                logging.error(f"[{t}] 백그라운드 리포트 태스크 타임아웃/에러: {e}")

                        task = asyncio.create_task(delayed_report_wrap())
                        background_tasks.add(task)
                        task.add_done_callback(background_tasks.discard)
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
                
                # 🟢 무한 누적 방지: 당일 세력 매집 흐름 파악을 위한 실시간 CVD 초기화
                global REALTIME_CVD
                REALTIME_CVD.clear()
            
            # 3. 일일 AI 제안 파일 생성 (매일 오전 9시)
            if now_dt.hour == 9 and now_dt.minute == 0 and now_dt.day != last_proposal_day:
                asyncio.create_task(generate_daily_proposal()) 
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
                        regime = await get_market_regime()
                        btc_short = await get_btc_short_term_data()
                        fgi_str = regime.get('fear_and_greed', '')
                        fgi_val = int(re.search(r'\d+', fgi_str).group()) if re.search(r'\d+', fgi_str) else 50
                        if fgi_val <= 35 or (btc_short['trend'] == "단기 하락" and fgi_val <= 50):
                            eval_mode = "CLASSIC"
                        else:
                            eval_mode = "QUANTUM"
                        await ai_self_optimize(trigger="auto", eval_mode=eval_mode) # 통합 전략 자동 최적화
                        # 통합 엔진은 hybrid self-optimize를 사용합니다.
                        
                    # 현재 승률을 \'이전 승률\'로 덮어씌워 다음 4시간 뒤에 비교할 수 있게 함
                    last_checked_win_rate = wr
                except Exception as e:
                    logging.error(f"승률 기반 최적화 로직 오류: {e}")
            
            # 5-A. 🚨 BTC 급등 감지 시 비정규 딥스캔 즉시 실행 (웹소켓 트리거 확인)
            global BTC_SURGE_TRIGGERED
            if BTC_SURGE_TRIGGERED and is_running:
                BTC_SURGE_TRIGGERED = False
                await send_msg("🚨 <b>BTC 급등 포착!</b> 알트코인 연동 상승 기회를 즉시 탐색합니다.")
                asyncio.create_task(run_full_scan(is_deep_scan=True))
                # 스캔 중이더라도 플래그는 리셋하여 중복 트리거 방지 (SCAN_LOCK이 순차 처리 보장)

            # 5. 딥 스캔 실행 조건
            if is_running and (now_ts - last_deep_scan_ts >= STRAT.get("deep_scan_interval", 900)):
                # SCAN_LOCK이 종료 후 자동 실행(Wait)하므로 별도 상태 체크 없이 태스크 던짐
                asyncio.create_task(run_full_scan(is_deep_scan=True))
                last_deep_scan_ts = now_ts
                
            await asyncio.sleep(0.5) 
            
        except Exception:
            logging.error(f"❗ 통합 메인 루프 예외 발생: {traceback.format_exc()}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("\n🛑 봇이 종료되었습니다.")
    except Exception:
        logging.error(f"\n❌ 실행 중 치명적 오류:\n{traceback.format_exc()}")
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        print(f"로그 파일 저장됨: {log_filepath}")
