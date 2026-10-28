/* Phone-friendly tables.
 * Every list table (<table class="w-full ...">) gets class "rt-stack" and each cell gets its column name as data-label.
 * On screens under 768px the CSS in base.html turns each row into a labelled card, so NO column is hidden and nothing
 * needs sideways scrolling. On larger screens nothing changes.
 * Tables whose rows do not line up with their header (merged cells, several header rows) are left exactly as they are.
 */
(function () {
    function clean(text) { return (text || "").replace(/[\u25B2\u25BC\u2191\u2193]/g, "").replace(/\s+/g, " ").trim(); }

    function label(table) {
        if (table.classList.contains("rt-stack") || table.classList.contains("rt-skip")) return;
        var headRows = table.querySelectorAll("thead tr");
        if (headRows.length !== 1) return;
        var ths = Array.prototype.slice.call(headRows[0].children);
        if (!ths.length || ths.some(function (th) { return th.colSpan > 1; })) return;
        var labels = ths.map(function (th) { return clean(th.textContent); });
        var rows = Array.prototype.slice.call(table.querySelectorAll("tbody tr"));
        for (var i = 0; i < rows.length; i++) {
            var cells = Array.prototype.slice.call(rows[i].children);
            if (cells.length === 1 && cells[0].colSpan > 1) continue;                 // "nothing found" row
            if (cells.length !== labels.length) return;                                // does not line up: do not touch this table
        }
        rows.forEach(function (row) {
            var cells = Array.prototype.slice.call(row.children);
            if (cells.length === 1 && cells[0].colSpan > 1) { row.classList.add("rt-empty"); return; }
            cells.forEach(function (td, n) { td.setAttribute("data-label", labels[n]); });
        });
        table.classList.add("rt-stack");
    }

    function run(scope) { (scope || document).querySelectorAll("table.w-full").forEach(label); }
    window.SCMOVS_labelTables = run;
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { run(); }); else run();
})();
