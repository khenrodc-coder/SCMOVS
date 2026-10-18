// Council Officer dashboard charts. Data is already limited on the server to this officer's own councils.
(function () {
    var C = window.SCMOVS_charts, data = window.SCMOVS_CHARTS;
    if (!C || !data) return;
    var peso = function (v) { return "\u20B1" + Number(v).toLocaleString(); };

    // Events and projects by status (horizontal)
    C.hbar("chart-officer-status", data.status.labels, [
        { label: "Events", data: data.status.events, color: "#2563eb" },
        { label: "Projects", data: data.status.projects, color: "#f59e0b" }
    ], { emptyText: "No events or projects yet." });

    // Budget utilisation per activity (horizontal: activity titles are long)
    C.hbar("chart-officer-budget", data.budget.labels, [
        { label: "Approved budget", data: data.budget.approved, color: "#93c5fd" },
        { label: "Approved expenses", data: data.budget.spent, color: "#1e3a8a" }
    ], { xTicks: { precision: 0, callback: peso }, emptyText: "No approved budgets yet.",
         tooltip: { label: function (c) { return " " + c.dataset.label + ": \u20B1" + Number(c.parsed.x).toLocaleString(undefined, { minimumFractionDigits: 2 }); } } });
})();
