// Keyboard navigation for the "choice" (quiz) study screen.
// One document-level listener, attached once; it queries the live DOM at event
// time because #card content is swapped by htmx. All work is scoped under
// .quiz-screen so other pages / study modes are untouched.
(function () {
  "use strict";

  document.addEventListener("keydown", function (e) {
    var screen = document.querySelector(".quiz-screen");
    if (!screen) return;

    // Never hijack keys while a text field is focused (other modes reuse this).
    var tag = document.activeElement && document.activeElement.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") return;

    if (e.key === "Escape") {
      e.preventDefault();
      window.location.href = "/dashboard";
      return;
    }

    // Feedback screen: Enter activates "Дальше"; number keys do nothing.
    var next = screen.querySelector(".quiz-next");
    if (next) {
      if (e.key === "Enter") {
        e.preventDefault();
        next.click();
      }
      return;
    }

    // Question screen.
    var opts = screen.querySelectorAll(".quiz-option");
    if (!opts.length) return;

    if (e.key >= "1" && e.key <= "4") {
      var idx = parseInt(e.key, 10) - 1;
      if (idx < opts.length) {
        for (var i = 0; i < opts.length; i++) opts[i].classList.remove("is-selected");
        opts[idx].classList.add("is-selected");
      }
      e.preventDefault();
      return;
    }

    if (e.key === "Enter") {
      var sel = screen.querySelector(".quiz-option.is-selected");
      if (sel) {
        e.preventDefault();
        sel.click();
      }
    }
  });
})();
