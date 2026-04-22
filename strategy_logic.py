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
import pandas as pd
import numpy as np
import pandas_ta as ta # noqa: F401

# ════════════════════════════════════════════════════════════════════════════
#  ScoringParams  ── 점수 계산 로직의 모든 가변 파라미터
#  (backtest_optimizer.py에서 중앙 관리로 이전)
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class ScoringParams:
    """
    점수 계산 방정식에서 조정 가능한 모든 파라미터.
    """
    # [A] 파운데이션 승수
    foundation_mult_q:   float = 2.20
    foundation_mult_c:   float = 1.05
    sniper_boost:        float = 0.03

    # [B] 보너스 / 패널티
    mtf_bonus_q:         float = 25.0
    mtf_penalty_q:       float = 40.0
    wick_penalty:        float = 55.0
    wick_ratio_major:    float = 1.5
    wick_ratio_meme:     float = 1.0
    bb_breakout_bonus:   float = 55.0
    sma_align_bonus:     float = 35.0
    rsi_oversold_bonus:  float = 55.0
    sma_gap_bonus:       float = 30.0
    cvd_bonus:           float = 25.0
    osc_conv_bonus_alt:  float = 15.0
    osc_conv_bonus_maj:  float = 8.5
    sma_above_bonus:     float = 5.0
    squeeze_bonus_alt:   float = 12.0
    squeeze_bonus_maj:   float = 5.0
    st_psar_bonus:       float = 15.0
    mid_sma_penalty:     float = 20.0
    rsi_slope_penalty:   float = 15.0
    divergence_penalty:  float = 15.0
    fgi_bonus_dampen:    float = 0.80

    # [C] 티어 승수
    vas_mult_major:      float = 1.08
    vas_mult_mid:        float = 1.05
    alt_accel_mult:      float = 1.15

    # [D] 지표별 감쇄/승수
    rsi_overbought_mult: float = 0.50
    macd_negative_mult:  float = 0.60
    major_weak_mult:     float = 0.20
    meme_bad_mult:       float = 0.01

    # [E] 지표 가중치 (Weights)
    w_zscore:        float = 2.5
    w_macd:          float = 2.0
    w_rsi:           float = 1.0
    w_volume:        float = 2.0
    w_st:            float = 1.5
    w_bb:            float = 1.0
    w_vwap:          float = 1.0
    w_ssl:           float = 1.0
    w_sma:           float = 1.0
    w_ichimoku:      float = 1.0
    w_obv:           float = 1.0

    # [F] 시스템 제어 및 임계값
    pass_score_threshold: float = 85.0
    rsi_high_thr:         float = 75.0
    rsi_low_thr:          float = 30.0

    # [G] 수익 극대화 파라미터 (새로 추가)
    sniper_confluence_bonus: float = 45.0
    tp_atr_mult:             float = 4.5
    sl_atr_mult:             float = 2.0
    step_up_l1_atr:          float = 1.5
    step_up_l2_atr:          float = 3.0
    vol_adj_mult_high:       float = 1.2
    vol_adj_mult_low:        float = 0.8
    vol_multiple_small:    float = 2.2
    vol_multiple_major:    float = 1.5
    cvd_penalty_q:         float = 20.0
    cvd_penalty_c:         float = 8.0
    cvd_slope_penalty_c:   float = 12.0
    vol_ratio_penalty_c:   float = 10.0
    
    # 임계점수 (Optimizer에서 사용)
    pass_score_threshold:  float = 85.0


# ── [최적화 파라미터] ────────────────────────────────────────────────────────
# Optimizer를 통해 발굴된 최적 파라미터 세트. 모든 엔진의 기본값으로 사용됩니다.
OPTIMIZED_PARAMS = ScoringParams(
    foundation_mult_q=5.745365,
    foundation_mult_c=0.515967,
    sniper_boost=0.256428,
    mtf_bonus_q=119.359476,
    mtf_penalty_q=0.0,
    wick_penalty=1.358166,
    wick_ratio_major=0.0,
    wick_ratio_meme=5.380842,
    bb_breakout_bonus=0.0,
    sma_align_bonus=174.09733,
    rsi_oversold_bonus=90.583499,
    sma_gap_bonus=0.0,
    cvd_bonus=33.25972,
    osc_conv_bonus_alt=27.550317,
    osc_conv_bonus_maj=10.70363,
    sma_above_bonus=46.002768,
    squeeze_bonus_alt=17.967481,
    squeeze_bonus_maj=7.02649,
    st_psar_bonus=3.821377,
    mid_sma_penalty=42.2882,
    rsi_slope_penalty=1.829236,
    divergence_penalty=47.594633,

    fgi_bonus_dampen=1.840189,
    vas_mult_major=0.458731,
    vas_mult_mid=2.209255,
    alt_accel_mult=2.86511,
    rsi_overbought_mult=0.373925,
    macd_negative_mult=1.062502,
    major_weak_mult=0.866446,
    meme_bad_mult=1.364843,
    vol_multiple_small=3.77695,
    vol_multiple_major=2.347211,
    cvd_penalty_q=93.156509,
    cvd_penalty_c=42.417935,
    cvd_slope_penalty_c=0.0,
    vol_ratio_penalty_c=34.79928,
    pass_score_threshold=85.0
)

# ── [전역 상수] ───────────────────────────────────────────────────────────────
GLOBAL_COMMISSION     = 0.0005     # 0.05%
GLOBAL_MAX_POSITIONS  = 10         # 최대 10종목 보유
GLOBAL_RISK_PER_TRADE = 0.015      # 1회 최대 손실 허용률 1.5%

# ── [공용 유틸리티 함수] ──────────────────────────────────────────────────────
def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None: return float(default)
    try: return float(val)
    except (ValueError, TypeError):
        cleaned = re.sub(r'[^0-9.\\-]', '', str(val))
        if cleaned and cleaned != '-':
            try: return float(cleaned)
            except: pass
        return float(default)

def get_coin_tier(ticker: str, curr_i: dict) -> str:
    # Tier 분류 로직 (backtest_optimizer.py 기준으로 통일)
    try:
        if not isinstance(curr_i, dict): return "Major"
        close_val = safe_float(curr_i.get('close'))
        atr_val   = safe_float(curr_i.get('ATR') or curr_i.get('atr'))
        if close_val <= 0 or atr_val <= 0: return "Major"
        
        vol_idx = (atr_val / close_val) * 100
        if vol_idx > 3.5:   return "Small (High Vol)"
        elif vol_idx > 1.5: return "Mid"
        else:               return "Major"
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
    """
    고도화된 리스크 기반 투자 금액 계산 함수
    :param atr_pct: ATR 비율 (단위: %, 예: 2.5)
    """
    # 1. 리스크 기반 금액 (ATR 대비 자산의 1.5%를 손실액으로 설정)
    risk_based_amt = equity * GLOBAL_RISK_PER_TRADE / (max(0.5, atr_pct) / 100)
    
    # 2. 균등 분할 한도 (총 자산을 최대 포지션 수로 나눈 뒤 1.2배 여유)
    equal_weight_cap = (equity / GLOBAL_MAX_POSITIONS) * 1.2
    
    # 3. 가용 현금 한도
    cash_cap = cash * 0.98
    
    # 세 가지 한도 중 최솟값 적용
    buy_amt = min(risk_based_amt, equal_weight_cap, cash_cap)
    return max(0, buy_amt)

def evaluate_coin_fundamental_sync(ticker, prev_i, curr_i, current_regime_mode="HYBRID",
                                   fgi_val=50.0, btc_short_trend=None, force_eval_mode=None, mtf_data=None, p_dict=OPTIMIZED_PARAMS):
    """
    제온(실전), 러너, 옵티마이저가 공통으로 사용하는 최종 채점 인터페이스.
    BTC 추세 객체를 자동 생성하여 하위 로직에 전달합니다.
    """
    btc_obj = {'trend': btc_short_trend} if isinstance(btc_short_trend, str) else (btc_short_trend or {})
    
    if force_eval_mode:
        return run_sub_eval_logic(ticker, prev_i, curr_i, fgi_val, mtf_data, force_eval_mode, p_dict, btc_short=btc_obj)
    
    return evaluate_strategy_sync(ticker, prev_i, curr_i, fgi_val, mtf_data, p_dict, btc_short=btc_obj)
def get_coin_tier_params(ticker, curr_i, strat_config=None):
    """종목 티어별 파라미터(TP/SL 무거운 설정 등)를 반환합니다."""
    tier = get_coin_tier(ticker, curr_i)
    if not strat_config:
        return {} # 기본값
    if tier == "Small (High Vol)": 
        return strat_config.get('high_vol_params', {})
    elif tier == "Mid":
        return strat_config.get('mid_vol_params', {})
    return strat_config.get('major_params', {})

def clamp_value(val, min_v, max_v, default=0.0):
    v = safe_float(val, default)
    return max(min_v, min(v, max_v))

def get_constrained_value(key, p_dict, mode="QUANTUM"):
    """
    [로직 통합] 파라미터 객체/딕셔너리에서 값을 직접 반환합니다.
    - Optimizer, Runner, Xeon 간의 파라미터 불일치 문제를 원천 차단합니다.
    - 이전의 복잡한 clamping/제약 로직을 제거하여 일관성을 보장합니다.
    """
    default_val = 0.0
    if hasattr(p_dict, key):
        return getattr(p_dict, key, default_val)
    elif isinstance(p_dict, dict):
        return p_dict.get(key, default_val)
    return default_val

def _calculate_ta_indicators_sync(df: pd.DataFrame, btc_df: pd.DataFrame = None, strat_params: dict = None) -> pd.DataFrame:
    """모든 엔진이 공유하는 표준 지표 계산 로직입니다 (정적 버전)."""
    if df is None or len(df) < 50: return df
    p = strat_params or {}
    
    # 기본 지표
    df['ATR'] = df.ta.atr(length=p.get('atr_len', 14))
    st = df.ta.supertrend(length=p.get('st_len', 20), multiplier=p.get('st_mult', 3.0))
    if st is not None: df['ST_DIR'] = st.iloc[:, 1]
    
    df['vwap'] = df.ta.vwap()
    df['vol_sma'] = df['volume'].rolling(window=20).mean()
    
    # CVD (Cumulative Volume Delta)
    hl = (df['high'] - df['low']).replace(0, 0.00001)
    df['vol_delta'] = df['volume'] * ((df['close'] - df['low']) / hl) - df['volume'] * ((df['high'] - df['close']) / hl)
    df['cvd'] = df['vol_delta'].rolling(window=20).sum()
    
    df['obv'] = df.ta.obv()
    df['rsi'] = df.ta.rsi(length=p.get('rsi_len', 14))
    
    # Stochastic RSI
    st_rsi = df.ta.stochrsi(length=p.get('stoch_rsi_len', 14), k=p.get('stoch_rsi_k_len', 3), d=p.get('stoch_rsi_d_len', 3))
    if st_rsi is not None:
        df['st_rsi_k'], df['st_rsi_d'] = st_rsi.iloc[:, 0], st_rsi.iloc[:, 1]
    
    # Stochastics
    stoch = df.ta.stoch(k=p.get('stochastics_k_len', 14), d=p.get('stochastics_d_len', 3))
    if stoch is not None:
        df['stoch_k'], df['stoch_d'] = stoch.iloc[:, 0], stoch.iloc[:, 1]
        
    # MACD
    macd = df.ta.macd(fast=p.get('macd_fast_len', 12), slow=p.get('macd_slow_len', 26), signal=p.get('macd_signal_len', 9))
    if macd is not None:
        df['macd_h'] = macd.iloc[:, 1]
        df['macd_h_diff'] = df['macd_h'].diff()
        df['macd_h_diff_sma'] = df['macd_h_diff'].abs().rolling(window=10).mean()
        
    # ADX
    adx_df = df.ta.adx(length=p.get('adx_len', 14))
    if adx_df is not None: df['adx'] = adx_df.iloc[:, 0]
    
    # Bollinger Bands
    bb = df.ta.bbands(length=p.get('bollinger_len', 20), std=p.get('bollinger_std_dev', 2))
    if bb is not None:
        df['bb_l'], df['bb_u'], df['bb_bw'] = bb.iloc[:, 0], bb.iloc[:, 2], bb.iloc[:, 3]
        
    # Keltner Channel
    kc = df.ta.kc(length=p.get('keltner_channel_len', 20), scalar=p.get('keltner_channel_atr_mult', 1.5))
    if kc is not None: df['kc_u'] = kc.iloc[:, 2]
    
    # Ichimoku
    t_len, k_len, s_len = int(p.get('ichimoku_conversion_len', 9)), int(p.get('ichimoku_base_len', 26)), int(p.get('ichimoku_lead_span_b_len', 52))
    tenkan_sen = (df['high'].rolling(window=t_len).max() + df['low'].rolling(window=t_len).min()) / 2
    kijun_sen = (df['high'].rolling(window=k_len).max() + df['low'].rolling(window=k_len).min()) / 2
    df['span_a'] = ((tenkan_sen + kijun_sen) / 2).shift(k_len - 1)
    df['span_b'] = ((df['high'].rolling(window=s_len).max() + df['low'].rolling(window=s_len).min()) / 2).shift(k_len - 1)
    
    df['sma_long'] = df['close'].rolling(window=p.get('bollinger_len', 20)).mean()
    
    if btc_df is not None:
        df['btc_close'] = btc_df['close'].reindex(df.index, method='ffill')
        
    return df

def calculate_grad(v, t, w2, md='DECREASE'):
    df = abs(v - t)
    if md == 'DECREASE': 
        return 1.0 - (df/w2) if t < v < t+w2 else (1.0 if v <= t else 0.0)
    else: 
        return 1.0 - (df/w2) if t-w2 < v < t else (1.0 if v >= t else 0.0)

def get_strategy_score(name: str, prev: dict, curr: dict, price: float, mode: str = "QUANTUM") -> float:
    try:
        if not isinstance(curr, dict) or not isinstance(prev, dict): return 0.0
        
        def calc_dist_score(val, baseline, weight=10.0, inverse=False):
            if baseline <= 0: return 25.0
            dist_pct = ((val - baseline) / baseline) * 100
            raw_move = dist_pct * weight if not inverse else -dist_pct * weight
            if raw_move > 0:
                score = 50.0 + (35.0 * (raw_move / (raw_move + 15.0)))
            else:
                score = 50.0 + raw_move
            return min(100.0, max(15.0, score))

        is_quantum = (mode == "QUANTUM")
        
        if name == "rsi":
            curr_rsi = safe_float(curr.get('rsi'), 50.0)
            if is_quantum:
                if 50 <= curr_rsi <= 65: return 100.0
                if curr_rsi > 85: return 30.0 
                return max(0.0, curr_rsi - 10)
            else:
                base_rsi_s = min(100.0, max(0.0, (50.0 - curr_rsi) * 3.0 + 60))
                rsi_prev = safe_float(prev.get('rsi'), curr_rsi)
                if curr_rsi > rsi_prev and curr_rsi < 45:
                    base_rsi_s = min(100.0, base_rsi_s + 15.0)
                return base_rsi_s
                
        if name == "bollinger":
            bb_u = safe_float(curr.get('bb_u'), 1)
            bb_l = safe_float(curr.get('bb_l'), 0)
            bb_range = bb_u - bb_l
            if bb_range <= 0: return 0.0 if is_quantum else 50.0
            pos_pct = (price - bb_l) / bb_range
            if is_quantum: return min(100.0, max(0.0, pos_pct * 100))
            else:
                base_bb_s = min(100.0, max(0.0, 110.0 - (pos_pct * 60)))
                prev_close = safe_float(prev.get('close'), price)
                bb_l_prev = safe_float(prev.get('bb_l'), 0)
                if prev_close < bb_l_prev and price > bb_l: base_bb_s = min(100.0, base_bb_s + 35.0)
                return base_bb_s
                
        if name == "z_score":
            z = safe_float(curr.get('z_score'), 0.0)
            if is_quantum: return min(100.0, max(0.0, 95.0 - (abs(z - 0.5) * 25)))
            else: return min(100.0, max(0.0, 75.0 + (z * -25.0)))
                
        if name == "macd":
            macd_h = safe_float(curr.get('macd_h'), 0.0)
            macd_h_diff = safe_float(curr.get('macd_h_diff', 0), 0.0)
            if is_quantum:
                base_s = 65.0 if macd_h > 0 else 0.0
                accel = min(1.0, macd_h_diff * 5.0) if macd_h_diff > 0 else 0.0
                return min(100.0, base_s + (accel * 35.0))
            else:
                macd_diff_sma = safe_float(curr.get('macd_h_diff_sma'), 0.0001)
                if macd_h_diff > 0: return min(100.0, max(50.0, (macd_h_diff / max(macd_diff_sma * 2, 0.0001)) * 100))
                return 30.0
                
        if name == "volume":
            curr_vol = safe_float(curr.get('volume'))
            vol_sma = safe_float(curr.get('vol_sma'), 0.0001)
            v_s = min(100.0, (curr_vol / (vol_sma + 1)) * 50) if is_quantum else min(100.0, (curr_vol / (vol_sma + 1)) * 30 + 30)
            if is_quantum and curr_vol > vol_sma * 1.5: v_s = min(100.0, v_s + 20.0)
            return v_s

        if name == "bollinger_breakout" and is_quantum:
            bb_u = safe_float(curr.get('bb_u'), 0)
            if price < bb_u: return 0.0
            prev_bw = safe_float(prev.get('bb_bw'), 0.0001)
            bw_expansion = max(0, (safe_float(curr.get('bb_bw'), 0) - prev_bw) / prev_bw)
            return min(100.0, 70.0 + (bw_expansion * 500))

        is_classic = (mode == "CLASSIC")
        if name == "vwap": return calc_dist_score(price, curr.get('vwap', price), weight=15.0, inverse=is_classic)
        if name == "ssl_channel": return calc_dist_score(price, curr.get('ssl_up', price), weight=15.0, inverse=is_classic)
        if name == "sma_crossover":
            slv = safe_float(curr.get('sma_long', curr.get('ema60', 0.0001)))
            sma_short = safe_float(curr.get('sma_short', curr.get('ema20', 0.0001)))
            if is_classic: return min(100.0, max(0.0, 50.0 - (((price - slv) / max(slv, 1e-9)) * 100 * 6)))
            if price > slv and slv > safe_float(curr.get('sma_50', 0)):
                spread = ((sma_short - slv) / max(slv, 1e-9)) * 100
                return min(100.0, 75.0 + (spread * 15.0))
            return 50.0 if price > slv else 0.0
        if name == "ichimoku":
            span_a = safe_float(curr.get('span_a'), 0)
            span_b = safe_float(curr.get('span_b'), 0)
            if span_a == 0 or span_b == 0: return 50.0
            kumo_top = max(span_a, span_b)
            if price > kumo_top: return 100.0
            if price < min(span_a, span_b): return 0.0
            return 50.0

        if name == "stochastics":
            st_k = safe_float(curr.get('stoch_k'), 50.0)
            st_d = safe_float(curr.get('stoch_d'), 50.0)
            if is_quantum:
                if st_k > st_d and st_k < 80: return 90.0
                return 40.0
            else:
                if st_k < 20: return 95.0
                return 50.0

        if name == "obv":
            obv_now = safe_float(curr.get('obv'), 0)
            obv_prev = safe_float(prev.get('obv'), 0)
            return 100.0 if obv_now > obv_prev else 30.0

        return 50.0
    except: return 50.0

def evaluate_sell_conditions(ticker, t, avg_p, real_price, p_rate, now_ts, current_live_score, ma_live_score, curr_i, strat_config):
    curr_p_rate = safe_float(p_rate, 0.0)
    scale_out_step = t.get('scale_out_step', 0)
    eval_mode = t.get('strategy_mode', 'QUANTUM')
    curr_i_safe = curr_i if curr_i else t.get('buy_ind', {})
    exit_plan = t.get('exit_plan', {})
    
    interval_sec = 900
    elapsed_sec = now_ts - t.get('buy_ts', now_ts)
    timeout_candles = exit_plan.get('timeout', strat_config.get('timeout_candles', 8))
    full_timeout_sec = timeout_candles * interval_sec
    
    entry_score = safe_float(t.get('pass_score', 80), 80.0)
    entry_atr = safe_float(t.get('entry_atr', 0))
    target_atr_multiplier = exit_plan.get('target_atr_multiplier', strat_config.get('tp_atr_mult', 4.5))
    if entry_score >= 90.0: target_atr_multiplier *= 1.2
    
    # ── [전략 로직 개선 2: 변동성 적응형 익절] ───────────────────────────
    # 변동성이 높은 구간에서는 목표가를 높여 추세를 극대화 (ATR 비율 활용)
    rel_vol = (entry_atr / avg_p * 100) if avg_p > 0 else 1.0
    high_v_mult = strat_config.get('vol_adj_mult_high', 1.2)
    low_v_mult = strat_config.get('vol_adj_mult_low', 0.8)
    vol_adj_mult = high_v_mult if rel_vol > 2.0 else (low_v_mult if rel_vol < 0.8 else 1.0)
    target_atr_multiplier *= vol_adj_mult
    
    base_tp_pct = (entry_atr * target_atr_multiplier / avg_p) * 100 if entry_atr > 0 and avg_p > 0 else 3.5
    tp_target = base_tp_pct * (0.4 if scale_out_step == 0 else 1.0)
    
    max_p_rate = (t.get('high_p', avg_p) / avg_p - 1) * 100 if avg_p > 0 else 0
    current_atr_mult = exit_plan.get('atr_mult', strat_config.get('sl_atr_mult', 2.0))
    
    # ── [전략 로직 개선 3: 지능형 수익 보존 (Step-Up Lock)] ──────────────
    # 수익이 1.5 ATR(진입가 대비)에 도달하면 본절 확보, 3.0 ATR 도달하면 수익 50% 잠금
    atr_pct_val = (entry_atr / avg_p * 100) if avg_p > 0 else 1.5
    l1_thr = strat_config.get('step_up_l1_atr', 1.5)
    l2_thr = strat_config.get('step_up_l2_atr', 3.0)
    
    hard_breakeven_floor = 0
    if max_p_rate >= (atr_pct_val * l2_thr): 
        hard_breakeven_floor = avg_p * (1 + (atr_pct_val * (l2_thr/2))/100) # 수익 절반 확정
    elif max_p_rate >= (atr_pct_val * l1_thr): 
        hard_breakeven_floor = avg_p * 1.005 # 본절+수수료 확보
    
    dynamic_mult = current_atr_mult * (0.3 if max_p_rate >= 5.0 else (0.5 if max_p_rate >= 3.0 else (0.7 if max_p_rate >= 1.0 else 1.0)))
    
    atr_stop = t.get('high_p', avg_p) - (entry_atr * dynamic_mult)
    chandelier_stop = t.get('high_p', avg_p) * 0.965 if max_p_rate >= 3.0 else 0
    
    stop_p = max(atr_stop, chandelier_stop, hard_breakeven_floor, avg_p * 0.965)

    sell_score_threshold = safe_float(strat_config.get('sell_score_threshold', 45.0))
    is_fundamental_broken = (ma_live_score < sell_score_threshold and curr_p_rate < -1.0)

    sell_conditions = [
        (curr_p_rate <= -1.5 or real_price <= stop_p, "STOP_OR_PROFIT_LOCK", 1.0, 9, "HIGH"),
        (is_fundamental_broken, "SCORE_DROP", 1.0, 0, "HIGH"),
        (curr_p_rate >= tp_target and scale_out_step == 0, f"PARTIAL_TP({tp_target:.1f}%)", 0.5, 1, "NORMAL"),
        (max_p_rate >= 1.0 and curr_p_rate < 0.1, "PROFIT_GUARD", 1.0, 9, "HIGH"),
        (elapsed_sec > full_timeout_sec and curr_p_rate < 0.0, "TIME_OUT", 1.0, 9, "NORMAL")
    ]
    
    for condition, reason, ratio, next_step, urgency in sell_conditions:
        if condition: return True, (ratio < 1.0), ratio, reason, urgency, next_step
            
    return False, False, 0.0, "", "NORMAL", 0

def run_sub_eval_logic(ticker, prev_i, curr_i, fgi_val, mtf_data, mode, p_dict, btc_short=None):
    """
    ?? ?? ?? (FULL VER) - ATS_Xeon, Optimizer ??
    p_dict: ScoringParams(????) ?? ?? ??? ??? dict
    """
    is_meme = any(m in ticker for m in ["DOGE", "SHIB", "PEPE"])
    tier = get_coin_tier(ticker, curr_i)
    
    # ?? [1] ?? ??? ? ??? ?? ???????????????????????????????????
    # (config?? ???? ??? ????? ???? p_dict? ???? ??? ??)
    # ???? "True Elite" ?? ?? ???? ??
    logic_list = ['supertrend', 'vwap', 'rsi', 'bollinger', 'macd', 'volume', 'ssl_channel', 'sma_crossover', 'ichimoku', 'stochastics', 'obv']
    if mode == "QUANTUM": logic_list.append('bollinger_breakout')
    
    # [1] 가중치 맵핑 (p_dict 기반으로 동적 생성)
    weights = {
        "z_score":           get_constrained_value('w_zscore', p_dict, mode),
        "macd":              get_constrained_value('w_macd', p_dict, mode),
        "rsi":               get_constrained_value('w_rsi', p_dict, mode),
        "volume":            get_constrained_value('w_volume', p_dict, mode),
        "supertrend":        get_constrained_value('w_st', p_dict, mode),
        "bollinger":         get_constrained_value('w_bb', p_dict, mode),
        "vwap":              get_constrained_value('w_vwap', p_dict, mode),
        "ssl_channel":       get_constrained_value('w_ssl', p_dict, mode),
        "sma_crossover":     get_constrained_value('w_sma', p_dict, mode),
        "ichimoku":          get_constrained_value('w_ichimoku', p_dict, mode),
        "obv":               get_constrained_value('w_obv', p_dict, mode),
        "bollinger_breakout": 1.0 # 고정 보너스 성격
    }
    
    curr_close = safe_float(curr_i.get('close'))
    curr_vol = safe_float(curr_i.get('volume'))
    vol_sma = safe_float(curr_i.get('vol_sma', 0.0001))

    # ?? [2] ?? ??? ??? ???? ?? ??????????????????????????????
    foundation_mult = get_constrained_value('foundation_mult_q' if mode == "QUANTUM" else 'foundation_mult_c', p_dict, mode)
    vas_mult = get_constrained_value('vas_mult_major' if tier == "Major" else 'vas_mult_mid', p_dict, mode)
    
    # 단계 [3] Fatal Flaw 체크
    fatal_reason = None
    mtf_trend = mtf_data.get('1h_trend', 0) if mtf_data else 0
    rsi_live = safe_float(curr_i.get('rsi', curr_i.get('RSI', 50)))
    
    # BTC 추세 체크 (인자로 전달받은 btc_short 활용)
    btc_trend = btc_short.get('trend', 0) if isinstance(btc_short, dict) else 0
    if btc_trend == -1:
        fatal_reason = "BTC 역추세"
    
    # [참고] ATR/atr 대소문자 모두 대응
    atr_val = safe_float(curr_i.get('atr', curr_i.get('ATR', 0)))
    vol_idx = (atr_val / max(1.0, curr_close)) * 100
    
    btc_p = safe_float(curr_i.get('btc_close', 0))
    btc_prev_p = safe_float(prev_i.get('btc_close', 0))
    if btc_prev_p > 0 and btc_p < btc_prev_p * 0.995: fatal_reason = "BTC????"

    vol_mult = get_constrained_value('vol_multiple_small' if tier == "Small (High Vol)" else 'vol_multiple_major', p_dict, mode)
    if curr_vol < vol_sma * vol_mult: fatal_reason = "????????"
    elif vol_idx < 0.3: fatal_reason = "??????" # 0.5 -> 0.3 ??
    elif safe_float(curr_i.get('bb_bw', curr_i.get('bollinger_bandwidth', 0))) < 0.5: fatal_reason = "?????"
    elif mode == "QUANTUM" and mtf_trend == -1: fatal_reason = "?????(Q)"
    elif mode == "CLASSIC" and mtf_trend == 1: fatal_reason = "?????(C)"
    elif mode == "CLASSIC" and mtf_trend == -1 and rsi_live > 25: fatal_reason = "???????"

    # ?? [4] Foundation Score ?? ?????????????????????????????????????
    earned_score, total_w = 0.0, 0.0001
    valid_indicator_count = 0
    
    for name in logic_list:
        w = safe_float(weights.get(name, 1.0), 1.0)
        if tier not in ["Major", "Mid"] and name in ['supertrend', 'stochastics']: w *= 1.5
        
        s_raw = get_strategy_score(name, prev_i, curr_i, curr_close, mode=mode)
        
        # 지표별 조건 (임계값 가변화)
        if name == 'rsi' and safe_float(curr_i.get('rsi', 50)) > get_constrained_value('rsi_high_thr', p_dict, mode):
            s_raw *= get_constrained_value('rsi_overbought_mult', p_dict, mode)
        if name == 'macd' and safe_float(curr_i.get('macd_h', 0)) <= 0:
            s_raw *= get_constrained_value('macd_negative_mult', p_dict, mode)
            
        s = s_raw * vas_mult
        
        # ??? ?? ?? ??
        if tier == "Major":
            ema60 = safe_float(curr_i.get('ema60', 0))
            if curr_close < ema60 or rsi_live < 50:
                s *= get_constrained_value('major_weak_mult', p_dict, mode)
        elif is_meme:
            if curr_close < safe_float(curr_i.get('ema20', 0)):
                s *= get_constrained_value('meme_bad_mult', p_dict, mode)
                
        earned_score += (s * w)
        total_w += w
        valid_indicator_count += 1

    # Sniper Boost
    if (earned_score / total_w) >= 85.0:
        foundation_mult *= (1.0 + get_constrained_value('sniper_boost', p_dict, mode))
        
    foundation_score = (earned_score / total_w) * foundation_mult
    if tier not in ["Major", "Mid"] and valid_indicator_count >= 2:
        foundation_score *= get_constrained_value('alt_accel_mult', p_dict, mode)

    # ?? [5] Bonus Score ?? ??????????????????????????????????????????
    bonus_score = 0.0
    cvd_improving = safe_float(curr_i.get('cvd', 0)) > safe_float(prev_i.get('cvd', 0))
    
    # MTF
    if mode == "QUANTUM" and mtf_trend == 1: bonus_score += get_constrained_value('mtf_bonus_q', p_dict, mode)
    if mode == "QUANTUM" and mtf_trend == -1: bonus_score -= get_constrained_value('mtf_penalty_q', p_dict, mode)
    
    # Wick
    upper_shadow = safe_float(curr_i.get('high', 0)) - max(curr_close, safe_float(curr_i.get('open', 0)))
    body_size = abs(curr_close - safe_float(curr_i.get('open', 0)))
    wick_ratio_thr = get_constrained_value('wick_ratio_meme' if is_meme else 'wick_ratio_major', p_dict, mode)
    if upper_shadow > body_size * wick_ratio_thr:
        bonus_score -= get_constrained_value('wick_penalty', p_dict, mode)
        
    if mode == "QUANTUM":
        # BB Breakout
        bb_u = safe_float(curr_i.get('bb_u', 0))
        if curr_close >= bb_u and bb_u > 0:
            bonus_score += get_constrained_value('bb_breakout_bonus', p_dict, mode) * min(1.0, ((curr_close-bb_u)/bb_u)*100/3.0)
        # SMA Align
        sma_short = safe_float(curr_i.get('ema20', 0))
        sma_long = safe_float(curr_i.get('ema60', 0))
        if sma_short > sma_long and curr_close > sma_short:
            bonus_score += get_constrained_value('sma_align_bonus', p_dict, mode)
    else: # CLASSIC
        # RSI Oversold
        if rsi_live < 35:
            bonus_score += get_constrained_value('rsi_oversold_bonus', p_dict, mode) * calculate_grad(rsi_live, 25, 10, 'DECREASE')
        # SMA Gap
        slv = safe_float(curr_i.get('sma_long', 0))
        if slv > 0:
            gap = ((curr_close - slv)/slv)*100
            if gap < -7.0: bonus_score += get_constrained_value('sma_gap_bonus', p_dict, mode)
        if cvd_improving: bonus_score += get_constrained_value('cvd_bonus', p_dict, mode)

    # ?? ???
    rsi_diff = rsi_live - safe_float(prev_i.get('rsi', 0))
    if tier in ["Major", "Mid"] and 0 < rsi_diff < 2.0:
        bonus_score -= get_constrained_value('rsi_slope_penalty', p_dict, mode)
        
    macd_conv = safe_float(curr_i.get('macd_h', 0)) > safe_float(prev_i.get('macd_h', 0))
    if macd_conv and rsi_diff > 0:
        bonus_score += get_constrained_value('osc_conv_bonus_alt' if tier not in ["Major", "Mid"] else 'osc_conv_bonus_maj', p_dict, mode)
        
    if safe_float(curr_i.get('bb_bw', 0)) > safe_float(prev_i.get('bb_bw', 0)):
        bonus_score += get_constrained_value('squeeze_bonus_alt' if tier not in ["Major", "Mid"] else 'squeeze_bonus_maj', p_dict, mode)

    if tier == "Mid" and curr_close < safe_float(curr_i.get('ema20', 0)) * 1.005:
        bonus_score -= get_constrained_value('mid_sma_penalty', p_dict, mode)

    if rsi_diff > 0 and safe_float(curr_i.get('macd', 0)) < safe_float(prev_i.get('macd', 0)):
        bonus_score -= get_constrained_value('divergence_penalty', p_dict, mode)

    if tier not in ["Major", "Mid"]:
        st_val = safe_float(curr_i.get('ST_DIR', 0))
        psar_val = safe_float(curr_i.get('psar', 0)) < curr_close
        if st_val == 1 and psar_val:
            bonus_score += get_constrained_value('st_psar_bonus', p_dict, mode)

    bonus_impact = 1.0
    if fgi_val >= 65 and tier in ["Major", "Mid"]:
        bonus_impact = get_constrained_value('fgi_bonus_dampen', p_dict, mode)
        
    # ── [전략 로직 개선 1: 스나이퍼 컨플루언스 부스트] ─────────────────────
    # RSI 과매도 + BB 하단 이탈 + CVD 개선이 동시에 발생하면 강력한 반등 신호로 간주
    bb_l = safe_float(curr_i.get('bb_l', 0))
    if rsi_live < 32 and curr_close <= bb_l and bb_l > 0:
        if cvd_improving or (curr_vol / vol_sma) > 1.8:
            bonus_score += get_constrained_value('sniper_confluence_bonus', p_dict, mode)

    total_score = foundation_score + (bonus_score * bonus_impact)

    # ?? [6] ?? CVD ??? ? ??? ?? ??????????????????????????????
    if mode == "QUANTUM":
        cvd_val = safe_float(curr_i.get('cvd', 0))
        if cvd_val < 0:
            total_score -= get_constrained_value('cvd_penalty_q', p_dict, mode) * min(1.0, abs(cvd_val)/1000.0)
    else:
        cvd_val = safe_float(curr_i.get('cvd', 0))
        if cvd_val < 0: total_score -= get_constrained_value('cvd_penalty_c', p_dict, mode)
        if cvd_val < safe_float(prev_i.get('cvd', 0)):
            total_score -= get_constrained_value('cvd_slope_penalty_c', p_dict, mode)
        if (curr_vol / vol_sma) < 1.1:
            total_score -= get_constrained_value('vol_ratio_penalty_c', p_dict, mode)

    suggested_threshold = get_constrained_value('pass_score_threshold', p_dict, mode)
    if tier == "Small (High Vol)" or is_meme:
        suggested_threshold += 5.0

    return round(max(0.0, min(100.0, total_score)), 1), fatal_reason, suggested_threshold, mode

def evaluate_strategy_sync(ticker, prev_i, curr_i, fgi_val, mtf_data, p_dict, btc_short=None):
    """
    Classic/Quantum ? ??? ?? ??????? ? ?? ??? ??? ??? ?????.
    """
    c_res = run_sub_eval_logic(ticker, prev_i, curr_i, fgi_val, mtf_data, "CLASSIC", p_dict, btc_short=btc_short)
    q_res = run_sub_eval_logic(ticker, prev_i, curr_i, fgi_val, mtf_data, "QUANTUM", p_dict, btc_short=btc_short)
    
    return c_res if c_res[0] >= q_res[0] else q_res
