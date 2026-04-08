# 🚀 ATS-Xeon: AI-Driven Hybrid Algorithmic Trading System

**ATS-Xeon**은 거시 경제의 '날씨'를 스스로 파악하여 최적의 매매 무기를 자동으로 스위칭하는 **완전 자동화 하이브리드(Hybrid) 퀀트 트레이딩 봇**입니다. Python의 정밀한 기술적 분석(TA)과 Google Gemini AI의 고도화된 상황 판단력을 결합하여 인간의 감정이 배제된 냉철한 수익 창출을 목표로 합니다.

## 🧠 Core Philosophy: The Dual-Engine System

ATS-Xeon은 단일 전략의 한계를 극복하기 위해, 시장의 공포/탐욕 지수(FGI)와 비트코인의 단기 추세를 분석하여 다음 세 가지 모드 중 하나로 자동 전환(Regime Detection)합니다.

### 🛡️ 1. CLASSIC Mode (Deep Dip Sniper)
* **발동 조건:** FGI 35 이하 (공포장) 또는 비트코인 단기 하락세.
* **작전 철학:** "피바다에서 주워라." 끝없이 추락하는 칼날 속에서 RSI 과매도, 볼린저 밴드 하단 이탈, 패닉 셀링(투매) 거래량이 터지는 진정한 '바닥'을 찾아내어 짧고 강한 기술적 반등(V자 반등)을 저격합니다.

### 🚀 2. QUANTUM Mode (Trend Breakout)
* **발동 조건:** FGI 65 이상 (탐욕장) 또는 비트코인 단기 상승세.
* **작전 철학:** "달리는 말에 올라타라." 시장에 돈이 도는 불장에서는 바닥을 줍지 않습니다. 주요 저항선 돌파(Breakout), 강력한 거래량 동반, 정배열(SMA Crossover)을 확인하고 진입하여 추세가 꺾일 때까지 트레일링 스탑으로 수익을 극대화합니다(Let winners run).

### ⚖️ 3. HYBRID Mode (Adaptive Monitoring)
* **발동 조건:** 뚜렷한 추세가 없는 횡보/혼조세.
* **작전 철학:** 거시 지표가 애매할 때는 개별 코인의 **추세 강도(ADX)**를 측정합니다. ADX가 높은 코인은 퀀텀(돌파)의 잣대로, ADX가 낮은 코인은 클래식(바닥 줍기)의 잣대로 채점하는 마이크로 스위칭을 수행합니다.

---

## ✨ Key Features

* **AI Gatekeeper (Gemini 2.5 Flash Lite):** 파이썬 모듈이 1차로 펀더멘탈 점수를 매겨 통과시킨 코인만 AI 참모진에게 결재를 올립니다. AI는 현재 호가창 불균형, 차트 패턴, 거시 경제를 종합 분석하여 최종 매수(BUY) 또는 스킵(SKIP)을 결정합니다.
* **Fatal Flaw (하드락) 시스템:** 점수가 아무리 높아도 '하락장 속 가짜 반등', '이미 반등이 끝난 과열 상태' 등 치명적 결함(Fatal Flaw)이 발견되면 즉시 -999점 처리하여 뇌동매매를 원천 차단합니다.
* **Time-Decay & Chandelier Stop:** 매수 후 일정 시간 내에 모멘텀이 터지지 않으면 가짜 타점으로 간주해 즉각 탈출(Time-Decay)하며, 수익권 진입 시 샹들리에 추적 손절매를 가동하여 이익을 보존합니다.
* **Telegram Control Center:** 텔레그램을 통해 실시간 보고, 디버그 점수 확인, 강제 매수/매도, AI 파라미터 최적화 지시가 가능합니다.

---

## ⚙️ Configuration Guide

ATS-Xeon은 두 개의 심장(`config_classic.json`, `config_quantum.json`)을 가집니다. 각 파일은 해당 전략의 성격에 맞게 극단적으로 세팅되어야 합니다.

### 📁 1. `config_classic.json` (낙폭 과대 스나이퍼용)
공포장에서 찰나의 반등을 먹고 나오는 전략이므로 **'안전'**과 **'빠른 탈출'**에 초점이 맞춰져 있습니다.

* `scoring_modifiers`: `bonus_golden_combo`, `bonus_mtf_panic_dip` 등 공포장에서 나타나는 패닉셀에 큰 가산점을 부여합니다. 하락장에서 작동해야 하므로 `penalty_st_downtrend`(하락 추세 페널티)는 낮게 설정합니다.
* `indicator_weights`: `bollinger`(밴드 하단 이탈), `rsi`(과매도), `stochastics` 등의 역추세 오실레이터 지표에 높은 가중치를 둡니다.
* `timeout_candles`: 3~5 캔들. (떨어지는 칼날을 잡았는데 1시간 내에 반등이 안 나오면 지하실이므로 짧게 설정하여 즉시 도망칩니다.)

### 📁 2. `config_quantum.json` (추세 추종 마라토너용)
상승장에서 강력한 모멘텀을 타는 전략이므로 **'돌파 확인'**과 **'수익 극대화'**에 초점이 맞춰져 있습니다.

* `scoring_modifiers`: `bonus_volume_explosion`(거래량 폭발), `bonus_all_time_high`(신고가 돌파)에 큰 가산점을 부여합니다. 패닉 보너스는 철저히 배제합니다.
* `indicator_weights`: `bollinger_breakout`(밴드 상단 돌파), `sma_crossover`(이평선 정배열), `macd`(추세 강도) 등 추세 지표에 최고 가중치를 둡니다.
* `timeout_candles`: 10~20 캔들. (저항을 뚫은 후 매물대를 소화하고 재차 상승할 수 있도록 충분한 시간을 기다려 줍니다.)
* `target_atr_multiplier`: 4.5 ~ 6.0. (짧게 먹지 않고, 트레일링 스탑을 이용해 추세의 끝까지 발라먹도록 높게 설정합니다.)

---

## 📱 Telegram Commands

* `/보고` : 현재 자산, 통합 엔진 모드, 누적 수익, 현재 봇 상태 실시간 브리핑
* `/점수` : [디버그용] 실시간 감시 대상 종목들의 펀더멘탈 점수 및 하드락(💀) 컷오프 여부 확인
* `/시작` / `/정지` : 감시 및 매매 엔진 가동/일시 정지
* `/매수` : 스캔 대기 시간을 무시하고 즉시 정밀 스캔 1회 강제 가동
* `/매도` : 보유 중인 모든 종목 시장가 긴급 전량 청산 (패닉 셀 버튼)
* `/최적화` : AI를 호출하여 최근 승률 데이터를 기반으로 마스터 전략(가중치) 수동 튜닝
* `/제안` : 그동안 누적된 AI 매도 사후 분석 리포트(txt) 다운로드

---

## 🛠️ Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/your-username/ATS-Xeon.git](https://github.com/your-username/ATS-Xeon.git)
   cd ATS-Xeon
Install requirements:

Bash
pip install pyupbit pandas_ta websockets google-genai aiosqlite
API Keys Configuration:
config_classic.json 및 config_quantum.json 내부에 Upbit API Keys, Telegram Token, Google Gemini API Key를 입력합니다.

Run the Engine:

Bash
python ATS_Xeon.py

⚠️ Disclaimer: 본 프로젝트는 알고리즘 트레이딩 연구 및 학습 목적으로 개발되었습니다. 본 시스템을 활용한 실제 매매에서 발생하는 모든 금전적 손실에 대한 책임은 사용자 본인에게 있습니다.
