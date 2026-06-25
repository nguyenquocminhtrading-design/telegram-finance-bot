function formatVnd(value) {
    return new Intl.NumberFormat("en-US").format(value) + " VND";
}

function destroyIfExists(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();
    return canvas;
}

function baseOptions() {
    return {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 500 },
    };
}

function drawLineChart(canvasId, labels, data, color, label = "") {
    const canvas = destroyIfExists(canvasId);
    if (!canvas) return;

    new Chart(canvas, {
        type: "line",
        data: {
            labels,
            datasets: [{
                label,
                data,
                borderColor: color,
                backgroundColor: color,
                borderWidth: 2,
                tension: 0.35,
                pointRadius: 2,
                pointHoverRadius: 4,
                fill: false,
            }],
        },
        options: {
            ...baseOptions(),
            plugins: {
                legend: { display: !!label },
                tooltip: {
                    callbacks: {
                        label: (context) => `${context.dataset.label ? context.dataset.label + ": " : ""}${formatVnd(context.parsed.y)}`,
                    },
                },
            },
            scales: {
                x: { grid: { display: false } },
                y: {
                    grid: { borderDash: [5, 5], color: "#e5e7eb" },
                    ticks: {
                        callback: (value) => {
                            if (value >= 1000000) return `${value / 1000000}M`;
                            if (value >= 1000) return `${value / 1000}K`;
                            return value;
                        },
                    },
                },
            },
        },
    });
}

function drawComparisonLineChart(canvasId, labels, seriesList) {
    const canvas = destroyIfExists(canvasId);
    if (!canvas) return;

    new Chart(canvas, {
        type: "line",
        data: {
            labels,
            datasets: seriesList.map((series) => ({
                label: series.label,
                data: series.data,
                borderColor: series.color,
                backgroundColor: series.color,
                borderWidth: 2,
                tension: 0.35,
                pointRadius: 2,
                pointHoverRadius: 4,
                fill: false,
            })),
        },
        options: {
            ...baseOptions(),
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: {
                    position: "top",
                    labels: { usePointStyle: true, boxWidth: 8 }
                },
                tooltip: {
                    callbacks: {
                        label: (context) => `${context.dataset.label}: ${formatVnd(context.parsed.y)}`,
                    },
                },
            },
            scales: {
                x: { grid: { display: false } },
                y: {
                    grid: { borderDash: [5, 5], color: "#e5e7eb" },
                    ticks: {
                        callback: (value) => {
                            if (value >= 1000000) return `${value / 1000000}M`;
                            if (value >= 1000) return `${value / 1000}K`;
                            return value;
                        },
                    },
                },
            },
        },
    });
}

function drawBarChart(canvasId, labels, incomeData, expenseData) {
    const canvas = destroyIfExists(canvasId);
    if (!canvas) return;

    new Chart(canvas, {
        type: "bar",
        data: {
            labels,
            datasets: [
                {
                    label: "Income",
                    data: incomeData,
                    backgroundColor: "rgb(0, 25, 152)",
                    borderRadius: 4,
                    barPercentage: 0.6,
                    categoryPercentage: 0.8,
                },
                {
                    label: "Expense",
                    data: expenseData,
                    backgroundColor: "#93c5fd",
                    borderRadius: 4,
                    barPercentage: 0.6,
                    categoryPercentage: 0.8,
                },
            ],
        },
        options: {
            ...baseOptions(),
            interaction: {
                mode: "index",
                intersect: false,
            },
            plugins: {
                legend: {
                    position: "top",
                    align: "end",
                    labels: { usePointStyle: true, boxWidth: 8 },
                },
                tooltip: {
                    callbacks: {
                        label: (context) => `${context.dataset.label}: ${formatVnd(context.parsed.y)}`,
                    },
                },
            },
            scales: {
                x: {
                    grid: { display: false },
                },
                y: {
                    grid: { borderDash: [5, 5], color: "#f1f5f9" },
                    ticks: {
                        callback: function(value) {
                            if (value >= 1000000) return (value / 1000000) + "M";
                            if (value >= 1000) return (value / 1000) + "K";
                            return value;
                        },
                    },
                },
            },
        },
    });
}

function drawPieChart(canvasId, data, labels) {
    const canvas = destroyIfExists(canvasId);
    if (!canvas) return;

    const chartColors = [
        "rgb(0, 25, 152)", "#3b82f6", "#8b5cf6", "#ec4899",
        "#f59e0b", "#10b981", "#14b8a6", "#64748b"
    ];

    new Chart(canvas, {
        type: "doughnut",
        data: {
            labels,
            datasets: [{
                data,
                backgroundColor: chartColors,
                borderWidth: 0,
                hoverOffset: 4,
            }],
        },
        options: {
            ...baseOptions(),
            plugins: {
                legend: {
                    position: "bottom",
                    labels: {
                        usePointStyle: true,
                        padding: 16,
                    },
                },
                tooltip: {
                    callbacks: {
                        label: (context) => `${context.label}: ${formatVnd(context.parsed)}`,
                    },
                },
            },
            cutout: "68%",
        },
    });
}

function drawPortfolioChart(canvasId, assets) {
    const active = (assets || []).filter(a => a.is_active);
    const labels = active.map(a => a.name);
    const data = active.map(a => a.current_value);
    drawPieChart(canvasId, data, labels);
}

function initDashboardCharts(report, assets) {
    const cf = report.cash_flow || [];
    const labels = cf.map(c => c.label);
    const income = cf.map(c => c.income);
    const expense = cf.map(c => c.expense);
    const net = cf.map(c => c.net);

    drawBarChart("cashFlowChart", labels, income, expense);
    drawLineChart("netBalanceChart", labels, net, "#0984e3", "Net");

    const cats = report.categories || [];
    drawPieChart("categoryChart", cats.map(c => c.total), cats.map(c => c.category));
    drawPortfolioChart("portfolioChart", assets ? assets.assets : []);
}
