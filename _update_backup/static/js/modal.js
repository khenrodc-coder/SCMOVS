/* SCMOVS global modal system.
 *
 *  Open:      <button data-modal-url="/some/fragment">   (the server returns the modal's HTML)
 *  Form:      the fragment contains <form data-modal-form> ... </form>; it is submitted with fetch().
 *             Server replies JSON: {ok:true, message}  or  422 {ok:false, errors:{field:msg}, message}.
 *  Refresh:   on success the element #list-region (if present) is re-fetched and swapped in place,
 *             so the table updates without reloading the whole dashboard.
 *  Close:     X button, Cancel (data-modal-close), or Escape.  Entered values are never cleared on error.
 */
(function () {
    var root, dialog, lastFocus, busy = false;

    function toast(icon, title) {
        if (typeof Swal === "undefined") return;
        Swal.fire({ toast: true, position: "top-end", icon: icon, title: title, showConfirmButton: false, timer: 4000, timerProgressBar: true });
    }
    function csrf() { var m = document.querySelector('meta[name="csrf-token"]'); return m ? m.content : ""; }

    function ensureRoot() {
        if (root) return;
        root = document.createElement("div");
        root.id = "scmovs-modal-root";
        root.className = "scmovs-modal-overlay";
        root.hidden = true;
        root.innerHTML = '<div class="scmovs-modal-dialog" role="dialog" aria-modal="true"></div>';
        document.body.appendChild(root);
        dialog = root.firstChild;
        root.addEventListener("mousedown", function (e) { root._downOnBackdrop = (e.target === root); });
        // Backdrop click does NOT close the modal: people lose typed data that way. Use X / Cancel / Esc.
    }

    function openShell(html) {
        ensureRoot();
        lastFocus = document.activeElement;
        dialog.innerHTML = html;
        root.hidden = false;
        document.documentElement.classList.add("modal-open");
        wire();
        var first = dialog.querySelector("[autofocus], input:not([type=hidden]):not([disabled]), select, textarea, button");
        if (first) first.focus();
    }

    function close() {
        if (!root || root.hidden) return;
        root.hidden = true;
        dialog.innerHTML = "";
        document.documentElement.classList.remove("modal-open");
        busy = false;
        if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    function open(url) {
        openShell('<div class="p-10 text-center text-slate-500"><i class="fa-solid fa-spinner fa-spin text-xl"></i><p class="mt-2 text-sm">Loading…</p></div>');
        fetch(url, { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
            .then(function (r) {
                if (!r.ok) throw new Error(r.status);
                return r.text();
            })
            .then(function (html) { openShell(html); })
            .catch(function () {
                openShell('<div class="p-8 text-center"><p class="font-semibold text-red-700">This form could not be loaded.</p>' +
                    '<p class="mt-1 text-sm text-slate-500">You may not have permission, or your session expired.</p>' +
                    '<button type="button" data-modal-close class="mt-4 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold">Close</button></div>');
            });
    }

    function clearErrors(form) {
        form.querySelectorAll("[data-error-for]").forEach(function (el) { el.textContent = ""; el.hidden = true; });
        form.querySelectorAll(".field-invalid").forEach(function (el) { el.classList.remove("field-invalid"); el.removeAttribute("aria-invalid"); });
        var box = form.querySelector("[data-form-error]");
        if (box) { box.textContent = ""; box.hidden = true; }
    }
    function showErrors(form, errors, message) {
        var shown = 0, firstField = null;
        Object.keys(errors || {}).forEach(function (name) {
            var slot = form.querySelector('[data-error-for="' + name + '"]');
            var input = form.querySelector('[name="' + name + '"]');
            if (slot && name !== "_form") {
                slot.textContent = errors[name]; slot.hidden = false; shown++;
                if (input) { input.classList.add("field-invalid"); input.setAttribute("aria-invalid", "true"); if (!firstField) firstField = input; }
            } else {
                var box = form.querySelector("[data-form-error]");
                if (box) { box.textContent = errors[name]; box.hidden = false; shown++; }
            }
        });
        if (!shown && message) {
            var b = form.querySelector("[data-form-error]");
            if (b) { b.textContent = message; b.hidden = false; }
        }
        if (firstField) firstField.focus();
    }

    function refreshRegion() {
        var region = document.getElementById("list-region");
        if (!region) { return Promise.resolve(false); }
        return fetch(location.href, { headers: { "X-Requested-With": "fetch-region" }, credentials: "same-origin" })
            .then(function (r) { return r.text(); })
            .then(function (html) {
                var doc = new DOMParser().parseFromString(html, "text/html");
                var fresh = doc.getElementById("list-region");
                if (fresh) { region.innerHTML = fresh.innerHTML; return true; }
                return false;
            }).catch(function () { return false; });
    }

    function submit(form, submitter) {
        if (busy) return;                       // blocks double submission
        busy = true;
        clearErrors(form);
        var btns = form.querySelectorAll("button[type=submit]");
        btns.forEach(function (b) { b.disabled = true; });
        var label = submitter && submitter.querySelector("[data-label]");
        var original = label ? label.textContent : "";
        if (label) label.textContent = submitter.getAttribute("data-loading") || "Saving…";
        var spin = submitter && submitter.querySelector("[data-spinner]");
        if (spin) spin.hidden = false;

        var done = function () {
            busy = false;
            btns.forEach(function (b) { b.disabled = false; });
            if (label) label.textContent = original;
            if (spin) spin.hidden = true;
        };

        fetch(form.getAttribute("action") || location.href, {
            method: "POST",
            body: new FormData(form),
            headers: { "X-Requested-With": "fetch", "X-CSRFToken": csrf(), "Accept": "application/json" },
            credentials: "same-origin"
        }).then(function (r) {
            return r.json().catch(function () { return { ok: false, message: "Unexpected response from the server (" + r.status + ")." }; })
                .then(function (data) { return { status: r.status, data: data }; });
        }).then(function (res) {
            var d = res.data;
            if (d.ok) {
                var after = form.getAttribute("data-after");       // optional: "stay" keeps the modal open (e.g. to show a temp password)
                if (d.html_result) {                                 // server asks to swap the dialog body (one-time secrets)
                    done(); dialog.innerHTML = d.html_result; wire(); refreshRegion(); return;
                }
                toast("success", d.message || "Saved.");
                close();
                if (d.reload) { location.reload(); return; }
                refreshRegion();
            } else {
                done();
                if (res.status === 400 && /CSRF/i.test(d.message || "")) d.message = "Your session expired. Please reload the page and try again.";
                showErrors(form, d.errors, d.message || "The request failed.");
                if (!d.errors || !Object.keys(d.errors).length) toast("error", d.message || "The request failed.");
            }
        }).catch(function () {
            done();
            showErrors(form, { _form: "Network error. Nothing was saved. Please try again." });
        });
    }

    function wire() {
        dialog.querySelectorAll("[data-modal-close]").forEach(function (b) { b.addEventListener("click", close); });
        var form = dialog.querySelector("form[data-modal-form]");
        if (form) {
            form.setAttribute("novalidate", "novalidate");     // we show our own inline messages; the server re-validates anyway
            form.addEventListener("submit", function (e) {
                e.preventDefault();
                var v = form._clientValidate ? form._clientValidate(form) : null;
                if (v && Object.keys(v).length) { showErrors(form, v); return; }
                submit(form, e.submitter || form.querySelector("button[type=submit]"));
            });
            if (window.SCMOVS_initModalForm) window.SCMOVS_initModalForm(form);
        }
        dialog.querySelectorAll("[data-modal-url]").forEach(function (b) {
            b.addEventListener("click", function () { open(b.getAttribute("data-modal-url")); });
        });
    }

    document.addEventListener("click", function (e) {
        var t = e.target.closest("[data-modal-url]");
        if (!t || (dialog && dialog.contains(t))) return;
        e.preventDefault();
        open(t.getAttribute("data-modal-url"));
    });
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && root && !root.hidden) { e.preventDefault(); close(); }
        // keep Tab focus inside the dialog
        if (e.key === "Tab" && root && !root.hidden) {
            var f = dialog.querySelectorAll('a[href], button:not([disabled]), input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled])');
            if (!f.length) return;
            var first = f[0], last = f[f.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
    });

    window.ScmovsModal = { open: open, close: close, refresh: refreshRegion };
})();
