// Super Admin dashboard charts. Data comes from window.SCMOVS_CHARTS (set in the template; real database numbers).
(function () {
    var C = window.SCMOVS_charts, data = window.SCMOVS_CHARTS;
    if (!C || !data) return;
    var F = C.fmt;

    // 1) Budget and Expenses Monitoring: line chart over time (approved amounts per month)
    var t = data.budget_trend;
    C.line("chart-budget-trend", t.labels, [
        { label: "Approved budgets", data: t.budgets, color: "#1e3a8a" },
        { label: "Approved expenses", data: t.expenses, color: "#ef4444" }
    ], {
        xTitle: "Month", yTitle: "Amount (\u20B1)", yTicks: { callback: F.pesoAxis },
        tooltip: { label: function (c) { return " " + c.dataset.label + ": " + F.peso(c.parsed.y); } },
        emptyText: "No approved budgets or expenses yet."
    });

    // 2) Open Election Voting Participation: vertical bars, voted vs. not yet voted
    var p = data.open_participation;
    C.vbar("chart-open-participation", p.labels, [
        { label: "Voted", data: p.voted, color: "#1e3a8a" },
        { label: "Not yet voted", data: p.not_voted, color: "#cbd5e1" }
    ], {
        xTitle: "Open election", yTitle: "Students", maxLabel: 18,
        tooltip: {
            label: function (c) { return " " + c.dataset.label + ": " + F.num(c.parsed.y); },
            afterBody: function (items) {
                var i = items[0].dataIndex;
                return "Participation: " + F.pct(p.voted[i], p.eligible[i]) + " of " + F.num(p.eligible[i]) + " eligible";
            }
        },
        emptyText: p.elections.length ? "The open election has no eligible students and no votes yet." : "No election is open right now."
    });
})();
