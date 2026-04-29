# strategy_logic.py
# 모든 전략 로직의 중앙 저장소 (ATS_Xeon, Backtest, Optimizer 공통)
# "True Elite" 전략 기반

import os
import sys
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# [최적화] PyPy 환경을 위해 Pandas 및 Pandas-TA 선택적 로드
try:
    import pandas as pd
    import pandas_ta as ta # noqa: F401
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    # Pandas가 없는 환경(PyPy)을 위한 더미 클래스 정의 (타입 힌트 오류 방지)
    class DummyPandas:
        class DataFrame: pass
        class Series: pass
    pd = DummyPandas()
    ta = Any # Dummy

import numpy as np

# [최적화] Numba @njit 대체용 더미 데코레이터
def njit(func=None, **kwargs):
    if func is None:
        return lambda f: f
    return func
def prange(start, stop=None, step=1):
    return range(start, stop if stop is not None else start, step)

@dataclass
class ScoringParams:
    foundation_mult_q:   float = 0.5
    foundation_mult_c:   float = 3.684
    sniper_boost:        float = 0.016
    mtf_bonus_q:         float = 0.0
    mtf_penalty_q:       float = 0.0
    wick_penalty:        float = 108.115
    wick_ratio_major:    float = 0.641
    wick_ratio_meme:     float = 1.715
    bb_breakout_bonus:   float = 80.422
    sma_align_bonus:     float = 59.2
    rsi_oversold_bonus:  float = 0.0
    sma_gap_bonus:       float = 0.0
    cvd_bonus:           float = 0.0
    osc_conv_bonus_alt:  float = 46.195
    osc_conv_bonus_maj:  float = 27.696
    sma_above_bonus:     float = 30.255
    squeeze_bonus_alt:   float = 83.595
    squeeze_bonus_maj:   float = 0.0
    st_psar_bonus:       float = 3.353
    mid_sma_penalty:     float = 32.793
    rsi_slope_penalty:   float = 0.0
    divergence_penalty:  float = 102.205
    fgi_bonus_dampen:    float = 0.259
    vas_mult_major:      float = 1.0
    vas_mult_mid:        float = 8.0
    alt_accel_mult:      float = 2.621
    rsi_overbought_mult: float = 0.571
    macd_negative_mult:  float = 3.937
    major_weak_mult:     float = 3.009
    meme_bad_mult:       float = 3.838
    w_zscore:        float = 0.747
    w_macd:          float = 0.0
    w_rsi:           float = 0.763
    w_volume:        float = 9.932
    w_st:            float = 0.0
    w_bb:            float = 0.357
    w_vwap:          float = 0.0
    w_ssl:           float = 2.032
    w_sma:           float = 0.0
    w_ichimoku:      float = 15.0
    w_obv:           float = 0.0
    w_stoch:         float = 1.0
    w_bb_break:      float = 1.0
    pass_score_threshold: float = 83.586
    rsi_high_thr:         float = 50.0
    rsi_low_thr:          float = 5.0
    sniper_confluence_bonus: float = 137.68
    tp_atr_mult:             float = 0.5
    sl_atr_mult:             float = 0.5
    step_up_l1_atr:          float = 4.424
    step_up_l2_atr:          float = 10.896
    vol_adj_mult_high:       float = 2.693
    vol_adj_mult_low:        float = 0.53
    vol_multiple_small:    float = 1.5
    vol_multiple_mid:      float = 1.691
    vol_multiple_major:    float = 2.413
    cvd_penalty_q:         float = 186.787
    cvd_penalty_c:         float = 207.024
    cvd_slope_penalty_c:   float = 0.0
    vol_ratio_penalty_c:   float = 236.148
    vol_idx_limit:         float = 0.3
    bb_bw_limit:           float = 0.5
    btc_drop_pct:          float = 0.005

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}

    def update_from_dict(self, d: dict):
        for k, v in d.items():
            if hasattr(self, k):
                try:
                    setattr(self, k, float(v))
                except: pass

# ── 최적화 파라미터 로드 ──────────────────────────────────────────────────────────
OPTIMIZED_PARAMS = ScoringParams()
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
OPT_PATH = os.path.join(BASE_PATH, "config_optimized.json")

if os.path.exists(OPT_PATH):
    try:
        import json as _json
        with open(OPT_PATH, "r", encoding="utf-8") as _f:
            _loaded = _json.load(_f)
            if _loaded:
                OPTIMIZED_PARAMS.update_from_dict(_loaded)
                print(f"  [System] {os.path.basename(OPT_PATH)} 로드 완료. 파라미터가 실시간 동기화되었습니다.")
    except Exception as _e:
        print(f"  [ERR-LoadOpt] {os.path.basename(OPT_PATH)} 로드 실패: {_e}")

GLOBAL_COMMISSION     = 0.0005
GLOBAL_MAX_POSITIONS  = 10
GLOBAL_RISK_PER_TRADE = 0.015

def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None: return float(default)
    try: return float(val)
    except: return float(default)

def get_coin_tier(ticker: str, curr_i: dict) -> str:
    try:
        close_val = safe_float(curr_i.get('close'))
        atr_val   = safe_float(curr_i.get('ATR') or curr_i.get('atr'))
        if close_val <= 0: return "Major"
        vol_idx = (atr_val / close_val) * 100
        if vol_idx > 3.5: return "Small"
        elif vol_idx > 1.5: return "Mid"
        return "Major"
    except: return "Major"

def get_upbit_tick_size(price: float) -> float:
    if price >= 2_000_000: return 1000.0
    elif price >= 1_000_000: return 500.0
    elif price >= 500_000:   return 100.0
    elif price >= 100_000:   return 50.0
    elif price >= 10_000:    return 10.0
    elif price >= 1_000:     return 1.0
    elif price >= 100:       return 0.1
    elif price >= 10:        return 0.01
    elif price >= 1:         return 0.001
    else:                    return 0.0001

def calculate_optimized_buy_amt(equity, cash, atr_pct):
    risk_based_amt = equity * GLOBAL_RISK_PER_TRADE / (max(0.5, atr_pct) / 100)
    equal_weight_cap = (equity / GLOBAL_MAX_POSITIONS) * 1.2
    cash_cap = cash * 0.98
    buy_amt = min(risk_based_amt, equal_weight_cap, cash_cap)
    return max(0, buy_amt)

def get_coin_tier_params(ticker, curr_i, strat_config=None):
    tier = get_coin_tier(ticker, curr_i)
    if not strat_config: return {}
    if tier == "Small": return strat_config.get('high_vol_params', {})
    elif tier == "Mid": return strat_config.get('mid_vol_params', {})
    return strat_config.get('major_params', {})

def clamp_value(val, min_v, max_v, default=0.0):
    v = safe_float(val, default)
    return max(min_v, min(v, max_v))

def get_constrained_value(key, p_dict, mode="QUANTUM"):
    if hasattr(p_dict, key): return getattr(p_dict, key, 0.0)
    if isinstance(p_dict, dict): return p_dict.get(key, 0.0)
    return 0.0

def _calculate_ta_indicators_sync(df: pd.DataFrame, btc_df: pd.DataFrame = None, strat_params: dict = None) -> pd.DataFrame:
    if df is None or len(df) < 50: return df
    p = strat_params or {}
    df['ATR'] = df.ta.atr(length=p.get('atr_len', 14))
    st = df.ta.supertrend(length=p.get('st_len', 20), multiplier=p.get('st_mult', 3.0))
    if st is not None: df['ST_DIR'] = st.iloc[:, 1]
    df['ema20'] = df.ta.ema(length=20)
    df['ema60'] = df.ta.ema(length=60)
    df['sma_short'] = df.ta.sma(length=5)
    df['sma_50'] = df.ta.sma(length=50)
    df['std_50'] = df['close'].rolling(window=50).std()
    df['z_score'] = (df['close'] - df['sma_50']) / (df['std_50'] + 0.0001)
    df['vwap'] = df.ta.vwap()
    df['vol_sma'] = df['volume'].rolling(window=20).mean()
    hl = (df['high'] - df['low']).replace(0, 0.00001)
    df['vol_delta'] = df['volume'] * ((df['close'] - df['low']) / hl) - df['volume'] * ((df['high'] - df['close']) / hl)
    df['cvd'] = df['vol_delta'].rolling(window=20).sum()
    df['obv'] = df.ta.obv()
    df['rsi'] = df.ta.rsi(length=14)
    macd = df.ta.macd()
    if macd is not None:
        df['macd_h'] = macd.iloc[:, 1]
        df['macd_h_diff'] = df['macd_h'].diff()
        df['macd_h_diff_sma'] = df['macd_h_diff'].abs().rolling(window=10).mean()
    bb = df.ta.bbands(length=20, std=2)
    if bb is not None: df['bb_l'], df['bb_u'], df['bb_bw'] = bb.iloc[:, 0], bb.iloc[:, 2], bb.iloc[:, 3]
    df['sma_long'] = df['close'].rolling(window=20).mean()
    if btc_df is not None: df['btc_close'] = btc_df['close'].reindex(df.index, method='ffill')
    return df

def calculate_grad(v, t, w2, md='DECREASE'):
    df = abs(v - t)
    if md == 'DECREASE': return 1.0 - (df/w2) if t < v < t+w2 else (1.0 if v <= t else 0.0)
    return 1.0 - (df/w2) if t-w2 < v < t else (1.0 if v >= t else 0.0)

def get_strategy_score(name: str, prev: dict, curr: dict, price: float, mode: str = "QUANTUM") -> float:
    try:
        is_q = (mode == "QUANTUM")
        def calc_dist(v, b, w=15.0, inv=False):
            if b <= 0: return 25.0
            d = ((v - b) / b) * 100
            m = d * w if not inv else -d * w
            s = 50.0 + (35.0 * (m / (m + 15.0))) if m > 0 else 50.0 + m
            return min(100.0, max(15.0, s))

        if name == "rsi":
            r = safe_float(curr.get('rsi'), 50.0)
            if is_q:
                if 50 <= r <= 65: return 100.0
                if r > 85: return 30.0
                return max(0.0, r - 10)
            b = min(100.0, max(0.0, (50.0-r)*3.0 + 60))
            if r > safe_float(prev.get('rsi'), r) and r < 45: return min(100.0, b+15.0)
            return b
        if name == "bollinger":
            u, l = safe_float(curr.get('bb_u'), 1), safe_float(curr.get('bb_l'), 0)
            p = (price - l) / max(1e-9, u - l)
            if is_q: return min(100.0, max(0.0, p * 100))
            b = min(100.0, max(0.0, 110.0 - (p * 60)))
            if safe_float(prev.get('close'), price) < safe_float(prev.get('bb_l'), 0) and price > l: return min(100.0, b+35.0)
            return b
        if name == "z_score":
            z = safe_float(curr.get('z_score'), 0.0)
            if is_q: return min(100.0, max(0.0, 95.0 - (abs(z-0.5)*25)))
            return min(100.0, max(0.0, 75.0 + (z*-25.0)))
        if name == "macd":
            h, d = safe_float(curr.get('macd_h'), 0.0), safe_float(curr.get('macd_h_diff'), 0.0)
            if is_q:
                base = 65.0 if h > 0 else 0.0
                accel = min(1.0, d*5.0)*35.0 if d > 0 else 0.0
                return min(100.0, base + accel)
            if d > 0:
                sma2 = max(safe_float(curr.get('macd_h_diff_sma'), 0.0001)*2, 1e-9)
                return min(100.0, max(50.0, (d / sma2)*100))
            return 30.0
        if name == "volume":
            v, s = safe_float(curr.get('volume')), safe_float(curr.get('vol_sma'), 0.0001)
            base = min(100.0, (v/(s+1))*(50 if is_q else 30) + (0 if is_q else 30))
            if is_q and v > s*1.5: return min(100.0, base+20.0)
            return base
        if name == "vwap": return calc_dist(price, curr.get('vwap', price), inv=(not is_q))
        if name == "ssl_channel": return calc_dist(price, curr.get('ssl_up', price), inv=(not is_q))
        if name == "sma_crossover":
            l, s = safe_float(curr.get('sma_long', curr.get('ema60', 1e-9))), safe_float(curr.get('sma_short', curr.get('ema20', 1e-9)))
            if not is_q: return min(100.0, max(0.0, 50.0 - (((price-l)/l)*600)))
            if price > l: return min(100.0, 75.0+(((s-l)/l)*1500))
            return 50.0 if price > l else 0.0
        if name == "ichimoku":
            sa, sb = safe_float(curr.get('span_a'), 0), safe_float(curr.get('span_b'), 0)
            if sa==0 or sb==0: return 50.0
            if price > max(sa, sb): return 100.0
            if price < min(sa, sb): return 0.0
            return 50.0
        if name == "stochastics":
            k, d = safe_float(curr.get('stoch_k'), 50.0), safe_float(curr.get('stoch_d'), 50.0)
            if is_q: return 90.0 if k>d and k<80 else 40.0
            return 95.0 if k<20 else 50.0
        if name == "supertrend":
            st = safe_float(curr.get('ST_DIR'))
            if st == 1: return 100.0
            if st == -1: return 0.0
            return 50.0
        if name == "obv": return 100.0 if safe_float(curr.get('obv')) > safe_float(prev.get('obv')) else 30.0
        return 50.0
    except: return 50.0

# ── [Unified Logic] Initial Exit Plan Calculation ──────────────────────────
def calculate_initial_exit_plan(ticker, price, curr_i, strat_config):
    """
    All engines must call this to ensure the same initial SL/TP setup.
    """
    atr = safe_float(curr_i.get('ATR', curr_i.get('atr', 0)))
    atr_pct = (atr / price * 100) if price > 0 else 1.5
    
    from strategy_logic import get_coin_tier_params # Local import to avoid circularity if needed, though already in file
    tier_params = get_coin_tier_params(ticker, curr_i, strat_config=strat_config)
    sl_atr_mult = tier_params.get('atr_mult', 2.0)
    target_mult = tier_params.get('target_atr_multiplier', 4.5)
    
    # ATR-based Stop Loss (with floor)
    final_sl = max(-(atr_pct * sl_atr_mult), tier_params.get('stop_loss', -3.0))
    # Target ATR Multiplier
    expected_target = atr_pct * target_mult
    
    # Risk/Reward Protection: Stop loss shouldn't be wider than 70% of target
    if abs(final_sl) > (expected_target * 0.7):
        final_sl = -(expected_target * 0.7)
        
    return {
        "target_atr_multiplier": target_mult,
        "stop_loss": round(final_sl, 2),
        "atr_mult": sl_atr_mult,
        "timeout": tier_params.get('timeout_candles', 8),
        "adaptive_breakeven_buffer": tier_params.get('adaptive_breakeven_buffer', 0.003),
        "target": expected_target # Pre-calculated target pct
    }


def evaluate_sell_conditions(ticker, t, avg_p, real_price, p_rate, now_ts, current_live_score, ma_live_score, curr_i, strat_config):
    p_rate = safe_float(p_rate, 0.0); scale_step = t.get('scale_out_step', 0); curr_i = curr_i or t.get('buy_ind', {}); elapsed = now_ts - t.get('buy_ts', now_ts)
    entry_atr = safe_float(t.get('entry_atr', 0)); tp_mult = strat_config.get('tp_atr_mult', 4.5); rel_vol = (entry_atr / avg_p * 100) if avg_p > 0 else 1.0
    vol_adj = strat_config.get('vol_adj_mult_high', 1.2) if rel_vol > 2.0 else (strat_config.get('vol_adj_mult_low', 0.8) if rel_vol < 0.8 else 1.0)
    tp_target = (entry_atr * tp_mult * vol_adj / avg_p * 100) * (0.4 if scale_step == 0 else 1.0) if avg_p > 0 else 3.5
    max_p = (t.get('high_p', avg_p) / avg_p - 1) * 100; atr_pct = (entry_atr / avg_p * 100) if avg_p > 0 else 1.5
    initial_sl = t.get('exit_plan', {}).get('stop_loss', strat_config.get('stop_loss', -1.5))
    stop_p = avg_p * (1 + initial_sl/100)
    
    if max_p >= (atr_pct * strat_config.get('step_up_l2_atr', 3.0)):
        stop_p = avg_p * (1 + (atr_pct * 1.5)/100)
    elif max_p >= (atr_pct * strat_config.get('step_up_l1_atr', 1.5)):
        stop_p = avg_p * 1.005

    # ── [7-Layer Dynamic Guards] ──────────────────────────────────────────
    # 1. Nano Failed: Early profit decay
    is_nano_failed = (max_p >= 0.5 and p_rate < 0.1)
    # 2. Micro Failed: Small profit pullback
    is_micro_failed = (max_p >= 1.2 and p_rate < 0.5)
    # 3. Sideways Decay: Exit if flat for too long
    is_sideways_decay = (elapsed > 3600 and abs(p_rate) < 0.3)
    # 4. RSI Overheated Drop: RSI peak reversal
    curr_rsi = safe_float(curr_i.get('rsi'))
    high_rsi = safe_float(t.get('high_rsi', 0))
    is_rsi_overheated_drop = (high_rsi > 75 and curr_rsi < 65)
    # 5. Fundamental Broken: Score drop (already FUND_BROKEN)
    is_fundamental_broken = (ma_live_score < strat_config.get('sell_score_threshold', 45) and p_rate < -0.5)

    conds = [
        (real_price <= stop_p, "STOP_LOSS", 1.0, 9),
        (is_fundamental_broken, "FUND_BROKEN", 1.0, 0),
        (is_rsi_overheated_drop, "RSI_OVERHEATED", 1.0, 9),
        (is_nano_failed or is_micro_failed, "PROFIT_DECAY", 1.0, 9),
        (is_sideways_decay, "SIDEWAYS_EXIT", 1.0, 9),
        (p_rate >= tp_target and scale_step == 0, "PARTIAL_TP", 0.5, 1),
        (elapsed > (strat_config.get('timeout_candles', 8)*900) and p_rate < 0, "TIME_OUT", 1.0, 9),
        (max_p >= 1.0 and p_rate < 0.1, "PROFIT_GUARD", 1.0, 9)
    ]
    
    for c, r, ratio, n_s in conds:
        if c: return True, (ratio < 1.0), ratio, r, "NORMAL", n_s
    return False, False, 0.0, "", "NORMAL", 0

def run_sub_eval_logic(ticker, prev_i, curr_i, fgi_val, mtf_data, mode, p, btc_short=None):
    is_meme = any(m in ticker for m in ["DOGE", "SHIB", "PEPE"])
    tier = get_coin_tier(ticker, curr_i)
    indicators = ['z_score', 'macd', 'rsi', 'volume', 'supertrend', 'bollinger', 'vwap', 'ssl_channel', 'sma_crossover', 'ichimoku', 'obv', 'stochastics', 'bollinger_breakout']
    weights = {'z_score': p.w_zscore, 'macd': p.w_macd, 'rsi': p.w_rsi, 'volume': p.w_volume, 'supertrend': p.w_st, 'bollinger': p.w_bb, 'vwap': p.w_vwap, 'ssl_channel': p.w_ssl, 'sma_crossover': p.w_sma, 'ichimoku': p.w_ichimoku, 'obv': p.w_obv, 'stochastics': p.w_stoch, 'bollinger_breakout': p.w_bb_break}
    f_mult = p.foundation_mult_q if mode == "QUANTUM" else p.foundation_mult_c
    v_mult = p.vas_mult_major if tier == "Major" else p.vas_mult_mid
    vol, v_sma = safe_float(curr_i.get('volume')), safe_float(curr_i.get('vol_sma'), 0.0001)
    atr = safe_float(curr_i.get('atr', curr_i.get('ATR', 0)))
    v_idx = (atr / max(1e-9, safe_float(curr_i.get('close')))) * 100
    mtf = mtf_data.get('1h_trend', 0) if mtf_data else 0
    final_thr = p.pass_score_threshold + (5 if tier=="Small" or is_meme else 0)
    vol_thr = p.vol_multiple_major if tier=="Major" else (p.vol_multiple_mid if tier=="Mid" else p.vol_multiple_small)
    if vol < v_sma * vol_thr: return 0.0, "VOL_LOW", final_thr, mode
    if v_idx < p.vol_idx_limit: return 0.0, "VOL_IDX_LOW", final_thr, mode
    if mode == "QUANTUM" and mtf == -1: return 0.0, "MTF_DOWN", final_thr, mode
    earned, total_w = 0.0, 1e-9
    rsi_live = safe_float(curr_i.get('rsi', 50))
    for name in indicators:
        w = weights.get(name, 1.0)
        if tier not in ["Major", "Mid"] and name in ['supertrend', 'stochastics']:
            w *= 1.5
        s = get_strategy_score(name, prev_i, curr_i, safe_float(curr_i.get('close')), mode) * v_mult
        if name == 'rsi' and rsi_live > p.rsi_high_thr:
            s *= p.rsi_overbought_mult
        if name == 'macd' and safe_float(curr_i.get('macd_h')) <= 0:
            s *= p.macd_negative_mult
        if tier == "Major" and (safe_float(curr_i.get('close')) < safe_float(curr_i.get('ema60')) or rsi_live < 50):
            s *= p.major_weak_mult
        earned += (s * w)
        total_w += w
    avg_s = earned / total_w
    if avg_s >= 85:
        f_mult *= (1.0 + p.sniper_boost)
    f_score = avg_s * f_mult
    if tier not in ["Major", "Mid"]:
        f_score *= p.alt_accel_mult
    bonus = 0.0
    cvd_up = safe_float(curr_i.get('cvd')) > safe_float(prev_i.get('cvd'))
    if mode == "QUANTUM":
        bb_u = safe_float(curr_i.get('bb_u'))
        if safe_float(curr_i.get('close')) >= bb_u and bb_u > 0:
            bonus += p.bb_breakout_bonus
        s20, s60 = safe_float(curr_i.get('ema20')), safe_float(curr_i.get('ema60'))
        if s20 > s60 and safe_float(curr_i.get('close')) > s20:
            bonus += p.sma_align_bonus
    else:
        if rsi_live < 35:
            bonus += p.rsi_oversold_bonus
        if cvd_up:
            bonus += p.cvd_bonus
        slv = safe_float(curr_i.get('ema60'))
        if slv > 0 and ((safe_float(curr_i.get('close'))-slv)/slv)*100 < -7.0:
            bonus += p.sma_gap_bonus
    # ── [Unified Scoring Logic] ──────────────────────────────────────────
    # 3. [ADD] Wick Penalty (Synchronized with Vectorized)
    up_shadow = (safe_float(curr_i.get('high')) - max(safe_float(curr_i.get('close')), safe_float(curr_i.get('open')))) / max(1e-9, safe_float(curr_i.get('close'))) * 100
    wick_r = p.wick_ratio_major if tier == "Major" else p.wick_ratio_meme
    if up_shadow > wick_r:
        bonus -= p.wick_penalty

    # ── [Unified Scoring Logic] ──────────────────────────────────────────
    total = f_score + bonus
    
    # 5. [ADD] MTF Bonus/Penalty (Synchronized with Vectorized)
    if mtf == 1:
        total += p.mtf_bonus_q
    elif mtf == -1:
        total -= p.mtf_penalty_q
        
    # 6. [ADD] Sniper Confluence Bonus (Synchronized with Vectorized)
    if rsi_live < 30 and safe_float(curr_i.get('macd_h'), 0) > 0:
        total += p.sniper_confluence_bonus

    if mode == "QUANTUM":
        if safe_float(curr_i.get('cvd')) < 0:
            total -= p.cvd_penalty_q
        # [ADD] Squeeze Bonus
        bb_bw = safe_float(curr_i.get('bb_bw'))
        if 0 < bb_bw < p.bb_bw_limit:
            total += (p.squeeze_bonus_maj if tier == "Major" else p.squeeze_bonus_alt)
    else:
        if safe_float(curr_i.get('cvd')) < 0:
            total -= p.cvd_penalty_c
        # [ADD] Divergence Penalty
        c_rsi, p_rsi = safe_float(curr_i.get('rsi')), safe_float(prev_i.get('rsi'))
        c_price, p_price = safe_float(curr_i.get('close')), safe_float(prev_i.get('close'))
        if c_rsi < p_rsi and c_price > p_price: # Bearish Divergence
            total -= p.divergence_penalty
        # [ADD] CVD Slope Penalty
        if safe_float(curr_i.get('cvd')) < safe_float(prev_i.get('cvd')):
            total -= p.cvd_slope_penalty_c

    final_thr = p.pass_score_threshold + (5 if tier=="Small" or is_meme else 0)
    return round(max(0.0, min(100.0, total)), 1), None, final_thr, mode

def evaluate_strategy_sync(ticker, prev_i, curr_i, fgi, mtf, p, btc=None):
    c = run_sub_eval_logic(ticker, prev_i, curr_i, fgi, mtf, "CLASSIC", p)
    q = run_sub_eval_logic(ticker, prev_i, curr_i, fgi, mtf, "QUANTUM", p)
    if c[0] >= q[0]: return c
    return q

def evaluate_coin_fundamental_sync(ticker, prev_i, curr_i, fgi_val=50.0, mtf_data=None, p_dict=OPTIMIZED_PARAMS, **kwargs):
    return evaluate_strategy_sync(ticker, prev_i, curr_i, fgi_val, mtf_data, p_dict)

@njit
def _njit_rsi_score(rsi, prev_rsi, is_q):
    n = len(rsi); s = np.full(n, 50.0)
    for i in prange(n):
        if is_q:
            if 50 <= rsi[i] <= 65: s[i] = 100.0
            elif rsi[i] > 85: s[i] = 30.0
            else: s[i] = max(0.0, rsi[i] - 10)
        else:
            b = min(100.0, max(0.0, (50.0-rsi[i])*3.0 + 60))
            if rsi[i] > prev_rsi[i] and rsi[i] < 45: s[i] = min(100.0, b+15.0)
            else: s[i] = b
    return s

@njit
def _njit_bb_score(close, u, l, p_close, p_l, is_q):
    n = len(close); s = np.full(n, 50.0)
    for i in prange(n):
        p = (close[i]-l[i]) / max(1e-9, u[i]-l[i])
        if is_q: s[i] = min(100.0, max(0.0, p*100))
        else:
            b = min(100.0, max(0.0, 110.0-(p*60)))
            if p_close[i] < p_l[i] and close[i] > l[i]: s[i] = min(100.0, b+35.0)
            else: s[i] = b
    return s

@njit
def _njit_z_score(z, is_q):
    n = len(z); s = np.full(n, 50.0)
    for i in prange(n):
        if is_q: s[i] = min(100.0, max(0.0, 95.0-(abs(z[i]-0.5)*25)))
        else: s[i] = min(100.0, max(0.0, 75.0+(z[i]*-25.0)))
    return s

def get_strategy_score_vec(name, prev, curr, mode="QUANTUM"):
    c = curr['close']; n = len(c); is_q = (mode == "QUANTUM")
    def calc_dist_v(v, b, inv=False):
        d = ((v - b) / np.maximum(1e-9, b)) * 100
        m = np.where(inv, -d*15.0, d*15.0)
        return np.where(m>0, 50.0+(35.0*(m/(m+15.0))), 50.0+m)

    if name=="rsi": return _njit_rsi_score(curr.get('rsi', np.full(n,50.0)), prev.get('rsi', np.full(n,50.0)), is_q)
    if name=="bollinger": return _njit_bb_score(c, curr.get('bb_u', np.ones(n)), curr.get('bb_l', np.zeros(n)), prev.get('close', c), prev.get('bb_l', np.zeros(n)), is_q)
    if name=="z_score": return _njit_z_score(curr.get('z_score', np.zeros(n)), is_q)
    if name=="macd":
        h, d, sma = curr.get('macd_h', np.zeros(n)), curr.get('macd_h_diff', np.zeros(n)), curr.get('macd_h_diff_sma', np.full(n,0.0001))
        if is_q:
            base = np.where(h>0, 65.0, 0.0)
            accel = np.where(d>0, np.minimum(1.0, d*5.0)*35.0, 0.0)
            return np.minimum(100.0, base + accel)
        return np.where(d>0, np.clip((d / (np.maximum(sma*2, 1e-9))) * 100, 50.0, 100.0), 30.0)
    if name=="volume":
        v, s = curr.get('volume', np.zeros(n)), curr.get('vol_sma', np.ones(n))
        base = (v/(s+1))*(50 if is_q else 30) + (0 if is_q else 30)
        if is_q: return np.minimum(100.0, np.where(v > s*1.5, base+20.0, base))
        return np.minimum(100.0, base)
    if name=="vwap": return calc_dist_v(c, curr.get('vwap', c), inv=(not is_q))
    if name=="ssl_channel": return calc_dist_v(c, curr.get('ssl_up', c), inv=(not is_q))
    if name=="sma_crossover":
        l, s = curr.get('sma_long', curr.get('ema60', np.full(n,1e-9))), curr.get('sma_short', curr.get('ema20', np.full(n,1e-9)))
        if not is_q: return np.clip(50.0-(((c-l)/l)*600), 0, 100)
        return np.where(c>l, 75.0+(((s-l)/l)*1500), np.where(c>l, 50.0, 0.0))
    if name=="ichimoku":
        sa, sb = curr.get('span_a', np.zeros(n)), curr.get('span_b', np.zeros(n))
        return np.where((sa==0)|(sb==0), 50.0, np.where(c>np.maximum(sa,sb), 100.0, np.where(c<np.minimum(sa,sb), 0.0, 50.0)))
    if name=="stochastics":
        k, d = curr.get('stoch_k', np.full(n,50.0)), curr.get('stoch_d', np.full(n,50.0))
        if is_q: return np.where((k>d)&(k<80), 90.0, 40.0)
        return np.where(k<20, 95.0, 50.0)
    if name=="supertrend":
        st = curr.get('ST_DIR', np.zeros(n))
        return np.where(st==1, 100.0, np.where(st==-1, 0.0, 50.0))
    if name=="obv": return np.where(curr.get('obv', np.zeros(n)) > prev.get('obv', np.zeros(n)), 100.0, 30.0)
    return np.full(n, 50.0)

def evaluate_strategy_vectorized(ticker: str, curr: Dict[str, Any], p: ScoringParams) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # [최적화] 이미 넘파이 배열인 경우 변환 생략 (메모리 복사 방지)
    curr = {k: np.asanyarray(v, dtype=np.int64 if k == 'timestamp' else np.float32) for k, v in curr.items()}
    n = len(curr['close'])
    prev = {k: np.roll(v, 1) for k, v in curr.items()}
    for k in prev:
        if len(prev[k]) > 1:
            prev[k][0] = prev[k][1]
    closes = curr['close']
    atrs = np.maximum(1e-9, curr.get('atr', curr.get('ATR', np.zeros(n))))
    v_idx = (atrs / np.maximum(1e-9, closes)) * 100
    is_meme = any(m in ticker for m in ["DOGE", "SHIB", "PEPE"])
    tiers = np.where(v_idx > 3.5, "Small", np.where(v_idx > 1.5, "Mid", "Major"))
    
    fatal_base = np.zeros(n, dtype=bool)
    vol, vol_sma = curr['volume'], np.maximum(1e-9, curr.get('vol_sma', np.zeros(n)))
    v_thr_v = np.where(tiers=="Major", p.vol_multiple_major, np.where(tiers=="Mid", p.vol_multiple_mid, p.vol_multiple_small))
    fatal_base |= (vol < vol_sma * v_thr_v)
    fatal_base |= (v_idx < p.vol_idx_limit)

    def calc_mode_score(mode):
        indicators = ['z_score', 'macd', 'rsi', 'volume', 'supertrend', 'bollinger', 'vwap', 'ssl_channel', 'sma_crossover', 'ichimoku', 'obv', 'stochastics', 'bollinger_breakout']
        weights = {'z_score': p.w_zscore, 'macd': p.w_macd, 'rsi': p.w_rsi, 'volume': p.w_volume, 'supertrend': p.w_st, 'bollinger': p.w_bb, 'vwap': p.w_vwap, 'ssl_channel': p.w_ssl, 'sma_crossover': p.w_sma, 'ichimoku': p.w_ichimoku, 'obv': p.w_obv, 'stochastics': p.w_stoch, 'bollinger_breakout': p.w_bb_break}
        f_mult = p.foundation_mult_q if mode == "QUANTUM" else p.foundation_mult_c
        v_mult = np.where(tiers == "Major", p.vas_mult_major, p.vas_mult_mid)
        
        earned, total_w = np.zeros(n), np.full(n, 1e-9)
        for name in indicators:
            w = weights.get(name, 1.0)
            if name in ['supertrend', 'stochastics']:
                w = np.where((tiers != "Major") & (tiers != "Mid"), w * 1.5, w)
            s = get_strategy_score_vec(name, prev, curr, mode=mode) * v_mult
            if name == 'rsi':
                s = np.where(curr.get('rsi', 50) > p.rsi_high_thr, s * p.rsi_overbought_mult, s)
            if name == 'macd':
                s = np.where(curr.get('macd_h', 0) <= 0, s * p.macd_negative_mult, s)
            if (tiers == "Major").any():
                s = np.where((tiers == "Major") & ((closes < curr.get('ema60',0)) | (curr.get('rsi',50) < 50)), s * p.major_weak_mult, s)
            earned += (s * w)
            total_w += w
        
        avg_s = earned / total_w
        f_score = avg_s * np.where(avg_s >= 85.0, f_mult * (1.0 + p.sniper_boost), f_mult)
        if (tiers != "Major").any():
            f_score = np.where((tiers != "Major") & (tiers != "Mid"), f_score * p.alt_accel_mult, f_score)
        
        bonus = np.zeros(n)
        cvd_up = curr.get('cvd', 0) > prev.get('cvd', 0)
        rsi_live = curr.get('rsi', 50)
        if mode == "QUANTUM":
            bb_u = curr.get('bb_u', 0)
            bonus = np.where((closes >= bb_u) & (bb_u > 0), bonus + p.bb_breakout_bonus, bonus)
            s20, s60 = curr.get('ema20',0), curr.get('ema60',0)
            bonus = np.where((s20>s60)&(closes>s20), bonus + p.sma_align_bonus, bonus)
            # [ADD] Squeeze Bonus (Vectorized)
            bb_bw = curr.get('bb_bw', np.ones(n))
            bonus = np.where((bb_bw > 0) & (bb_bw < p.bb_bw_limit), 
                             bonus + np.where(tiers == "Major", p.squeeze_bonus_maj, p.squeeze_bonus_alt), bonus)
        else:
            bonus = np.where(rsi_live < 35, bonus + p.rsi_oversold_bonus, bonus)
            bonus = np.where(cvd_up, bonus + p.cvd_bonus, bonus)
            slv = curr.get('ema60', 0)
            gap = np.where(slv>0, ((closes-slv)/slv)*100, 0)
            bonus = np.where((slv>0) & (gap < -7.0), bonus + p.sma_gap_bonus, bonus)
            # [ADD] Divergence Penalty (Vectorized)
            p_rsi = prev.get('rsi', rsi_live)
            p_closes = prev.get('close', closes)
            bonus = np.where((rsi_live < p_rsi) & (closes > p_closes), bonus - p.divergence_penalty, bonus)
            # [ADD] CVD Slope Penalty (Vectorized)
            bonus = np.where(curr.get('cvd', 0) < prev.get('cvd', 0), bonus - p.cvd_slope_penalty_c, bonus)
        
        # [ADD] Wick Penalty (Vectorized)
        up_shadow = (curr.get('high', closes) - np.maximum(closes, curr.get('open', closes))) / np.maximum(1e-9, closes) * 100
        wick_r = np.where(tiers=="Major", p.wick_ratio_major, p.wick_ratio_meme)
        bonus = np.where(up_shadow > wick_r, bonus - p.wick_penalty, bonus)
        
        # ── [Unified Scoring Logic] ──────────────────────────────────────────
        total = f_score + bonus
        
        # [ADD] MTF Bonus/Penalty (Vectorized)
        mtf_v = curr.get('1h_trend', np.zeros(n))
        total = np.where(mtf_v == 1, total + p.mtf_bonus_q, np.where(mtf_v == -1, total - p.mtf_penalty_q, total))
        
        # [ADD] Sniper Confluence Bonus (Vectorized)
        sniper_c = (curr.get('rsi', 50) < 30) & (curr.get('macd_h', 0) > 0)
        total = np.where(sniper_c, total + p.sniper_confluence_bonus, total)

        if mode == "QUANTUM":
            total = np.where(curr.get('cvd', 0) < 0, total - p.cvd_penalty_q, total)
        else:
            total = np.where(curr.get('cvd', 0) < 0, total - p.cvd_penalty_c, total)
        
        m_fatal = fatal_base.copy()
        mtf = curr.get('1h_trend', np.zeros(n))
        if mode == "QUANTUM":
            m_fatal |= (mtf == -1)
        
        total = np.where(m_fatal, 0.0, np.clip(total, 0.0, 100.0))
        thr = np.full(n, p.pass_score_threshold)
        thr = np.where((tiers == "Small") | is_meme, thr + 5.0, thr)
        return total, m_fatal, thr

    sq, fq, tq = calc_mode_score("QUANTUM")
    sc, fc, tc = calc_mode_score("CLASSIC")
    
    is_classic_better = sc >= sq
    final_scores = np.where(is_classic_better, sc, sq)
    final_fatals = np.where(is_classic_better, fc, fq)
    final_thrs = np.where(is_classic_better, tc, tq)
    final_modes = np.where(is_classic_better, "CLASSIC", "QUANTUM")
    return final_scores, final_fatals, final_thrs, final_modes

def warm_up_numba():
    """Numba JIT 컴파일을 미리 수행하여 실제 계산 시 지연을 제거합니다."""
    try:
        dummy_data = {
            'close': np.array([100.0, 101.0], dtype=np.float32),
            'volume': np.array([1000.0, 1100.0], dtype=np.float32),
            'rsi': np.array([50.0, 55.0], dtype=np.float32),
            'macd_h': np.array([0.1, 0.2], dtype=np.float32),
            'macd_h_diff': np.array([0.01, 0.02], dtype=np.float32),
            'macd_h_diff_sma': np.array([0.01, 0.01], dtype=np.float32),
            'bb_u': np.array([110.0, 110.0], dtype=np.float32),
            'bb_l': np.array([90.0, 90.0], dtype=np.float32),
            'z_score': np.array([0.5, 0.6], dtype=np.float32),
            'ema20': np.array([100.0, 100.5], dtype=np.float32),
            'ema60': np.array([99.0, 99.2], dtype=np.float32),
            'atr': np.array([1.5, 1.5], dtype=np.float32),
        }
        p = ScoringParams()
        evaluate_strategy_vectorized("WARMUP", dummy_data, p)
    except:
        pass

if __name__ == "__main__":
    warm_up_numba()
