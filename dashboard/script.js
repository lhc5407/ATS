// Constants & Globals
const API_BASE = '/api';
let profitChart = null;
let profitData = [];
let timeLabels = [];

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
            labels: timeLabels,
            datasets: [{
                label: 'Total Realized Profit (KRW)',
                data: profitData,
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
        const response = await fetch(`${API_BASE}/dashboard`);
        if (!response.ok) throw new Error('API Error');
        const data = await response.json();
        
        updateUI(data);
    } catch (error) {
        console.error("Failed to fetch dashboard data:", error);
        document.getElementById('system-status-text').textContent = "Disconnected";
        document.getElementById('system-status-dot').className = "dot pnl-negative";
    }
}

function updateUI(data) {
    // 1. System Status
    document.getElementById('system-status-text').textContent = "Online";
    document.getElementById('system-status-dot').className = "dot pulse-green";
    
    document.getElementById('regime-status').textContent = data.system_status || "Initializing...";
    
    const btcEl = document.getElementById('btc-trend');
    btcEl.textContent = data.btc_trend || "Unknown";
    btcEl.className = (data.btc_trend === "단기 상승" || data.btc_trend === "Bullish") ? "neon-text" : "neon-purple";

    // 2. Stats Row
    document.getElementById('win-rate').textContent = `${data.win_rate.toFixed(1)}%`;
    
    // Format KRW with commas
    const formattedProfit = new Intl.NumberFormat('ko-KR').format(Math.floor(data.total_profit));
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
            
            const html = `
                <div class="trade-item">
                    <div class="trade-info">
                        <h4>${trade.ticker} ${modeIcon}</h4>
                        <p>Entry: ${new Intl.NumberFormat('ko-KR').format(trade.entry_price)} KRW</p>
                        <p>Score: ${trade.score}</p>
                    </div>
                    <div class="trade-pnl ${pnlClass}">
                        ${pnlSign}${trade.pnl_pct.toFixed(2)}%
                    </div>
                </div>
            `;
            tradeList.insertAdjacentHTML('beforeend', html);
        });
    }

    // 4. Update Chart
    const now = new Date();
    const timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
    
    timeLabels.push(timeStr);
    profitData.push(data.total_profit);
    
    // Keep only last 30 data points for performance and clarity
    if (timeLabels.length > 30) {
        timeLabels.shift();
        profitData.shift();
    }
    
    if (profitChart) {
        profitChart.update();
    }
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    
    // Initial fetch
    fetchDashboardData();
    
    // Set interval for live updates (every 5 seconds)
    setInterval(fetchDashboardData, 5000);
});
