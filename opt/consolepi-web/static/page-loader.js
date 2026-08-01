(() => {
  const loader = document.querySelector(".page-loader");
  if (!loader) return;

  const show = () => {
    document.body.classList.add("consolepi-loading");
    document.body.setAttribute("aria-busy", "true");
    loader.setAttribute("aria-hidden", "false");
  };

  const hide = () => {
    document.body.classList.remove("consolepi-loading");
    document.body.removeAttribute("aria-busy");
    loader.setAttribute("aria-hidden", "true");
  };

  const isNavigatingLink = (link, event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    if (link.target && link.target !== "_self") return false;
    if (link.hasAttribute("download") || link.dataset.noPageLoader !== undefined) return false;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || url.hash && url.pathname === location.pathname && url.search === location.search) return false;
    return url.protocol === location.protocol;
  };

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");
    if (link && isNavigatingLink(link, event)) show();
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.dataset.noPageLoader !== undefined || form.target) return;
    // Některé formuláře obsluhuje JavaScript bez přechodu na jinou stránku.
    // Kontrolu odložíme až po doběhnutí všech posluchačů události.
    queueMicrotask(() => {
      if (!event.defaultPrevented) show();
    });
  });

  addEventListener("pageshow", hide);
  addEventListener("pagehide", () => loader.setAttribute("aria-hidden", "true"));
})();
