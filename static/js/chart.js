function initDashboardCharts(report) {
    // Colors based on new theme
    const chartColors = [
        'rgb(0, 25, 152)', '#3b82f6', '#8b5cf6', '#ec4899', 
        '#f59e0b', '#10b981', '#14b8a6', '#64748b'
    ];

    // Category Pie Chart
    const cats = report.categories || [];
    const catLabels = cats.map(c => c.category);
    const catData = cats.map(c => c.total);

    const ctxPie = document.getElementById('categoryChart');
    if (ctxPie) {
        new Chart(ctxPie, {
            type: 'doughnut',
            data: {
                labels: catLabels,
                datasets: [{
                    data: catData,
                    backgroundColor: chartColors,
                    borderWidth: 0,
                    hoverOffset: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            font: { family: 'Outfit', size: 12 },
                            usePointStyle: true,
                            padding: 20
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                let label = context.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed !== null) {
                                    label += new Intl.NumberFormat('en-US').format(context.parsed) + ' VND';
                                }
                                return label;
                            }
                        }
                    }
                },
                cutout: '70%'
            }
        });
    }

    // Cash Flow Bar Chart
    const cf = report.cash_flow || [];
    const cfLabels = cf.map(c => c.label);
    const incomeData = cf.map(c => c.income);
    const expenseData = cf.map(c => c.expense);

    const ctxBar = document.getElementById('cashFlowChart');
    if (ctxBar) {
        new Chart(ctxBar, {
            type: 'bar',
            data: {
                labels: cfLabels,
                datasets: [
                    {
                        label: 'Income',
                        data: incomeData,
                        backgroundColor: 'rgb(0, 25, 152)',
                        borderRadius: 4,
                        barPercentage: 0.6,
                        categoryPercentage: 0.8
                    },
                    {
                        label: 'Expense',
                        data: expenseData,
                        backgroundColor: '#93c5fd', /* light blue */
                        borderRadius: 4,
                        barPercentage: 0.6,
                        categoryPercentage: 0.8
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                plugins: {
                    legend: {
                        position: 'top',
                        align: 'end',
                        labels: { font: { family: 'Outfit', size: 12 }, usePointStyle: true, boxWidth: 8 }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed.y !== null) {
                                    label += new Intl.NumberFormat('en-US').format(context.parsed.y);
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { font: { family: 'Outfit' } }
                    },
                    y: {
                        grid: { borderDash: [5, 5], color: '#f1f5f9' },
                        ticks: {
                            font: { family: 'Outfit' },
                            callback: function(value) {
                                if(value >= 1000000) return (value / 1000000) + 'M';
                                if(value >= 1000) return (value / 1000) + 'K';
                                return value;
                            }
                        }
                    }
                }
            }
        });
    }
}
