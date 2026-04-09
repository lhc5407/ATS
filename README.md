# 🚀 ATS-Xeon: AI-Driven Hybrid Algorithmic Trading System

**ATS-Xeon**은 거시 경제의 '날씨'를 스스로 파악하여 최적의 매매 무기를 자동으로 스위칭하고, 스스로의 전략 지침을 진화시키는 **차세대 완전 자동화 하이브리드(Hybrid) 트레이딩 엔진**입니다. 기술적 분석(TA)의 정밀함과 Google Gemini AI의 고도화된 전략 수립 능력을 결합하여, 인간의 개입 없는 자율 매매를 수행합니다.

## 🧠 Core Philosophy: The Dual-Engine System

ATS-Xeon은 단일 전략의 한계를 극복하기 위해, 시장의 공포/탐욕 지수(FGI)와 비트코인의 단기 추세를 분석하여 다음 세 가지 모드 중 하나로 자동 전환(Regime Detection)합니다.

### 🛡️ 1. CLASSIC Mode (Deep Dip Sniper)
* **발동 조건:** FGI 35 이하 (공포장) 또는 비트코인 단기 하락세.
* **작전 철학:** "피바다에서 주워라." 끝없이 추락하는 칼날 속에서 RSI 과매도, 볼린저 밴드 하단 이탈, 패닉 셀링(투매) 거래량이 터지는 진정한 '바닥'을 찾아내어 짧고 강한 기술적 반등(V자 반등)을 저격합니다.

### 🚀 2. QUANTUM Mode (Trend Breakout)
* **발동 조건:** FGI 65 이상 (탐욕장) 또는 비트코인 단기 상승세.
* **작전 철학:** "달리는 말에 올라타라." 주요 저항선 돌파(Breakout)와 강력한 거래량 동반, 정배열(SMA Crossover)을 확인하고 진입하여 추세가 꺾일 때까지 트레일링 스탑으로 수익을 극대화합니다.

---

## ✨ Advanced Features (Latest Update)

* **Autonomous Evolution (진화형 지침):** 단순히 매매만 하는 것이 아니라, 매일 아침 생성되는 AI 분석 리포트를 기반으로 스스로의 `exit_plan_guideline`과 전략 프롬프트를 업데이트합니다. 인간의 개입 없이도 시장 상황에 맞춰 매도 전략을 정교화합니다.
* **BTC Surge Trigger (급등 탐지):** 웹소켓 실시간 데이터를 통해 BTC의 1분 내 1.5% 이상 변동을 감지합니다. 급격한 시세 분출 시 즉시 딥스캔을 수행하여 알트코인 매수 기회를 놓치지 않습니다.
* **High-Performance Engine:** 지표 캐시 최적화 및 비동기 처리 강화를 통해 전체 스캔 속도를 10초 이내로 단축(50종목 기준)하여 지연 없는 매매 타점을 확보합니다.
* **Fatal Flaw (하드락) 시스템:** 수동적인 점수제를 넘어, '가짜 반등'이나 '거시 추세 역행' 등의 치명적 결함 발견 시 실시간으로 진입을 차단하는 강력한 안전 장치를 가동합니다.
* **Resilient Infrastructure:** Rotating File Logging(10MB/5개), DB Timeout 안정화, WebSocket Watchdog을 통해 24/7 중단 없는 운용이 가능합니다.

---

## ⚙️ Configuration Guide

ATS-Xeon은 `config_classic.json`과 `config_quantum.json` 파일에 정의된 파라미터를 기반으로 동작합니다.

### 📁 주요 설정 파라미터
* `deep_scan_interval`: 정기 딥스캔 주기 (기본 900초 - 15분).
* `btc_surge_threshold`: 비정규 스캔을 트리거할 BTC 상승률 기준 (기본 1.5%).
* `indicator_weights`: 각 기술적 지표(RSI, MACD, BB, STOCH 등)가 점수 산출에 미치는 가중치.
* `exit_plan_guideline`: AI가 손익절 지침을 생성할 때 참고하는 핵심 원칙 (자율 진화 대상).

---

## 📱 Telegram Control Center

* `/보고` : 현재 자산, 엔진 모드, 누적 수익, 현재 봇 상태 실시간 브리핑
* `/점수` : 감시 대상 종목들의 펀더멘탈 점수 및 하드락(💀) 컷오프 여부 실시간 확인
* `/시작` / `/정지` : 매매 엔진 가동/일시 정지
* `/매수` : 강제 딥스캔 1회 즉시 실행
* `/매도` : 보유 중인 전 종목 시장가 긴급 전량 청산
* `/최적화` : AI를 호출하여 최근 승률 기반 마스터 전략 수동 튜닝

---

## 🛠️ Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/ATS-Xeon.git
   cd ATS-Xeon
   ```

2. **Install requirements:**
   ```bash
   pip install pyupbit pandas_ta websockets google-genai aiosqlite requests
   ```

3. **API Keys Configuration:**
   `config_classic.json` 및 `config_quantum.json` 내부에 Upbit API Keys, Telegram Token, Google Gemini API Key를 입력합니다.

4. **Run the Engine:**
   ```bash
   python ATS_Xeon.py
   ```

---

⚠️ **Disclaimer:** 본 프로젝트는 알고리즘 트레이딩 연구 및 학습 목적으로 개발되었습니다. 본 시스템을 활용한 실제 매매에서 발생하는 모든 금전적 손실에 대한 책임은 사용자 본인에게 있습니다.
