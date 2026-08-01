(() => {
  const root = document.documentElement;
  const button = document.querySelector("[data-theme-toggle]");
  if (!button) return;
  const label = button.querySelector("[data-theme-label]");
  const icon = button.querySelector("[aria-hidden]");
  const systemDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;
  const current = () => root.dataset.theme || (systemDark() ? "dark" : "light");
  const render = () => {
    const dark = current() === "dark";
    label.textContent = dark ? "Denní režim" : "Noční režim";
    icon.textContent = dark ? "☀" : "☾";
    button.setAttribute("aria-pressed", String(dark));
  };
  button.addEventListener("click", () => {
    const next = current() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    localStorage.setItem("consolepi-theme", next);
    render();
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
  render();
})();
