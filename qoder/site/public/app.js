(function () {
  "use strict";

  function fallbackCopy(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "-1000px";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (err) {
      ok = false;
    }
    document.body.removeChild(area);
    return ok;
  }

  function flash(button, message) {
    var original = button.getAttribute("data-label") || button.textContent;
    button.setAttribute("data-label", original);
    button.textContent = message;
    button.classList.add("copied");
    window.clearTimeout(button._resetTimer);
    button._resetTimer = window.setTimeout(function () {
      button.textContent = original;
      button.classList.remove("copied");
    }, 1800);
  }

  function handleCopy(button) {
    var target = document.getElementById(button.getAttribute("data-copy"));
    if (!target) return;
    var text = target.innerText.replace(/\r\n/g, "\n").trim();
    if (!text) return;

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(
        function () {
          flash(button, "已复制");
        },
        function () {
          flash(button, fallbackCopy(text) ? "已复制" : "复制失败");
        }
      );
      return;
    }
    flash(button, fallbackCopy(text) ? "已复制" : "复制失败");
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    event.preventDefault();
    handleCopy(button);
  });
})();
