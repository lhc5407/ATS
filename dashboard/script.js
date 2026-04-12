// Constants & Globals
const API_BASE = '/api';
let profitChart = null;
let currentTimeframe = 'all'; // Default timeframe
let logInterval = null;
let scannerInterval = null;
let currentSettings = { max_concurrent_trades: 5 }; // For blocking buy button

// Initialize Chart.js
function initChart() {
    const ctx = document.getElementById('profitChart').getContext('2d');
    
    // Gradient fill for the chart
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(0, 240, 255, 0.4)');
    gradient.addColorStop(1, 'rgba(0, 240, 255, 0.0)');

    profitChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Total Realized Profit (KRW)',
                data: [],
                borderColor: '#00F0FF',
                backgroundColor: gradient,
                borderWidth: 2,
                pointRadius: 0,
                pointHitRadius: 10,
                fill: true,
                tension: 0.4 // Smooth curves
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                zoom: {
                    pan: {
                        enabled: true,
                        mode: 'x',
                    },
                    zoom: {
                        wheel: { enabled: true },
                        pinch: { enabled: true },
                        mode: 'x',
                    }
                },
                legend: { display: false },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: 'rgba(15, 23, 42, 0.9)',
                    titleColor: '#E2E8F0',
                    bodyColor: '#00F0FF',
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1
                }
            },
            scales: {
                x: {
                    grid: { display: false, drawBorder: false },
                    ticks: { color: '#94A3B8', maxTicksLimit: 8 }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
                    ticks: { color: '#94A3B8' }
                }
            },
            interaction: {
                mode: 'nearest',
                axis: 'x',
                intersect: false
            }
        }
    });
}

// Fetch and Update Data
async function fetchDashboardData() {
    try {
        const response = await fetch(`${API_BASE}/dashboard?timeframe=${currentTimeframe}`);
        if (!response.ok) throw new Error('API Error');
        const data = await response.json();
        
        updateUI(data);
        // Hide offline overlay on success
        const overlay = document.getElementById('offline-overlay');
        if (overlay) overlay.style.display = 'none';
        
    } catch (error) {
        console.error("Failed to fetch dashboard data:", error);
        document.getElementById('system-status-text').textContent = "Disconnected";
        document.getElementById('system-status-dot').className = "dot pnl-negative";
        
        // Show offline overlay on failure
        const overlay = document.getElementById('offline-overlay');
        if (overlay) overlay.style.display = 'flex';
    }
}

function updateUI(data) {
    // 1. System Status
    document.getElementById('system-status-text').textContent = "Online";
    document.getElementById('system-status-dot').className = "dot pulse-green";
    
    document.getElementById('regime-status').textContent = data.system_status || "Initializing...";
    
    const btcTrend = data.btc_trend || "알 수 없음";
    const btcEl = document.getElementById('btc-trend');
    btcEl.textContent = btcTrend;
    btcEl.className = (btcTrend === "단기 상승" || btcTrend === "Bullish") ? "neon-text" : "neon-purple";

    // 2. Stats Row
    const winRateVal = typeof data.win_rate === 'number' ? data.win_rate : 0;
    document.getElementById('win-rate').textContent = `${winRateVal.toFixed(1)}%`;
    
    // Format KRW with commas
    const profitVal = typeof data.total_profit === 'number' ? data.total_profit : 0;
    const formattedProfit = new Intl.NumberFormat('ko-KR').format(Math.floor(profitVal));
    const profitEl = document.getElementById('total-profit');
    profitEl.textContent = `${formattedProfit} KRW`;
    
    if (data.total_profit >= 0) {
        profitEl.className = "stat-value neon-cyan";
    } else {
        profitEl.className = "stat-value pnl-negative";
    }

    // 3. Active Trades
    const tradeList = document.getElementById('trade-list');
    document.getElementById('active-trades-count').textContent = data.active_trades.length;
    
    if (data.active_trades.length === 0) {
        tradeList.innerHTML = `<div class="empty-state">No active trades currently.</div>`;
    } else {
        tradeList.innerHTML = '';
        data.active_trades.forEach(trade => {
            const pnlClass = trade.pnl_pct >= 0 ? "pnl-positive" : "pnl-negative";
            const pnlSign = trade.pnl_pct >= 0 ? "+" : "";
            const modeIcon = trade.mode === "QUANTUM" ? "🚀" : (trade.mode === "CLASSIC" ? "📉" : "⚡");
            
            // Formatting KRW
            const f = new Intl.NumberFormat('ko-KR');
            
            const item = document.createElement('div');
            item.className = 'trade-item-container';
            item.innerHTML = `
                <div class="trade-item clickable-trade">
                    <div class="trade-info">
                        <h4>${trade.ticker} ${modeIcon}</h4>
                        <div class="trade-stats-mini">
                            <span>Entry: ${f.format(trade.entry_price)}</span>
                            <span>Cur: ${f.format(trade.current_price)}</span>
                        </div>
                        <div class="trade-amounts-mini">
                            <span>Buy: ${f.format(Math.floor(trade.buy_amount))}</span>
                            <span>Val: ${f.format(Math.floor(trade.current_amount))}</span>
                        </div>
                    </div>
                    <div class="trade-right">
                        <div class="trade-score">Score: ${trade.score}</div>
                        <div class="trade-pnl ${pnlClass}">
                            ${pnlSign}${trade.pnl_pct.toFixed(2)}%
                        </div>
                        <button class="trade-btn sell-btn" style="margin-top: 8px;" onclick="executeTrade('${trade.ticker}', 'sell', event)">Sell</button>
                    </div>
                </div>
                <div class="trade-detail-reason" style="display: none;">
                    <strong>Buy Reason:</strong> ${trade.reason}
                </div>
            `;
            
            // Toggle Logic
            item.querySelector('.clickable-trade').addEventListener('click', () => {
                const detail = item.querySelector('.trade-detail-reason');
                detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
            });
            
            tradeList.appendChild(item);
        });
    }

    // 4. Update Chart (Event-Driven from API payload)
    if (data.chart_data && Array.isArray(data.chart_data)) {
        // Only update if the dataset actually changed length, to avoid unnecessary rendering 
        // and losing zoom/pan states. Note: in active trading, last item profit could change, 
        // but since we only log 'SELL' (completed trades), length comparison is safe.
        if (!window.lastChartLen || window.lastChartLen !== data.chart_data.length) {
            window.lastChartLen = data.chart_data.length;
            
            const newLabels = data.chart_data.map(d => {
                // Parse "YYYY-MM-DD HH:MM:SS"
                const t = new Date(d.time.replace(' ', 'T'));
                if (currentTimeframe === 'day') {
                    return `${t.getHours().toString().padStart(2, '0')}:${t.getMinutes().toString().padStart(2, '0')}`;
                } else {
                    return `${t.getMonth()+1}/${t.getDate()} ${t.getHours().toString().padStart(2, '0')}:${t.getMinutes().toString().padStart(2, '0')}`;
                }
            });
            const newProfits = data.chart_data.map(d => d.profit);
            
            if (profitChart) {
                profitChart.data.labels = newLabels;
                profitChart.data.datasets[0].data = newProfits;
                profitChart.update('none'); // Update without fully resetting zoom animations if possible
            }
        }
    }
}

// ==========================================
// SPA Routing & Navigation
// ==========================================
function switchView(targetId) {
    // Hide all views
    document.querySelectorAll('.view-section').forEach(el => {
        el.style.display = 'none';
        el.classList.remove('active');
    });
    
    // Show target view
    const targetEl = document.getElementById(targetId);
    if (targetEl) {
        targetEl.style.display = 'flex';
        // Need brief timeout for flex to apply before adding opacity class if we had one
        setTimeout(() => targetEl.classList.add('active'), 10);
    }
    
    // Fire specific load events
    if (targetId === 'history-view') {
        fetchHistory();
    } else if (targetId === 'settings-view') {
        fetchSettings();
    } else if (targetId === 'system-view') {
        fetchLogs();
        if (logInterval) clearInterval(logInterval);
        logInterval = setInterval(fetchLogs, 3000);
    } else if (targetId === 'scanner-view') {
        fetchScannerData();
        if (scannerInterval) clearInterval(scannerInterval);
        scannerInterval = setInterval(fetchScannerData, 10000); // 10s refresh for scanner
    }
    
    // Stop log polling if NOT in system view
    if (targetId !== 'system-view' && logInterval) {
        clearInterval(logInterval);
        logInterval = null;
    }
    if (targetId !== 'scanner-view' && scannerInterval) {
        clearInterval(scannerInterval);
        scannerInterval = null;
    }
}

// ==========================================
// History View Logic
// ==========================================
async function fetchHistory() {
    try {
        const response = await fetch(`${API_BASE}/history`);
        if (!response.ok) throw new Error('Failed to fetch history');
        const data = await response.json();
        
        const tbody = document.getElementById('history-tbody');
        tbody.innerHTML = '';
        
        if (!data.history || data.history.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No trading history available.</td></tr>`;
            return;
        }
        
        data.history.forEach((row, idx) => {
            const pnlClass = row.profit_krw >= 0 ? "pnl-positive" : "pnl-negative";
            const pnlSign = row.profit_krw >= 0 ? "+" : "";
            
            let scoreClass = 'score-mid';
            if (row.score >= 80) scoreClass = 'score-high';
            else if (row.score < 50) scoreClass = 'score-low';
            
            // Format time slightly
            const t = new Date(row.time.replace(' ', 'T'));
            const timeFormatted = `${t.getMonth()+1}/${t.getDate()} ${t.getHours().toString().padStart(2, '0')}:${t.getMinutes().toString().padStart(2, '0')}`;
            
            const tr = document.createElement('tr');
            tr.className = 'history-row';
            tr.innerHTML = `
                <td>${timeFormatted}</td>
                <td style="font-weight: 600;">${row.ticker}</td>
                <td>${row.side}</td>
                <td>${new Intl.NumberFormat('ko-KR').format(row.price)}</td>
                <td class="trade-pnl ${pnlClass}">${pnlSign}${new Intl.NumberFormat('ko-KR').format(Math.floor(row.profit_krw))}</td>
            `;
            
            // Accordion row
            const detailTr = document.createElement('tr');
            detailTr.style.display = 'none';
            detailTr.innerHTML = `
                <td colspan="5" style="padding: 0;">
                    <div class="history-details">
                        <div style="margin-bottom: 8px;">
                            <span class="score-badge ${scoreClass}">AI Score: ${row.score}</span>
                        </div>
                        <div><strong>Analysis:</strong> ${row.reason.replace(/<br>/g, ' ')}</div>
                    </div>
                </td>
            `;
            
            // Toggle logic
            tr.addEventListener('click', () => {
                detailTr.style.display = detailTr.style.display === 'none' ? 'table-row' : 'none';
            });
            
            tbody.appendChild(tr);
            tbody.appendChild(detailTr);
        });
        
    } catch (e) {
        console.error(e);
        document.getElementById('history-tbody').innerHTML = `<tr><td colspan="5" class="empty-state" style="color: var(--neon-red)">Error loading history.</td></tr>`;
    }
}

// ==========================================
// Settings View Logic
// ==========================================
async function fetchSettings() {
    try {
        const response = await fetch(`${API_BASE}/settings`);
        if (!response.ok) throw new Error('Failed to fetch settings');
        const data = await response.json();
        
        document.getElementById('set-max-trades').value = data.max_concurrent_trades || 5;
        document.getElementById('set-base-amount').value = data.base_trade_amount || 5000;
        document.getElementById('set-max-slippage').value = data.max_slippage_pct || 0.5;
        document.getElementById('set-deep-scan').value = data.deep_scan_interval || 900;
        currentSettings.max_concurrent_trades = data.max_concurrent_trades || 5;
        
    } catch (e) {
        console.error(e);
    }
}

async function saveSettings() {
    const btn = document.getElementById('btn-save-settings');
    btn.textContent = "Saving...";
    
    const payload = {
        max_concurrent_trades: parseInt(document.getElementById('set-max-trades').value),
        base_trade_amount: parseInt(document.getElementById('set-base-amount').value),
        max_slippage_pct: parseFloat(document.getElementById('set-max-slippage').value)
    };
    
    try {
        const response = await fetch(`${API_BASE}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) throw new Error('Basic settings save failed');
        
        // 2. 딥스캔 주기 전용 API 호출
        const scanPayload = { interval: parseInt(document.getElementById('set-deep-scan').value) };
        const scanRes = await fetch(`${API_BASE}/settings/deep-scan`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(scanPayload)
        });
        
        if (!scanRes.ok) throw new Error('Deep scan interval save failed');

        btn.textContent = "Saved Successfully!";
        btn.style.color = "var(--neon-green)";
        btn.style.borderColor = "var(--neon-green)";
        
        setTimeout(() => {
            btn.textContent = "Save Configuration";
            btn.style.color = "var(--neon-cyan)";
            btn.style.borderColor = "var(--neon-cyan)";
        }, 2000);
        
    } catch (e) {
        console.error(e);
        btn.textContent = "Error saving";
        btn.style.color = "var(--neon-red)";
        btn.style.borderColor = "var(--neon-red)";
        setTimeout(() => {
            btn.textContent = "Save Configuration";
            btn.style.color = "var(--neon-cyan)";
            btn.style.borderColor = "var(--neon-cyan)";
        }, 2000);
    }
}

// ==========================================
// System Control & Logs Logic
// ==========================================
async function fetchLogs() {
    try {
        const response = await fetch(`${API_BASE}/logs`);
        const data = await response.json();
        const terminal = document.getElementById('log-terminal');
        if (terminal && typeof data.logs === 'string') {
            // Updated comparison and assignment for robustness
            if (terminal.textContent !== data.logs) {
                terminal.textContent = data.logs;
                // Auto scroll to bottom
                terminal.scrollTop = terminal.scrollHeight;
            }
        }
    } catch (error) {
        console.error("Failed to fetch logs:", error);
    }
}

async function controlSystem(action) {
    const confirmMsg = action === 'restart' 
        ? "정말로 엔진을 재시작하시겠습니까? (약 5초 내외 소요)" 
        : "정말로 시스템을 완전히 종료하시겠습니까? (다시 켜려면 서버에서 직접 실행해야 합니다)";
    
    if (!confirm(confirmMsg)) return;

    try {
        const response = await fetch(`${API_BASE}/control`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action })
        });
        const data = await response.json();
        if (data.status === 'success') {
            alert(data.message);
            if (action === 'shutdown') {
                document.body.innerHTML = `<div style="display:flex; justify-content:center; align-items:center; height:100vh; color:#fff; font-family:sans-serif;">
                    <div style="text-align:center;">
                        <h1>System Offline</h1>
                        <p>시스템이 완전히 종료되었습니다. 대시보드를 닫으셔도 됩니다.</p>
                    </div>
                </div>`;
            }
        }
    } catch (error) {
        console.error(`Failed to ${action} system:`, error);
        alert(`${action} 요청 처리 중 오류가 발생했습니다.`);
    }
}

// ==========================================
// Initialization
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    
    // Setup timeframe filter buttons
    const filterBtns = document.querySelectorAll('.filter-btn');
    filterBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            filterBtns.forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            
            currentTimeframe = e.target.getAttribute('data-timeframe');
            window.lastChartLen = 0; 
            
            if (profitChart) {
                profitChart.resetZoom(); 
            }
            
            fetchDashboardData();
        });
    });

    // Setup Navigation
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            navItems.forEach(n => n.classList.remove('active'));
            item.classList.add('active');
            
            const target = item.getAttribute('data-target');
            if (target) {
                switchView(target);
            }
        });
    });
    
    // Connect Save Button
    document.getElementById('btn-save-settings').addEventListener('click', saveSettings);

    // Connect System Control Buttons
    const restartBtn = document.getElementById('btn-restart');
    const shutdownBtn = document.getElementById('btn-shutdown');
    if (restartBtn) restartBtn.addEventListener('click', () => controlSystem('restart'));
    if (shutdownBtn) shutdownBtn.addEventListener('click', () => controlSystem('shutdown'));
    

    // Initial fetch
    fetchDashboardData();
    
    // Live updates (Dashboard Stats & Active Positions: 10 seconds)
    setInterval(() => {
        const dash = document.getElementById('dashboard-view');
        const hist = document.getElementById('history-view');
        // 대시보드나 히스토리 뷰를 보고 있을 때만 갱신 (효율성)
        if ((dash && dash.style.display !== 'none') || (hist && hist.style.display !== 'none')) {
            fetchDashboardData();
        }
    }, 10000); 
    
    // Initial settings fetch to get trade limits
    fetchSettings();
});

// ==========================================
// Scanner View Logic
// ==========================================
async function fetchScannerData() {
    try {
        const response = await fetch(`${API_BASE}/scanner`);
        if (!response.ok) throw new Error('Scanner API fail');
        const data = await response.json();
        
        const tbody = document.getElementById('scanner-tbody');
        tbody.innerHTML = '';
        
        if (data.timestamp > 0) {
            const lastScan = new Date(data.timestamp * 1000);
            document.getElementById('scanner-update-time').textContent = `Last scan: ${lastScan.toLocaleTimeString()}`;
        }

        if (!data.scanner || data.scanner.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No scan results yet. Start scan first.</td></tr>`;
            return;
        }

        // Check current active count
        const activeCount = parseInt(document.getElementById('active-trades-count').textContent) || 0;
        const canBuy = activeCount < currentSettings.max_concurrent_trades;

        data.scanner.forEach(item => {
            const scoreClass = item.score >= 80 ? 'score-high' : (item.score >= 60 ? 'score-mid' : 'score-low');
            const tr = document.createElement('tr');
            tr.className = 'scanner-row';
            
            // Format price
            const f = new Intl.NumberFormat('ko-KR');
            const priceStr = f.format(item.price);
            
            // 🟢 [수정] 결격 사유(fatal_flaw)를 전용 컬럼으로 분리
            let flawContent = '<span class="text-muted">PASS</span>';
            if (item.fatal_flaw && item.fatal_flaw !== 'PASS') {
                flawContent = `<span style="color: var(--neon-red); font-size: 11px; font-weight: 600;">🛑 ${item.fatal_flaw}</span>`;
            }

            tr.innerHTML = `
                <td>
                    <div style="font-weight: 600;">${item.ticker}</div>
                    <div class="scanner-info">${item.mode}</div>
                </td>
                <td>${priceStr}</td>
                <td>
                    <span class="score-badge ${scoreClass}">${item.score.toFixed(1)}</span>
                </td>
                <td><span class="mtf-badge">${item.mtf}</span></td>
                <td>${flawContent}</td>
                <td>
                    <button class="trade-btn buy-btn" 
                        ${canBuy ? '' : 'disabled title="Max trades reached"'} 
                        onclick="executeTrade('${item.ticker}', 'buy', event)">Buy</button>
                </td>
            `;
            
            // Tooltip row or reason
            const reasonTr = document.createElement('tr');
            reasonTr.style.display = 'none';
            reasonTr.innerHTML = `<td colspan="6" class="history-details"><strong>Scan Detail:</strong> ${item.reason}</td>`;
            
            tr.addEventListener('click', (e) => {
                if(e.target.tagName !== 'BUTTON') {
                    reasonTr.style.display = reasonTr.style.display === 'none' ? 'table-row' : 'none';
                }
            });
            
            tbody.appendChild(tr);
            tbody.appendChild(reasonTr);
        });
    } catch (e) {
        console.error("Scanner fetch error:", e);
    }
}

async function refreshScanner() {
    const btn = document.getElementById('btn-refresh-scanner');
    if (!btn) return;
    
    btn.disabled = true;
    btn.textContent = "Scanning...";
    
    try {
        const response = await fetch(`${API_BASE}/scanner/refresh`, { method: 'POST' });
        const result = await response.json();
        
        // 🟢 스캔은 백그라운드에서 돌고 있으므로, 3초 후 결과 새로고침 시도
        setTimeout(fetchScannerData, 3000);
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = "점수 갱신";
        }, 5000);
        
    } catch (e) {
        console.error("Refresh failed:", e);
        btn.disabled = false;
        btn.textContent = "점수 갱신";
    }
}

// ==========================================
// Manual Trading Execution
// ==========================================
async function executeTrade(ticker, action, event) {
    if (event) event.stopPropagation(); // Prevent row expand
    
    const confirmMsg = action === 'buy' 
        ? `${ticker} 종목을 즉시 매수하시겠습니까?` 
        : `${ticker} 종목을 전량 시장가 매도하시겠습니까?`;
        
    if (!confirm(confirmMsg)) return;
    
    try {
        const response = await fetch(`${API_BASE}/trade`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticker, action })
        });
        
        const result = await response.json();
        if (result.status === 'success') {
            alert(result.message);
            // Refresh data
            fetchDashboardData();
            if (document.getElementById('scanner-view').style.display !== 'none') {
                fetchScannerData();
            }
        } else {
            alert(`Error: ${result.message}`);
        }
    } catch (e) {
        console.error("Trade execution error:", e);
        alert("통신 오류가 발생했습니다.");
    }
}
