// Super Admin dashboard charts. Data comes from window.SCMOVS_CHARTS (set in the template; real database numbers).
(function () {
    var C = window.SCMOVS_charts, data = window.SCMOVS_CHARTS;
    if (!C || !data) return;
    var money = function (v) { return "\u20B1" + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2 }); };

    // 1) Election participation: horizontal bars (election names are long). Aggregate counts only.
    C.hbar("chart-participation", data.participation.labels, [
        { label: "Eligible voters", data: data.participation.eligible, color: "#93c5fd" },
        { label: "Votes cast", data: data.participation.cast, color: "#1e3a8a" }
    ], { emptyText: "No election has opened yet.", maxLabel: 30, tooltip: {
        afterLabel: function (c) {
            if (c.dataset.label !== "Votes cast") return "";
            var el = data.participation.eligible[c.dataIndex];
            return el ? (Math.round(c.parsed.x * 1000 / el) / 10) + "% of eligible voters" : "";
        } } });

    // 2) Students by department: pie with counts + percentages
    C.pie("chart-departments", data.departments.labels, data.departments.values, { noun: "students", emptyText: "No students yet." });

    // 3) Events and projects by status: horizontal bars
    C.hbar("chart-status", data.status.labels, [
        { label: "Events", data: data.status.events, color: "#2563eb" },
        { label: "Projects", data: data.status.projects, color: "#f59e0b" }
    ], { emptyText: "No events or projects yet." });

    // 4) Budget vs expenses (three bars, stays vertical)
    C.vbar("chart-finance", data.finance.labels, [{ label: "Amount", data: data.finance.values, color: "#1e3a8a" }], {
        yTicks: { callback: function (v) { return "\u20B1" + Number(v).toLocaleString(); } },
        tooltip: { label: function (c) { return " " + money(c.parsed.y); } }, emptyText: "No approved budgets yet." });
    var fin = window.Chart && Chart.getChart("chart-finance");
    if (fin) { fin.data.datasets[0].backgroundColor = ["#1e3a8a", "#ef4444", "#10b981"]; fin.update("none"); }
})();
