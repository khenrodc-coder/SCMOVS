/* Client-side validation for modal forms (the server repeats every rule; this only saves a round trip).
 * Inputs opt in with data-rule:  required (HTML attribute) | email | student-id | student-email | password-match
 *   student-email needs data-match="<name of the Student ID input>";  password-match needs data-match="<password input name>"
 */
(function () {
    var EMAIL = /^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$/, SID = /^[0-9]{8}$/, DOMAIN = "holycross.edu.ph", PERSONAL = "gmail.com", ONLY = "Only @" + PERSONAL + " and @" + DOMAIN + " email addresses are accepted.";
    var NAME = /^[\p{L}][\p{L} .'-]*$/u;

    function val(form, name) { var el = form.querySelector('[name="' + name + '"]'); return el ? el.value : ""; }

    function validate(form) {
        var errors = {};
        form.querySelectorAll("input, select, textarea").forEach(function (el) {
            var name = el.name; if (!name || el.disabled || el.type === "hidden" && !el.hasAttribute("required")) return;
            var v = (el.type === "password" ? el.value : el.value.trim());
            if (el.hasAttribute("required") && !v) { errors[name] = "This field is required."; return; }
            if (!v) return;
            var rule = el.getAttribute("data-rule");
            if (rule === "name" && !NAME.test(v)) errors[name] = "Use letters only (spaces, . ' - allowed).";
            if (rule === "email") {
                if (!EMAIL.test(v)) errors[name] = "Enter a valid email address.";
                else if ([PERSONAL, DOMAIN].indexOf(v.toLowerCase().split("@")[1]) < 0) errors[name] = ONLY;
            }
            if (rule === "student-id" && !SID.test(v)) errors[name] = "Student ID must be exactly 8 digits (numbers only, no spaces or hyphens).";
            if (rule === "student-email") {
                var sid = val(form, el.getAttribute("data-match")).trim(), low = v.toLowerCase(), parts = low.split("@");
                if (!EMAIL.test(low)) errors[name] = "Enter a valid email address.";
                else if ([PERSONAL, DOMAIN].indexOf(parts[1]) < 0) errors[name] = ONLY;
                else if (parts[1] === DOMAIN && !SID.test(parts[0])) errors[name] = "A school email must be 8 digits followed by @" + DOMAIN + ". You can also use a personal @" + PERSONAL + " address.";
                else if (parts[1] === DOMAIN && SID.test(sid) && parts[0] !== sid) errors[name] = "The email's student number (" + parts[0] + ") does not match the Student ID (" + sid + "). It should be " + sid + "@" + DOMAIN + ", or use a personal @" + PERSONAL + " address.";
            }
            if (rule === "ph-mobile" && !/^(09|\+639|639)[0-9]{9}$/.test(v.replace(/[\s\-()]/g, ""))) errors[name] = "Enter a Philippine mobile number, for example 09171234567 or +639171234567.";
            if (rule === "birthdate") {
                var born = new Date(v + "T00:00:00"), today = new Date(), age = today.getFullYear() - born.getFullYear() - ((today.getMonth() < born.getMonth() || (today.getMonth() === born.getMonth() && today.getDate() < born.getDate())) ? 1 : 0);
                if (isNaN(born.getTime())) errors[name] = "Enter a valid birthday.";
                else if (born > today) errors[name] = "The birthday cannot be in the future.";
                else if (age < 5 || age > 120) errors[name] = "The age must be between 5 and 120 years.";
            }
            if (rule === "password-match" && v !== val(form, el.getAttribute("data-match"))) errors[name] = "The passwords do not match.";
        });
        return errors;
    }

    var prev = window.SCMOVS_initModalForm;
    window.SCMOVS_initModalForm = function (form) {
        if (prev) prev(form);
        form._clientValidate = validate;
        // Student ID: keep only digits as the person types / pastes, capped at 8 (the server still validates)
        form.querySelectorAll('[data-rule="student-id"]').forEach(function (el) {
            el.setAttribute("inputmode", "numeric");
            el.addEventListener("input", function () { var d = el.value.replace(/[^0-9]/g, "").slice(0, 8); if (d !== el.value) el.value = d; });
        });
        // Year-level suggestions follow the chosen department (data comes from the server in data-year-map)
        var yearMapEl = form.querySelector("[data-year-map]"), levels = form.querySelector("#year-levels");
        if (yearMapEl && levels) {
            var map = {}; try { map = JSON.parse(yearMapEl.getAttribute("data-year-map")); } catch (e) {}
            var fill = function () {
                var dep = form.querySelector('[name="department_id"]'); levels.innerHTML = "";
                ((dep && map[dep.value]) || []).forEach(function (l) { var o = document.createElement("option"); o.value = l; levels.appendChild(o); });
            };
            form.addEventListener("change", function (e) { if (e.target.name === "department_id") fill(); });
            fill();
        }
        // Photo preview (candidate + any file input with data-photo-preview)
        form.querySelectorAll("[data-photo-preview]").forEach(function (inp) {
            inp.addEventListener("change", function () {
                var box = document.getElementById(inp.getAttribute("data-photo-preview")), f = inp.files[0], slot = form.querySelector('[data-error-for="' + inp.name + '"]');
                if (slot) { slot.hidden = true; slot.textContent = ""; }
                if (!f) return;
                var bad = ["image/jpeg", "image/png", "image/webp"].indexOf(f.type) < 0 ? "Choose a JPG, PNG or WebP image." : (f.size > 5 * 1024 * 1024 ? "The image is larger than 5 MB." : "");
                if (bad) { inp.value = ""; if (slot) { slot.textContent = bad; slot.hidden = false; } return; }
                box.innerHTML = '<img alt="Photo preview" class="h-full w-full object-cover" src="' + URL.createObjectURL(f) + '">';
            });
        });
        // Add/Edit Candidate: positions follow the election; names + department come from the student record
        var cand = form.querySelector("[data-candidate-form]");
        if (cand) {
            var posMap = {}; try { posMap = JSON.parse(cand.getAttribute("data-pos-map")); } catch (e) {}
            var lookupUrl = cand.getAttribute("data-lookup-url"), stu = form.querySelector("[data-candidate-student]"), statusEl = form.querySelector("[data-cand-status]"), timer = null;
            var setText = function (k, v) { var n = form.querySelector("[data-cand-" + k + "]"); if (n) n.textContent = v || ""; };
            var election = function () { var e = form.querySelector('[name="election_id"]'); return e ? e.value : ""; };
            var lookup = function () {
                if (!stu) return; var id = stu.value.trim();
                ["first_name", "middle_name", "last_name", "department"].forEach(function (k) { setText(k, ""); });
                if (!id || !election()) { statusEl.textContent = "Choose an election and enter a Student ID."; statusEl.className = "text-xs text-slate-500"; return; }
                fetch(lookupUrl + "?election=" + encodeURIComponent(election()) + "&student_number=" + encodeURIComponent(id), { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
                    .then(function (r) { return r.json(); }).then(function (d) {
                        if (d.ok) { ["first_name", "middle_name", "last_name", "department"].forEach(function (k) { setText(k, d.student[k]); }); statusEl.textContent = "Eligible student found."; statusEl.className = "text-xs font-medium text-green-700"; }
                        else { statusEl.textContent = d.message; statusEl.className = "text-xs font-medium text-red-700"; }
                    }).catch(function () { statusEl.textContent = "Could not check the Student ID right now."; statusEl.className = "text-xs font-medium text-red-700"; });
            };
            if (stu) stu.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(lookup, 350); });
            form.addEventListener("change", function (e) {
                if (e.target.name !== "election_id") return;
                var wrap = form.querySelector('[name="position_id"]').closest("[data-icon-select]"), list = wrap.querySelector("[role=listbox]"), hid = wrap.querySelector("input[type=hidden]");
                list.innerHTML = ""; hid.value = "";
                (posMap[e.target.value] || []).forEach(function (p) { var li = document.createElement("li"); li.setAttribute("role", "option"); li.setAttribute("data-value", p.id); li.setAttribute("data-icon", "fa-briefcase");
                    li.className = "flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 hover:bg-blue-50"; li.innerHTML = '<i class="fa-solid fa-briefcase w-4 text-center text-slate-500"></i><span></span>'; li.lastChild.textContent = p.name; list.appendChild(li); });
                wrap._isInit = false; window.SCMOVS_initIconSelects(wrap.parentNode); lookup();
            });
        }
        // Birthday cannot be in the future
        form.querySelectorAll('[data-rule="birthdate"]').forEach(function (el) { el.max = new Date().toISOString().slice(0, 10); });

        // Add User: the Student section appears only for the Student role (and is switched off otherwise, so it is
        // neither validated nor sent). The email rule becomes the student rule for students.
        var roleEl = form.querySelector('[name="role"]'), hasSections = form.querySelector("[data-show-role]");
        if (roleEl && hasSections) {
            var applyRole = function () {
                var r = roleEl.value;
                var toggle = function (sec, on) { sec.hidden = !on; sec.querySelectorAll("input, select, textarea, button").forEach(function (el) { el.disabled = !on; }); };
                form.querySelectorAll("[data-show-role]").forEach(function (sec) { toggle(sec, sec.getAttribute("data-show-role") === r); });
                form.querySelectorAll("[data-hide-role]").forEach(function (sec) { toggle(sec, sec.getAttribute("data-hide-role") !== r); });
                var em = form.querySelector('[name="email"]');
                if (em) { em.setAttribute("data-rule", r === "student" ? "student-email" : "email"); em.setAttribute("data-match", "student_number"); }
            };
            roleEl.addEventListener("change", applyRole); applyRole();
        }

        // Suggest the school email as soon as a full Student ID is typed (only while the email is empty)
        var sidEl = form.querySelector('[data-rule="student-id"]'), mail = form.querySelector('[name="email"]');
        if (sidEl && mail) sidEl.addEventListener("input", function () {
            if (mail.getAttribute("data-rule") === "student-email" && /^[0-9]{8}$/.test(sidEl.value) && !mail.value) mail.value = sidEl.value + "@" + DOMAIN;
        });
    };
})();
