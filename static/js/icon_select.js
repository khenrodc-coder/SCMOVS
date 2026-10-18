/* Accessible dropdown with icons for each option (native <option> cannot show icons).
 * Markup comes from the icon_select macro in templates/components/modal.html.
 * Keyboard: Enter/Space/Arrow opens; Up/Down/Home/End move; Enter selects; Esc closes; type to jump.
 * The chosen value lives in a hidden <input name=...>, so normal form submission keeps working. */
(function () {
    function init(root) {
        if (root._isInit) return; root._isInit = true;
        var input = root.querySelector("input[type=hidden]"), btn = root.querySelector("button"), list = root.querySelector("[role=listbox]");
        var icon = root.querySelector("[data-is-icon]"), label = root.querySelector("[data-is-label]");
        var opts = Array.prototype.slice.call(list.querySelectorAll("[role=option]")), active = -1, typed = "", typedAt = 0;

        function paint() {
            var cur = opts.filter(function (o) { return o.getAttribute("data-value") === input.value; })[0];
            if (cur) { label.textContent = cur.textContent.trim(); icon.className = "fa-solid w-4 text-center text-slate-500 " + cur.getAttribute("data-icon"); label.classList.remove("text-slate-400"); }
            else { label.textContent = label.getAttribute("data-placeholder") || "Select…"; icon.className = "hidden"; label.classList.add("text-slate-400"); }
            opts.forEach(function (o) { o.setAttribute("aria-selected", o === cur ? "true" : "false"); o.classList.toggle("bg-blue-50", o === cur); });
        }
        function setActive(i) {
            active = Math.max(0, Math.min(opts.length - 1, i));
            opts.forEach(function (o, n) { o.classList.toggle("ring-2", n === active); o.classList.toggle("ring-blue-300", n === active); });
            opts[active].scrollIntoView({ block: "nearest" });
        }
        function open() { if (btn.disabled) return; list.hidden = false; btn.setAttribute("aria-expanded", "true"); var i = opts.findIndex(function (o) { return o.getAttribute("data-value") === input.value; }); setActive(i < 0 ? 0 : i); list.focus(); }
        function close(focusBtn) { list.hidden = true; btn.setAttribute("aria-expanded", "false"); if (focusBtn) btn.focus(); }
        function choose(i) { input.value = opts[i].getAttribute("data-value"); input.dispatchEvent(new Event("change", { bubbles: true })); paint(); close(true); }

        btn.addEventListener("click", function () { list.hidden ? open() : close(true); });
        btn.addEventListener("keydown", function (e) { if (["ArrowDown", "ArrowUp", "Enter", " "].indexOf(e.key) > -1) { e.preventDefault(); open(); } });
        list.addEventListener("keydown", function (e) {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
            else if (e.key === "Home") { e.preventDefault(); setActive(0); }
            else if (e.key === "End") { e.preventDefault(); setActive(opts.length - 1); }
            else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(active); }
            else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); }
            else if (e.key === "Tab") { close(false); }
            else if (e.key.length === 1) {
                var now = Date.now(); typed = (now - typedAt > 700 ? "" : typed) + e.key.toLowerCase(); typedAt = now;
                var hit = opts.findIndex(function (o) { return o.textContent.trim().toLowerCase().indexOf(typed) === 0; });
                if (hit > -1) setActive(hit);
            }
        });
        opts.forEach(function (o, i) { o.addEventListener("click", function () { choose(i); }); o.addEventListener("mousemove", function () { setActive(i); }); });
        document.addEventListener("click", function (e) { if (!root.contains(e.target)) close(false); });
        paint();
    }
    window.SCMOVS_initIconSelects = function (scope) { (scope || document).querySelectorAll("[data-icon-select]").forEach(init); };
    document.addEventListener("DOMContentLoaded", function () { window.SCMOVS_initIconSelects(); });
    var prev = window.SCMOVS_initModalForm;
    window.SCMOVS_initModalForm = function (form) { if (prev) prev(form); window.SCMOVS_initIconSelects(form); };
})();
