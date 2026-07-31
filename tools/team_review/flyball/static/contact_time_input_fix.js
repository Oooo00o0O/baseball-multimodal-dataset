// Preserve the operator's in-progress number text while app.js updates the
// numeric draft and redraws the rest of the interface.
let pendingContactTimeText = null;

document.addEventListener(
  "input",
  (event) => {
    if (event.target instanceof HTMLInputElement && event.target.id === "contactTime") {
      pendingContactTimeText = event.target.value;
    }
  },
  true,
);

document.addEventListener("input", (event) => {
  if (
    event.target instanceof HTMLInputElement
    && event.target.id === "contactTime"
    && pendingContactTimeText !== null
  ) {
    event.target.value = pendingContactTimeText;
    pendingContactTimeText = null;
  }
});
