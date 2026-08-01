(() => {
  const refreshPublicStatus = async () => {
    if (document.hidden) return;
    try {
      const response = await fetch("/api/public-status", {
        cache: "no-store",
        headers: {Accept: "application/json"}
      });
      if (!response.ok) return;
      const data = await response.json();
      const count = document.querySelector("#public-connected-count");
      if (count) count.textContent = `${data.connected} připojené`;

      (data.ports || []).forEach((port) => {
        const row = document.querySelector(`[data-public-console-port="${port.port}"]`);
        if (!row) return;
        const badge = row.querySelector('[data-role="public-status"]');
        const icon = row.querySelector('[data-role="public-cable-icon"]');
        const name = row.querySelector('[data-role="public-console-name"]');
        const serial = row.querySelector('[data-role="public-serial-summary"]');
        const nextState = port.busy ? "busy" : port.connected ? "ready" : "offline";
        const previousState = badge?.dataset.state || "";

        if (name) name.textContent = port.display_name;
        if (serial) serial.textContent = port.serial_summary;
        if (icon) {
          icon.textContent = port.connected ? "" : "⊘";
          icon.classList.toggle("disconnected", !port.connected);
        }
        if (badge) {
          badge.className = `badge ${nextState}`;
          badge.dataset.state = nextState;
          badge.textContent = port.busy ? "Obsazen" : port.connected ? "Připraven" : "Offline";
        }
        row.classList.toggle("is-offline", !port.connected);
        if (previousState && previousState !== nextState) {
          row.classList.remove("state-flash");
          void row.offsetWidth;
          row.classList.add("state-flash");
        }
      });
    } catch (_) {
      // Při krátkém výpadku se zachová poslední známý stav.
    }
  };

  refreshPublicStatus();
  setInterval(refreshPublicStatus, 3000);
  document.addEventListener("visibilitychange", refreshPublicStatus);
})();
