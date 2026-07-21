// Keyboard navigation for the dark "quiz" study screens (choice / typed /
// flashcards / match / feedback / summary — anything wrapped in .quiz-screen).
// One document-level listener, attached once; it queries the live DOM at event
// time because #card content is swapped by htmx. All work is scoped under
// .quiz-screen so other pages are untouched.
(function () {
  "use strict";

  // Auto-advance: after a correct answer in choice mode, move to the next
  // card on its own instead of waiting for Enter/click. The server marks the
  // eligible "Дальше" button with data-autoadvance="<ms>"; any manual click
  // (or Escape/reload) swaps #card again, which cancels the pending timer.
  var autoAdvanceTimer = null;

  document.addEventListener("htmx:afterSwap", function (e) {
    var target = (e.detail && e.detail.target) || e.target;
    if (!target || target.id !== "card") return;
    clearTimeout(autoAdvanceTimer);
    var btn = target.querySelector(".quiz-next[data-autoadvance]");
    if (btn) {
      var delay = parseInt(btn.dataset.autoadvance, 10) || 1200;
      autoAdvanceTimer = setTimeout(function () { btn.click(); }, delay);
    }
  });

  document.addEventListener("keydown", function (e) {
    var screen = document.querySelector(".quiz-screen");
    if (!screen) return;

    // Escape always aborts — even while the typed-answer input is focused.
    if (e.key === "Escape") {
      e.preventDefault();
      window.location.href = "/dashboard";
      return;
    }

    // Ignore typing keys while a text field is focused (typed mode). The flip
    // checkbox is an <input> too but must stay keyboard-drivable, so exclude it.
    var active = document.activeElement;
    var tag = active && active.tagName;
    var isText = (tag === "INPUT" && active.type !== "checkbox") || tag === "TEXTAREA";
    if (isText) return;

    // Flashcards: Space flips the card; once flipped, 1-4 grade it.
    var flip = screen.querySelector(".quiz-flip-toggle");
    if (flip) {
      if (!flip.checked) {
        if (e.key === " " || e.key === "Spacebar") {
          e.preventDefault();
          flip.click(); // .click() so the native :checked CSS state updates
        }
        return;
      }
      if (e.key >= "1" && e.key <= "4") {
        var grades = screen.querySelectorAll(".quiz-grade");
        var gi = parseInt(e.key, 10) - 1;
        if (gi < grades.length) {
          e.preventDefault();
          grades[gi].click();
        }
      }
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

    // Choice question screen: numbers select, Enter confirms the selection.
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
