/* Shared Chart.js (v4) helpers: SCMOVS look, dark-mode colours, empty states, pie/bar builders.
 * Loaded after chart.umd.min.js. Charts re-colour themselves when the Super Admin toggles dark mode. */
(function () {
    if (typeof Chart === "undefined") return;
    var registry = [];
    // One formatter for every tooltip, axis and total (matches the server's |money filter: PHP peso, thousands, 2 decimals)
    var fmt = {
        num: function (v) { return Number(v || 0).toLocaleString("en-PH"); },
        peso: function (v) { return "\u20B1" + Number(v || 0).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); },
        pesoAxis: function (v) { return "\u20B1" + Number(v || 0).toLocaleString("en-PH"); },
        pct: function (part, total) { return total ? (Math.round(part * 1000 / total) / 10).toFixed(1) + "%" : "0.0%"; }
    };
    var PALETTE = ["#1e3a8a", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16", "#64748b", "#f97316"];

    function isDark() { return document.documentElement.classList.contains("dark"); }
    function colors() {
        return isDark()
            ? { text: "#cbd5e1", grid: "#2a3a5c", tip: "#0b1220", tipText: "#e2e8f0", arc: "#111a2e" }
            : { text: "#475569", grid: "#e2e8f0", tip: "#172554", tipText: "#ffffff", arc: "#ffffff" };
    }
    function defaults() {
        var c = colors();
        Chart.defaults.font.family = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
        Chart.defaults.font.size = 12;
        Chart.defaults.color = c.text;
        Chart.defaults.borderColor = c.grid;
        Chart.defaults.elements.bar.borderRadius = 5;
        Chart.defaults.plugins.legend.labels.usePointStyle = true;
        Chart.defaults.plugins.legend.labels.boxWidth = 8;
        Chart.defaults.plugins.legend.labels.padding = 14;
        Object.assign(Chart.defaults.plugins.tooltip, { backgroundColor: c.tip, titleColor: c.tipText, bodyColor: c.tipText, padding: 10, cornerRadius: 8, titleFont: { weight: "700" } });
    }
    defaults();

    function themed(color) {
        var dark = isDark();
        var swap = function (c) { return dark && c === "#1e3a8a" ? "#60a5fa" : (!dark && c === "#60a5fa" ? "#1e3a8a" : c); };
        return Array.isArray(color) ? color.map(swap) : swap(color);
    }
    function restyle(chart) {
        // Work on the RAW options we passed in. (Writing chart.options.* back onto itself makes Chart.js recurse forever.)
        var c = colors(), o = chart.config.options || (chart.config.options = {});
        var scales = o.scales || {};
        Object.keys(scales).forEach(function (k) {
            var sc = scales[k]; sc.ticks = sc.ticks || {}; sc.grid = sc.grid || {};
            sc.ticks.color = c.text; sc.grid.color = c.grid;
            if (sc.title) sc.title.color = c.text;
        });
        o.plugins = o.plugins || {};
        var legend = o.plugins.legend = o.plugins.legend || {}; legend.labels = legend.labels || {}; legend.labels.color = c.text;
        var tip = o.plugins.tooltip = o.plugins.tooltip || {};
        tip.backgroundColor = c.tip; tip.titleColor = c.tipText; tip.bodyColor = c.tipText;
        chart.data.datasets.forEach(function (d) {
            ["backgroundColor", "pointBackgroundColor"].forEach(function (k) { if (d[k]) d[k] = themed(d[k]); });
            if (chart.config.type === "pie" || chart.config.type === "doughnut") d.borderColor = c.arc; else if (d.borderColor) d.borderColor = themed(d.borderColor);
        });
        chart.update("none");
    }
    window.addEventListener("scmovs:theme", function () { defaults(); registry.forEach(restyle); });

    function empty(canvas, text) {
        canvas.parentElement.innerHTML = '<p class="flex h-full min-h-[120px] items-center justify-center text-sm text-slate-500">' + text + "</p>";
    }
    function make(canvasId, config, values, emptyText) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return null;
        if (!values.some(function (v) { return v !== 0; })) { empty(canvas, emptyText || "No data yet."); return null; }
        var chart = new Chart(canvas, config); registry.push(chart); restyle(chart); return chart;
    }
    // Wrap a long label onto up to 3 short lines (Chart.js draws an array as a multi-line tick)
    function wrap(label, width) {
        var words = String(label).split(/\s+/), lines = [], line = "";
        words.forEach(function (w) {
            if ((line + " " + w).trim().length > width && line) { lines.push(line); line = w; } else { line = (line + " " + w).trim(); }
        });
        if (line) lines.push(line);
        if (lines.length > 3) { lines = lines.slice(0, 3); lines[2] = short(lines[2] + "\u2026", width); }
        return lines.map(function (l) { return short(l, width + 2); });
    }
    function short(label, n) { label = String(label); return label.length > n ? label.slice(0, n - 1) + "\u2026" : label; }
    function pct(v, total) { return total ? Math.round(v * 1000 / total) / 10 : 0; }

    /* Horizontal bar chart. series = [{label, data, color}] */
    function hbar(canvasId, labels, series, opts) {
        opts = opts || {};
        var all = []; series.forEach(function (s) { all = all.concat(s.data); });
        return make(canvasId, {
            type: "bar",
            data: { labels: labels, datasets: series.map(function (s) { return { label: s.label, data: s.data, backgroundColor: s.color, maxBarThickness: 22 }; }) },
            options: {
                indexAxis: "y", responsive: true, maintainAspectRatio: false,
                layout: { padding: { right: 12 } },
                scales: {
                    x: { beginAtZero: true, ticks: Object.assign({ precision: 0 }, opts.xTicks || {}) },
                    y: { grid: { display: false }, ticks: { autoSkip: false, callback: function (v) { return short(this.getLabelForValue(v), opts.maxLabel || 26); } } }
                },
                plugins: {
                    legend: { display: series.length > 1, position: "bottom" },
                    tooltip: { callbacks: Object.assign({ title: function (items) { return String(labels[items[0].dataIndex]); } }, opts.tooltip || {}) }
                }
            }
        }, all, opts.emptyText);
    }

    /* Pie chart with counts and percentages in tooltips and legend. Zero slices are left out and listed in a note. */
    function pie(canvasId, labels, values, opts) {
        opts = opts || {};
        var total = values.reduce(function (a, b) { return a + b; }, 0), keep = [], zero = [];
        labels.forEach(function (l, i) { (values[i] > 0 ? keep : zero).push(i); });
        var note = document.getElementById(canvasId + "-note");
        if (note) note.textContent = zero.length && total ? "No " + (opts.noun || "students") + " yet: " + zero.map(function (i) { return labels[i]; }).join(", ") + "." : "";
        return make(canvasId, {
            type: "pie",
            data: { labels: keep.map(function (i) { return labels[i]; }),
                    datasets: [{ data: keep.map(function (i) { return values[i]; }), backgroundColor: keep.map(function (_, n) { return PALETTE[n % PALETTE.length]; }), borderWidth: 2, borderColor: colors().arc }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { position: "right", labels: { generateLabels: function (chart) {
                        var d = chart.data;
                        return d.labels.map(function (l, i) { var v = d.datasets[0].data[i]; return { text: short(l, 22) + " \u2014 " + v + " (" + pct(v, total) + "%)", fillStyle: d.datasets[0].backgroundColor[i], strokeStyle: d.datasets[0].backgroundColor[i], fontColor: colors().text, index: i, hidden: false, pointStyle: "circle" }; });
                    } } },
                    tooltip: { callbacks: { label: function (c) { return " " + c.label + ": " + c.parsed + " " + (opts.noun || "students") + " (" + pct(c.parsed, total) + "%)"; } } }
                }
            }
        }, values, opts.emptyText || "No students yet.");
    }

    function axisTitle(text) { return text ? { display: true, text: text, font: { weight: "600" } } : { display: false }; }

    /* Vertical bar chart (one or more series side by side). opts: xTitle, yTitle, yTicks, tooltip, emptyText, maxLabel */
    function vbar(id, labels, series, opts) {
        opts = opts || {}; var all = []; series.forEach(function (s) { all = all.concat(s.data); });
        return make(id, { type: "bar",
            data: { labels: labels, datasets: series.map(function (s) { return { label: s.label, data: s.data, backgroundColor: s.color, maxBarThickness: 48 }; }) },
            options: { responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: series.length > 1 || !!opts.legend, position: "bottom" },
                           tooltip: { callbacks: Object.assign({ title: function (items) { return String(labels[items[0].dataIndex]); } }, opts.tooltip || {}) } },
                scales: { x: { title: axisTitle(opts.xTitle), grid: { display: false },
                               ticks: { autoSkip: false, maxRotation: 0, callback: function (v) { return wrap(this.getLabelForValue(v), opts.maxLabel || 13); } } },
                          y: { beginAtZero: true, title: axisTitle(opts.yTitle), ticks: opts.yTicks || { precision: 0 } } } } }, all, opts.emptyText);
    }

    /* Line chart over time. series = [{label, data, color}]. opts: xTitle, yTitle, yTicks, tooltip, emptyText */
    function line(id, labels, series, opts) {
        opts = opts || {}; var all = []; series.forEach(function (s) { all = all.concat(s.data); });
        return make(id, { type: "line",
            data: { labels: labels, datasets: series.map(function (s) {
                return { label: s.label, data: s.data, borderColor: s.color, backgroundColor: s.color, pointBackgroundColor: s.color, borderWidth: 2.5, cubicInterpolationMode: "monotone", pointRadius: 3.5, pointHoverRadius: 6, fill: false };
            }) },
            options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
                plugins: { legend: { position: "bottom" }, tooltip: { callbacks: opts.tooltip || {} } },
                scales: { x: { title: axisTitle(opts.xTitle), grid: { display: false }, ticks: { autoSkip: true, maxRotation: 0 } },
                          y: { beginAtZero: true, title: axisTitle(opts.yTitle), ticks: opts.yTicks || { precision: 0 } } } } }, all, opts.emptyText);
    }

    // Resize charts when the layout width changes without a window resize (sidebar opened / closed / collapsed)
    window.addEventListener("scmovs:layout", function () { registry.forEach(function (ch) { ch.resize(); }); });

    window.SCMOVS_charts = { make: make, hbar: hbar, pie: pie, vbar: vbar, line: line, fmt: fmt, palette: PALETTE };
})();
