// 1) Show Flask flash messages as SweetAlert2 toasts.
// Categories used in Flask: success, error, warning, info
(function () {
    var messages = window.SCMOVS_FLASH || [];
    if (!messages.length || typeof Swal === "undefined") return;

    var Toast = Swal.mixin({
        toast: true,
        position: "top-end",
        showConfirmButton: false,
        timer: 4000,
        timerProgressBar: true
    });

    messages.forEach(function (item) {
        var category = item[0];
        var text = item[1];
        var icon = ["success", "error", "warning", "info"].indexOf(category) !== -1 ? category : "info";
        Toast.fire({ icon: icon, title: text });
    });
})();

// 2) Mobile sidebar toggle (only exists on pages that use the app layout).
(function () {
    var button = document.getElementById("sidebar-toggle");
    var sidebar = document.getElementById("sidebar");
    if (!button || !sidebar) return;

    button.addEventListener("click", function () {
        sidebar.classList.toggle("-translate-x-full");
    });
})();

// 3) Confirmation dialog for any form that has a data-confirm="message" attribute.
document.addEventListener("submit", function (event) {
    var form = event.target;
    var message = form.getAttribute("data-confirm");
    if (!message || typeof Swal === "undefined") return;

    event.preventDefault();
    Swal.fire({
        title: "Please confirm",
        text: message,
        icon: "question",
        showCancelButton: true,
        confirmButtonText: "Yes, continue",
        cancelButtonText: "Cancel",
        confirmButtonColor: "#1e3a8a"
    }).then(function (result) {
        if (result.isConfirmed) {
            form.removeAttribute("data-confirm");   // so the real submit is not intercepted again
            form.submit();
        }
    });
});