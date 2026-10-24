// Draws one horizontal bar chart per position. Data comes from window.SCMOVS_RESULTS (set in the template).
(function () {
    if (typeof Chart === "undefined" || !window.SCMOVS_RESULTS) return;
    var colours = { winner: "#16a34a", tie: "#d97706", not_elected: "#94a3b8" };
    window.SCMOVS_RESULTS.forEach(function (position) {
        var canvas = document.getElementById("chart-pos-" + position.id);
        if (!canvas) return;
        if (!position.votes.some(function (v) { return v > 0; })) {
            canvas.parentElement.innerHTML = '<p class="flex h-full items-center justify-center text-sm text-slate-500">No votes to chart.</p>';
            return;
        }
        new Chart(canvas, {
            type: "bar",
            data: { labels: position.labels, datasets: [{ label: "Votes", data: position.votes,
                    backgroundColor: position.outcomes.map(function (o) { return colours[o]; }) }] },
            options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
                       scales: { x: { beginAtZero: true, ticks: { precision: 0 } } } }
        });
    });
})();