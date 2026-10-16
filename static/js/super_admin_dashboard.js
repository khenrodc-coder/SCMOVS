// Draws the Super Admin dashboard charts. Data comes from window.SCMOVS_CHARTS (set in the template).
(function () {
    if (typeof Chart === "undefined" || !window.SCMOVS_CHARTS) return;

    var data = window.SCMOVS_CHARTS;
    var colors = ["#1e3a8a", "#2563eb", "#60a5fa", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"];

    // Draw a chart, or show "No data yet" when every value is zero.
    function makeChart(canvasId, config, allValues) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        var hasData = allValues.some(function (v) { return v !== 0; });
        if (!hasData) {
            canvas.parentElement.innerHTML =
                '<p class="h-full flex items-center justify-center text-sm text-slate-500">No data yet.</p>';
            return;
        }
        new Chart(canvas, config);
    }

    var countScale = { y: { beginAtZero: true, ticks: { precision: 0 } } };

    // 1) Students by department
    makeChart("chart-departments", {
        type: "doughnut",
        data: {
            labels: data.departments.labels,
            datasets: [{ data: data.departments.values, backgroundColor: colors }]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } }
    }, data.departments.values);

    // 2) Election participation (aggregate numbers only)
    makeChart("chart-participation", {
        type: "bar",
        data: {
            labels: data.participation.labels,
            datasets: [
                { label: "Eligible voters", data: data.participation.eligible, backgroundColor: "#93c5fd" },
                { label: "Votes cast", data: data.participation.cast, backgroundColor: "#1e3a8a" }
            ]
        },
        options: { responsive: true, maintainAspectRatio: false, scales: countScale }
    }, data.participation.eligible.concat(data.participation.cast));

    // 3) Events and projects by status
    makeChart("chart-status", {
        type: "bar",
        data: {
            labels: data.status.labels,
            datasets: [
                { label: "Events", data: data.status.events, backgroundColor: "#2563eb" },
                { label: "Projects", data: data.status.projects, backgroundColor: "#f59e0b" }
            ]
        },
        options: { responsive: true, maintainAspectRatio: false, scales: countScale }
    }, data.status.events.concat(data.status.projects));

    // 4) Budget vs expenses
    makeChart("chart-finance", {
        type: "bar",
        data: {
            labels: data.finance.labels,
            datasets: [{ label: "Amount", data: data.finance.values, backgroundColor: ["#1e3a8a", "#ef4444", "#10b981"] }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: true } }
        }
    }, data.finance.values);
})();