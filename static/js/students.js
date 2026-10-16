// Student form: suggest year levels for the department that is selected.
// The server still checks the value, so this is only a convenience.
(function () {
    var dataElement = document.getElementById("year-level-data");
    var department = document.getElementById("department_id");
    var list = document.getElementById("year-levels");
    if (!dataElement || !department || !list) return;

    var levelsByDepartment = JSON.parse(dataElement.textContent);

    function refreshSuggestions() {
        var levels = levelsByDepartment[department.value] || [];
        list.textContent = "";
        levels.forEach(function (level) {
            var option = document.createElement("option");
            option.value = level;
            list.appendChild(option);
        });
    }

    department.addEventListener("change", refreshSuggestions);
    refreshSuggestions();
})();
