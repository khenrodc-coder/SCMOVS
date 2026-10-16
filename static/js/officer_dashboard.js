// Draws the Council Officer dashboard charts. Data comes from window.SCMOVS_CHARTS (set in the template).
(function () {
    if (typeof Chart === "undefined" || !window.SCMOVS_CHARTS) return;

    var data = window.SCMOVS_CHARTS;

    // Draw a chart, or show "No data yet" when every value is zero.
    function makeChart(canvasId, config, allValues) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        if (!allValues.some(function (v) { return v !== 0; })) {
            canvas.parentElement.innerHTML =
                '<p class="h-full flex items-center justify-center text-sm text-slate-500">No data yet.</p>';
            return;
        }
        new Chart(canvas, config);
    }

    // Events and projects by status
    makeChart("chart-officer-status", {
        type: "bar",
        data: {
            labels: data.status.labels,
            datasets: [
                { label: "Events", data: data.status.events, backgroundColor: "#2563eb" },
                { label: "Projects", data: data.status.projects, backgroundColor: "#f59e0b" }
            ]
        },
        options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }
    }, data.status.events.concat(data.status.projects));

    // Budget utilisation: approved budget vs approved expenses
    makeChart("chart-officer-budget", {
        type: "bar",
        data: {
            labels: data.budget.labels,
            datasets: [
                { label: "Approved budget", data: data.budget.approved, backgroundColor: "#93c5fd" },
                { label: "Approved expenses", data: data.budget.spent, backgroundColor: "#1e3a8a" }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            scales: { y: { beginAtZero: true, ticks: { callback: function (v) { return "\u20B1" + Number(v).toLocaleString(); } } } },
            plugins: { tooltip: { callbacks: { label: function (c) { return c.dataset.label + ": \u20B1" + Number(c.parsed.y).toLocaleString(undefined, { minimumFractionDigits: 2 }); } } } }
        }
    }, data.budget.approved.concat(data.budget.spent));
})();