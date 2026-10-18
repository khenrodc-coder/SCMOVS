/* Adds an icon to every option of every native <select> (native <option> cannot show icons).
 *
 * Progressive enhancement: the real <select> stays in the page (visually hidden, still submitted, still
 * 'required'/'disabled', still fires 'change' so existing onchange handlers keep working). The visible control
 * is an accessible combobox/listbox: Enter/Space/Arrows open, Up/Down/Home/End move, type to jump, Esc closes.
 * Opt out with data-native on a <select>. Icons are Font Awesome (already installed).
 */
(function () {
    var RULES = [
        [/super\s*admin/i, "fa-shield-halved"], [/school\s*admin/i, "fa-school"], [/council\s*officer|officer/i, "fa-user-tie"],
        [/^student|graduat/i, "fa-graduation-cap"],
        [/disqualif/i, "fa-user-slash"], [/reject|declin|denied/i, "fa-circle-xmark"], [/approv|verified/i, "fa-circle-check"],
        [/^open\b/i, "fa-circle-play"], [/clos/i, "fa-lock"], [/schedul/i, "fa-calendar-check"], [/draft/i, "fa-file-pen"],
        [/pending|submitted|review|upcoming|waiting/i, "fa-hourglass-half"], [/publish/i, "fa-bullhorn"], [/archiv/i, "fa-box-archive"],
        [/complet|done|finish/i, "fa-flag-checkered"], [/in.progress|ongoing/i, "fa-spinner"],
        [/inactive|disabled|locked|suspend|cancel/i, "fa-ban"], [/^active|enabled/i, "fa-circle-check"],
        [/college|high school|elementary|department|\bdept\b/i, "fa-building-columns"],
        [/\d{4}\s*[-\u2013]\s*\d{4}|school year/i, "fa-calendar-days"],
        [/year/i, "fa-layer-group"], [/election|ballot|vote/i, "fa-check-to-slot"], [/council/i, "fa-people-group"],
        [/position/i, "fa-briefcase"], [/login|logout|auth/i, "fa-right-to-bracket"], [/event/i, "fa-calendar-days"],
        [/project/i, "fa-diagram-project"], [/budget|expense|finance/i, "fa-wallet"], [/meeting/i, "fa-handshake"],
        [/document|file|minutes|report/i, "fa-file-lines"], [/announce/i, "fa-bullhorn"]
    ];
    var BY_NAME = { department: "fa-building-columns", department_id: "fa-building-columns", school_year: "fa-calendar-days", school_year_id: "fa-calendar-days",
        council: "fa-people-group", council_id: "fa-people-group", election: "fa-check-to-slot", election_id: "fa-check-to-slot", position: "fa-briefcase",
        position_id: "fa-briefcase", year_level: "fa-layer-group", section: "fa-users", category: "fa-tag", module: "fa-cube", action: "fa-bolt",
        type: "fa-shapes", state: "fa-toggle-on", status: "fa-circle-dot", role: "fa-user-shield", link: "fa-link", activity: "fa-list-check" };

    function iconFor(select, option) {
        var text = (option.textContent || "").trim(), value = option.value;
        if (value === "" ) return /^(all|any|no\b|select|choose|\u2014|-)/i.test(text) || !text ? "fa-list" : (BY_NAME[select.name] || "fa-list");
        for (var i = 0; i < RULES.length; i++) if (RULES[i][0].test(text) || RULES[i][0].test(value)) return RULES[i][1];
        return BY_NAME[select.name] || "fa-circle";
    }

    function enhance(select) {
        if (select._iconized || select.multiple || select.hasAttribute("data-native") || select.closest("[data-icon-select]")) return;
        select._iconized = true;
        var opts = Array.prototype.slice.call(select.options);
        var wrap = document.createElement("div"); wrap.className = "relative inline-block max-w-full align-middle"; wrap.setAttribute("data-icon-wrap", "");
        select.parentNode.insertBefore(wrap, select);
        wrap.appendChild(select);
        // keep the real select for submission/validation; hide it from view and from the tab order
        select.classList.add("sr-only"); select.tabIndex = -1; select.setAttribute("aria-hidden", "true");

        var id = select.id, labelEl = id ? document.querySelector('label[for="' + id + '"]') : null;
        var btn = document.createElement("button"); btn.type = "button";
        btn.className = (select.className.replace(/\bsr-only\b/g, "") + " bg-white flex min-h-[36px] w-full items-center justify-between gap-2 text-left").replace(/\s+/g, " ");
        btn.setAttribute("role", "combobox"); btn.setAttribute("aria-haspopup", "listbox"); btn.setAttribute("aria-expanded", "false");
        var aria = select.getAttribute("aria-label"); if (aria) btn.setAttribute("aria-label", aria);
        else if (labelEl) { if (!labelEl.id) labelEl.id = "lbl_" + (id || Math.random().toString(36).slice(2)); btn.setAttribute("aria-labelledby", labelEl.id); labelEl.addEventListener("click", function () { btn.focus(); }); }
        else btn.setAttribute("aria-label", select.name || "Options");
        btn.disabled = select.disabled;
        btn.innerHTML = '<span class="flex min-w-0 items-center gap-2"><i data-i class="fa-solid w-4 shrink-0 text-center text-slate-500" aria-hidden="true"></i><span data-t class="truncate"></span></span><i class="fa-solid fa-chevron-down text-[10px] text-slate-400" aria-hidden="true"></i>';
        wrap.appendChild(btn);

        var list = document.createElement("ul"); list.setAttribute("role", "listbox"); list.tabIndex = -1; list.hidden = true;
        list.className = "absolute left-0 z-[70] mt-1 max-h-60 min-w-full overflow-auto rounded-lg border border-slate-200 bg-white p-1 text-sm shadow-lg";
        list.style.width = "max-content"; list.style.maxWidth = "min(22rem, 90vw)";
        var items = opts.map(function (o, i) {
            var li = document.createElement("li"); li.setAttribute("role", "option"); li.setAttribute("data-value", o.value); li.setAttribute("data-icon", iconFor(select, o));
            li.className = "flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-md px-2.5 py-2 hover:bg-blue-50" + (o.disabled ? " opacity-50 pointer-events-none" : "");
            li.innerHTML = '<i class="fa-solid ' + li.getAttribute("data-icon") + ' w-4 shrink-0 text-center text-slate-500" aria-hidden="true"></i><span></span>';
            li.lastChild.textContent = (o.textContent || "").trim() || "\u00A0";
            list.appendChild(li); return li;
        });
        wrap.appendChild(list);

        var active = -1, typed = "", typedAt = 0;
        function paint() {
            var o = select.options[select.selectedIndex];
            btn.querySelector("[data-t]").textContent = o ? (o.textContent || "").trim() : "";
            btn.querySelector("[data-i]").className = "fa-solid w-4 shrink-0 text-center text-slate-500 " + (o ? iconFor(select, o) : "fa-list");
            items.forEach(function (li, i) { var on = i === select.selectedIndex; li.setAttribute("aria-selected", on ? "true" : "false"); li.classList.toggle("bg-blue-50", on); });
        }
        function setActive(i) { active = Math.max(0, Math.min(items.length - 1, i)); items.forEach(function (li, n) { li.classList.toggle("ring-2", n === active); li.classList.toggle("ring-blue-300", n === active); }); items[active].scrollIntoView({ block: "nearest" }); }
        function open() { if (btn.disabled) return; list.hidden = false; btn.setAttribute("aria-expanded", "true"); setActive(Math.max(0, select.selectedIndex)); list.focus(); }
        function close(focus) { list.hidden = true; btn.setAttribute("aria-expanded", "false"); if (focus) btn.focus(); }
        function choose(i) {
            if (opts[i].disabled) return;
            var changed = select.selectedIndex !== i; select.selectedIndex = i; paint(); close(true);
            if (changed) select.dispatchEvent(new Event("change", { bubbles: true }));   // existing onchange / auto-submit handlers still run
        }
        btn.addEventListener("click", function () { list.hidden ? open() : close(true); });
        btn.addEventListener("keydown", function (e) { if (["ArrowDown", "ArrowUp", "Enter", " "].indexOf(e.key) > -1) { e.preventDefault(); open(); } });
        list.addEventListener("keydown", function (e) {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
            else if (e.key === "Home") { e.preventDefault(); setActive(0); }
            else if (e.key === "End") { e.preventDefault(); setActive(items.length - 1); }
            else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(active); }
            else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); }
            else if (e.key === "Tab") { close(false); }
            else if (e.key.length === 1) { var now = Date.now(); typed = (now - typedAt > 700 ? "" : typed) + e.key.toLowerCase(); typedAt = now;
                var hit = items.findIndex(function (li) { return li.textContent.trim().toLowerCase().indexOf(typed) === 0; }); if (hit > -1) setActive(hit); }
        });
        items.forEach(function (li, i) { li.addEventListener("click", function () { choose(i); }); li.addEventListener("mousemove", function () { setActive(i); }); });
        document.addEventListener("click", function (e) { if (!wrap.contains(e.target)) close(false); });
        select.form && select.form.addEventListener("reset", function () { setTimeout(paint, 0); });
        select.addEventListener("change", paint);
        paint();
    }

    function run(scope) { (scope || document).querySelectorAll("select").forEach(enhance); }
    window.SCMOVS_enhanceSelects = run;
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { run(); }); else run();
})();
