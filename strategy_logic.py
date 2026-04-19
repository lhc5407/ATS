
# strategy_logic.py
# 전용 매매 로직 통합 모듈 (ATS_Xeon, Backtest, Optimizer 공용)
# "True Elite" 스나이퍼 전략 기반

import os
import sys
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None: return default
        return float(v)
    except: return default

def get_coin_tier(ticker: str, curr_i: dict) -> str:
    # Tier 구분 로직 (ATS_Xeon과 동일)
    if any(m in ticker for m in ["BTC", "ETH", "XRP"]): return "Major"
    if any(m in ticker for m in ["SOL", "ADA", "LINK", "DOT", "MATIC"]): return "Mid"
    if any(m in ticker for m in ["DOGE", "SHIB", "PEPE"]): return "Meme"
    
    close = safe_float(curr_i.get('close', 1))
    atr = safe_float(curr_i.get('ATR') or curr_i.get('atr', 0))
    vol_idx = (atr / max(1.0, close)) * 100
    if vol_idx > 2.5: return "Small (High Vol)"
    return "Small"

# ── [절대 규칙] 실전 운영용 파라미터 제약 조건 (Optimizer에 의해 튜닝되는 기준점) ──
# 최적화기(Optimizer)가 매매 로직의 본질을 훼손하는 것을 막는 절대적 안전장치입니다.
STRAT_CONSTRAINTS = {
    "foundation_mult_q": 2.2,           # QUANTUM 모드 기본 점수 증폭
    "foundation_mult_c": 1.05,          # CLASSIC 모드 기본 점수 증폭
    "sniper_boost": 0.03,               # 85점 이상 진입 시 가중
    "mtf_bonus_q": 25.0,                # 대추세 일치 보너스
    "mtf_penalty_q": 40.0,              # 대추세 역행 패널티
    "wick_penalty": 55.0,               # 윗꼬리 패널티
    "wick_ratio_major": 1.5,            # Major 윗꼬리 비율
    "wick_ratio_meme": 1.0,             # Meme 윗꼬리 비율
    "bb_breakout_bonus": 55.0,          # BB 돌파 보너스
    "sma_align_bonus": 35.0,            # SMA 정배열 보너스
    "rsi_oversold_bonus": 55.0,         # RSI 과매도 보너스
    "sma_gap_bonus": 30.0,              # SMA 이격 보너스
    "cvd_bonus": 25.0,                  # CVD 개선 보너스
    "osc_conv_bonus_alt": 15.0,         # 오실레이터 수렴 (Alt)
    "osc_conv_bonus_maj": 8.5,          # 오실레이터 수렴 (Major)
    "sma_above_bonus": 5.0,             # SMA 위 보너스
    "squeeze_bonus_alt": 12.0,          # 스퀴즈 분출 (Alt)
    "squeeze_bonus_maj": 5.0,           # 스퀴즈 분출 (Major)
    "st_psar_bonus": 15.0,              # ST+PSAR 확인 보너스
    "mid_sma_penalty": 20.0,            # Mid SMA 저항 패널티
    "rsi_slope_penalty": 15.0,          # RSI 기울기 패널티
    "divergence_penalty": 15.0,         # 불일치 패널티
    "fgi_bonus_dampen": 0.8,            # FGI 과열 감쇄
    "vas_mult_major": 1.08,             # Major 지표 승수
    "vas_mult_mid": 1.05,               # Mid 지표 승수
    "alt_accel_mult": 1.15,             # Alt 가속 승수
    "rsi_overbought_mult": 0.5,         # RSI 과매수 감쇄
    "macd_negative_mult": 0.6,          # MACD 음수 감쇄
    "major_weak_mult": 0.2,             # Major 약세 필터
    "meme_bad_mult": 0.01,              # Meme 위험 필터
    "vol_multiple_small": 1.2,          # Small 거래량 임계 (2.2 -> 1.2로 완화)
    "vol_multiple_major": 1.0,          # Major 거래량 임계 (1.5 -> 1.0으로 완화)
    "cvd_penalty_q": 20.0,              # QUANTUM CVD 패널티
    "cvd_penalty_c": 8.0,               # CLASSIC CVD 패널티
    "cvd_slope_penalty_c": 12.0,        # CLASSIC CVD 기울기 패널티
    "vol_ratio_penalty_c": 10.0,        # CLASSIC 거래량 비율 패널티
    "pass_score_threshold": 80.0,       # 진입 임계값 (85.0 -> 80.0 완화)
}

def clamp_value(val, min_v, max_v, default=0.0):
    v = safe_float(val, default)
    return max(min_v, min(v, max_v))

def get_constrained_value(key, p_dict, mode="QUANTUM"):
    """
    파라미터 값을 가져오되, 최적화 중에는 자유 범위를 허용하고 실전에서는 안전 범위를 보장합니다.
    """
    base_val = STRAT_CONSTRAINTS.get(key, 0.0)
    
    # [수정] 제약 범위 대폭 완화 (±50% ~ ±100%)
    # 최적화 중에 '동일 결과'가 나오는 것을 방지하기 위해 탐색 범위를 넓힙니다.
    if base_val == 0.0:
        min_v, max_v = 0.0, 50.0  # 0이었던 것도 보너스 등은 확장 가능
    elif abs(base_val) < 0.1:
        min_v = 0.0
        max_v = max(0.5, base_val * 5.0)
    else:
        min_v = base_val * 0.3    # 하한 -70%
        max_v = base_val * 3.0    # 상한 +200% (파운데이션 승수 등 고려)
        
    if hasattr(p_dict, key):
        val = getattr(p_dict, key)
    elif isinstance(p_dict, dict):
        val = p_dict.get(key, base_val)
    else:
        val = base_val
        
    return clamp_value(val, min_v, max_v, base_val)

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
        if name == "supertrend": return 95.0 if curr.get('ST_DIR', 1) == 1 else 0.0
        
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
    target_atr_multiplier = exit_plan.get('target_atr_multiplier', 4.5)
    if entry_score >= 90.0: target_atr_multiplier *= 1.2
    
    base_tp_pct = (entry_atr * target_atr_multiplier / avg_p) * 100 if entry_atr > 0 and avg_p > 0 else 3.5
    tp_target = base_tp_pct * (0.4 if scale_out_step == 0 else 1.0)
    
    max_p_rate = (t.get('high_p', avg_p) / avg_p - 1) * 100 if avg_p > 0 else 0
    current_atr_mult = exit_plan.get('atr_mult', strat_config.get('atr_multiplier_for_stoploss', 2.0))
    dynamic_mult = current_atr_mult * (0.3 if max_p_rate >= 5.0 else (0.5 if max_p_rate >= 3.0 else (0.7 if max_p_rate >= 1.0 else 1.0)))
    
    atr_stop = t.get('high_p', avg_p) - (entry_atr * dynamic_mult)
    chandelier_stop = t.get('high_p', avg_p) * 0.965 if max_p_rate >= 3.0 else 0
    
    hard_breakeven_floor = 0
    if max_p_rate >= 4.0: hard_breakeven_floor = avg_p * 1.025
    elif max_p_rate >= 1.0: hard_breakeven_floor = avg_p * 1.010
    
    stop_p = max(atr_stop, chandelier_stop, hard_breakeven_floor, avg_p * 0.965)

    sell_score_threshold = safe_float(strat_config.get('sell_score_threshold', 45.0))
    is_fundamental_broken = (ma_live_score < sell_score_threshold and curr_p_rate < -1.0)

    sell_conditions = [
        (curr_p_rate <= -1.5 or real_price <= stop_p, "시스템 최종 손절", 1.0, 9, "HIGH"),
        (is_fundamental_broken, "펀더멘탈 붕괴", 1.0, 0, "HIGH"),
        (curr_p_rate >= tp_target and scale_out_step == 0, f"1차 수익 확보({tp_target:.1f}%)", 0.5, 1, "NORMAL"),
        (max_p_rate >= 1.0 and curr_p_rate < 0.1, "익절 보존 (Profit Guard)", 1.0, 9, "HIGH"),
        (elapsed_sec > full_timeout_sec and curr_p_rate < 0.0, "타임아웃 종료", 1.0, 9, "NORMAL")
    ]
    
    for condition, reason, ratio, next_step, urgency in sell_conditions:
        if condition: return True, (ratio < 1.0), ratio, reason, urgency, next_step
            
    return False, False, 0.0, "", "NORMAL", 0

def run_sub_eval_logic(ticker, prev_i, curr_i, fgi_val, mtf_data, mode, p_dict, btc_short=None):
    """
    통합 채점 로직 (FULL VER) - ATS_Xeon, Optimizer 공용
    p_dict: ScoringParams(최적화기) 혹은 직접 넘겨준 설정값 dict
    """
    is_meme = any(m in ticker for m in ["DOGE", "SHIB", "PEPE"])
    tier = get_coin_tier(ticker, curr_i)
    
    # ── [1] 지표 리스트 및 가중치 설정 ───────────────────────────────────
    # (config에서 가져오는 부분은 호출부에서 처리하여 p_dict에 병합되어 있다고 가정)
    # 여기서는 "True Elite" 기본 로직 리스트를 사용
    logic_list = ['supertrend', 'vwap', 'rsi', 'bollinger', 'macd', 'volume', 'ssl_channel', 'sma_crossover', 'ichimoku', 'stochastics', 'obv']
    if mode == "QUANTUM": logic_list.append('bollinger_breakout')
    
    # 가중치 (지표별 1.0 기본)
    weights = {} # 필요 시 p_dict에서 확장 가능
    
    curr_close = safe_float(curr_i.get('close'))
    curr_vol = safe_float(curr_i.get('volume'))
    vol_sma = safe_float(curr_i.get('vol_sma', 0.0001))

    # ── [2] 제약 조건이 적용된 파라미터 획득 ──────────────────────────────
    foundation_mult = get_constrained_value('foundation_mult_q' if mode == "QUANTUM" else 'foundation_mult_c', p_dict, mode)
    vas_mult = get_constrained_value('vas_mult_major' if tier == "Major" else 'vas_mult_mid', p_dict, mode)
    
    # ── [3] Fatal Flaw 필터 ─────────────────────────────────────────────
    fatal_reason = None
    mtf_trend = mtf_data.get('1h_trend', 0) if mtf_data else 0
    rsi_live = safe_float(curr_i.get('rsi', curr_i.get('RSI', 50)))
    
    # [수정] ATR/atr 대소문자 혼용 대응
    atr_val = safe_float(curr_i.get('atr', curr_i.get('ATR', 0)))
    vol_idx = (atr_val / max(1.0, curr_close)) * 100
    
    btc_p = safe_float(curr_i.get('btc_close', 0))
    btc_prev_p = safe_float(prev_i.get('btc_close', 0))
    if btc_prev_p > 0 and btc_p < btc_prev_p * 0.995: fatal_reason = "BTC패닉드랍"

    vol_mult = get_constrained_value('vol_multiple_small' if tier == "Small (High Vol)" else 'vol_multiple_major', p_dict, mode)
    if curr_vol < vol_sma * vol_mult: fatal_reason = "거래량에너지부족"
    elif vol_idx < 0.3: fatal_reason = "저변동성횡보" # 0.5 -> 0.3 완화
    elif safe_float(curr_i.get('bb_bw', curr_i.get('bollinger_bandwidth', 0))) < 0.5: fatal_reason = "밴드수축중"
    elif mode == "QUANTUM" and mtf_trend == -1: fatal_reason = "대추세역행(Q)"
    elif mode == "CLASSIC" and mtf_trend == 1: fatal_reason = "대추세역행(C)"
    elif mode == "CLASSIC" and mtf_trend == -1 and rsi_live > 25: fatal_reason = "하락장칼날잡기"

    # ── [4] Foundation Score 계산 ─────────────────────────────────────
    earned_score, total_w = 0.0, 0.0001
    valid_indicator_count = 0
    
    for name in logic_list:
        w = safe_float(weights.get(name, 1.0), 1.0)
        if tier not in ["Major", "Mid"] and name in ['supertrend', 'stochastics']: w *= 1.5
        
        s_raw = get_strategy_score(name, prev_i, curr_i, curr_close, mode=mode)
        
        # 특수 보정
        if name == 'rsi' and safe_float(curr_i.get('rsi', 50)) > 75:
            s_raw *= get_constrained_value('rsi_overbought_mult', p_dict, mode)
        if name == 'macd' and safe_float(curr_i.get('macd_h', 0)) <= 0:
            s_raw *= get_constrained_value('macd_negative_mult', p_dict, mode)
            
        s = s_raw * vas_mult
        
        # 티어별 추가 약세 필터
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

    # ── [5] Bonus Score 계산 ──────────────────────────────────────────
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

    # 기타 보너스
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
        
    total_score = foundation_score + (bonus_score * bonus_impact)

    # ── [6] 최종 CVD 패널티 및 임계값 설정 ──────────────────────────────
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
    Classic/Quantum 두 모드를 모두 시뮬레이션하여 더 높은 점수가 나오는 모드를 채택합니다.
    """
    c_res = run_sub_eval_logic(ticker, prev_i, curr_i, fgi_val, mtf_data, "CLASSIC", p_dict, btc_short=btc_short)
    q_res = run_sub_eval_logic(ticker, prev_i, curr_i, fgi_val, mtf_data, "QUANTUM", p_dict, btc_short=btc_short)
    
    return c_res if c_res[0] >= q_res[0] else q_res
