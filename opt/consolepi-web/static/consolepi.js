(() => {
  const tabs = document.querySelectorAll(".tab[data-tab]");
  const panels = document.querySelectorAll(".panel");
  const selectTab = (name) => {
    tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
    panels.forEach((panel) => panel.classList.toggle("active", panel.id === name));
  };
  tabs.forEach((tab) => tab.addEventListener("click", () => selectTab(tab.dataset.tab)));
  if (new URLSearchParams(location.search).get("tab") === "network" || document.querySelector(".network-change-pending")) {
    selectTab("network");
  }

  const networkCountdown = document.querySelector("[data-network-countdown]");
  if (networkCountdown) {
    const value = networkCountdown.querySelector("[data-network-countdown-value]");
    const message = networkCountdown.querySelector("[data-network-countdown-message]");
    const fallbackUrl = networkCountdown.dataset.fallbackUrl || "";
    let deadline = Date.now() + Math.max(0, Number(networkCountdown.dataset.remainingSeconds || 0)) * 1000;
    let expired = false;
    const renderCountdown = () => {
      const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      if (value) value.textContent = String(remaining);
      if (!remaining && !expired) {
        expired = true;
        if (message) message.textContent = fallbackUrl
          ? "Limit vypršel. ConsolePi obnovuje původní síťový profil; za okamžik se otevře původní adresa."
          : "Limit vypršel. ConsolePi obnovuje původní síťový profil.";
        if (fallbackUrl) window.setTimeout(() => location.replace(fallbackUrl), 2500);
      }
    };
    const refreshCountdown = async () => {
      try {
        const response = await fetch("/api/network/pending", {credentials: "same-origin", cache: "no-store"});
        if (!response.ok) return;
        const state = await response.json();
        if (state.active) {
          deadline = Date.now() + Math.max(0, Number(state.remaining_seconds || 0)) * 1000;
          renderCountdown();
        }
      } catch (_) { /* The network can disappear while the rollback is applied. */ }
    };
    renderCountdown();
    window.setInterval(renderCountdown, 250);
    window.setInterval(refreshCountdown, 5000);
  }

  const fields = document.querySelector("#static-fields");
  document.querySelectorAll('input[name="mode"]').forEach((radio) => {
    const update = () => {
      if (!fields) return;
      const disabled = document.querySelector('input[name="mode"]:checked').value === "dhcp";
      fields.hidden = disabled;
      fields.querySelectorAll("input").forEach((input) => input.disabled = disabled);
    };
    radio.addEventListener("change", update);
    update();
  });

  const proxyToggle = document.querySelector('input[name="enabled"]');
  const proxyFields = document.querySelector("[data-proxy-fields]");
  const updateProxyFields = () => {
    if (!proxyToggle || !proxyFields) return;
    proxyFields.hidden = !proxyToggle.checked;
    proxyFields.querySelectorAll("input, select").forEach((field) => {
      field.disabled = !proxyToggle.checked;
    });
  };
  if (proxyToggle) {
    proxyToggle.addEventListener("change", updateProxyFields);
    updateProxyFields();
  }

  const repositoriesMode = document.querySelector("[data-repositories-mode]");
  const repositoriesFields = document.querySelector("[data-repositories-fields]");
  const updateRepositoryFields = () => {
    if (!repositoriesMode || !repositoriesFields) return;
    const customMirror = repositoriesMode.value === "mirror";
    repositoriesFields.hidden = !customMirror;
    repositoriesFields.querySelectorAll("input").forEach((field) => {
      field.disabled = !customMirror;
      field.required = customMirror;
    });
  };
  if (repositoriesMode) {
    repositoriesMode.addEventListener("change", updateRepositoryFields);
    updateRepositoryFields();
  }

  const updateAccessConfirmation = (form) => {
    const network = form.querySelector('input[name="network"]');
    const confirmation = form.querySelector("[data-access-confirm]");
    if (!network || !confirmation) return;
    const required = network.value.trim() === "0.0.0.0/0";
    confirmation.hidden = !required;
    const input = confirmation.querySelector('input[name="confirmation"]');
    if (input) {
      input.disabled = !required;
      if (!required) input.value = "";
    }
  };
  document.querySelectorAll("form.access-source-row, form.access-source-add").forEach((form) => {
    const network = form.querySelector('input[name="network"]');
    if (network) network.addEventListener("input", () => updateAccessConfirmation(form));
    updateAccessConfirmation(form);
  });

  const updateStatus = async () => {
    if (document.hidden) return;
    try {
      const response = await fetch("/api/status", {
        credentials: "same-origin",
        cache: "no-store",
        headers: {Accept: "application/json"}
      });
      if (response.status === 401 || response.redirected) {
        location.assign("/login");
        return;
      }
      if (!response.ok) return;
      const data = await response.json();
      renderUnassignedUsb(data.unassigned_usb_cables || [], data.ports || []);
      document.querySelector("#connected-count").textContent = `${data.connected} připojené`;
      document.querySelector("#offline-count").textContent = `${data.offline} volné SSH porty`;
      data.ports.forEach((port) => {
        const row = document.querySelector(`[data-console-port="${port.port}"]`);
        if (!row) return;
        const badge = row.querySelector('[data-role="status"]');
        const icon = row.querySelector('[data-role="cable-icon"]');
        const nextState = port.busy ? "busy" : port.connected ? "ready" : "offline";
        const previousState = badge.dataset.state || (
          badge.classList.contains("busy") ? "busy" :
          badge.classList.contains("ready") ? "ready" : "offline"
        );
        badge.className = `badge ${nextState}`;
        badge.dataset.state = nextState;
        const assigned = row.dataset.assigned === "yes";
        badge.textContent = port.busy ? "Obsazen" : port.connected ? "Připraven" : assigned ? "Odpojený" : "Nepřiřazeno";
        icon.textContent = port.connected ? "" : "⊘";
        icon.classList.toggle("disconnected", !port.connected);
        row.classList.toggle("is-offline", !port.connected);
        const deviceDescription = row.querySelector('[data-role="device-description"]');
        if (deviceDescription) {
          deviceDescription.textContent = port.connected
            ? port.hardware_description
            : assigned
              ? `Odpojený · ${port.hardware_description}`
              : port.hardware_description;
          deviceDescription.title = port.device;
        }
        const serialSummary = row.querySelector('[data-role="serial-summary"]');
        if (serialSummary) serialSummary.textContent = port.serial_summary;
        const consoleName = row.querySelector('[data-role="console-name"]');
        if (consoleName) consoleName.textContent = port.display_name;
        if (previousState !== nextState) {
          row.classList.remove("state-flash");
          void row.offsetWidth;
          row.classList.add("state-flash");
        }
      });
    } catch (_) {
      // Krátký výpadek sítě nemění poslední známý stav.
    }
  };

  const renderUnassignedUsb = (cables, ports) => {
    const section = document.querySelector("[data-unassigned-usb]");
    const list = document.querySelector('[data-role="unassigned-usb-list"]');
    if (!section || !list) return;
    section.hidden = cables.length === 0;
    if (!cables.length) return;
    // Stav se obnovuje každé tři sekundy. Než formuláře znovu vytvoříme,
    // zapamatujeme ruční volbu portu pro každý nalezený USB adaptér.
    const selectedPorts = new Map();
    list.querySelectorAll("form").forEach((form) => {
      const device = form.querySelector('input[name="device"]')?.value;
      const port = form.querySelector('select[name="port"]')?.value;
      if (device && port) selectedPorts.set(device, port);
    });
    const freePorts = ports.filter((port) => port.device.includes("/unassigned-"));
    list.replaceChildren();
    cables.forEach((cable) => {
      const form = document.createElement("form");
      form.method = "post"; form.action = "/ports/assign"; form.className = "unassigned-usb-row";
      const csrf = document.createElement("input");
      csrf.type = "hidden"; csrf.name = "csrf"; csrf.value = section.dataset.csrf || "";
      const device = document.createElement("input");
      device.type = "hidden"; device.name = "device"; device.value = cable.stable_id;
      const description = document.createElement("div");
      const title = document.createElement("strong"); title.textContent = cable.hardware_description;
      const details = document.createElement("small");
      const code = document.createElement("code"); code.textContent = cable.stable_id;
      details.append(code); description.append(title, details);
      const label = document.createElement("label"); label.textContent = "SSH port";
      const select = document.createElement("select"); select.name = "port";
      freePorts.forEach((port) => {
        const option = document.createElement("option");
        option.value = port.port; option.textContent = `${port.port} · ${port.name}`;
        option.selected = selectedPorts.get(cable.stable_id) === port.port;
        select.append(option);
      });
      label.append(select);
      const button = document.createElement("button"); button.type = "submit";
      button.textContent = freePorts.length ? "Přiřadit kabel" : "Není volný SSH port";
      button.disabled = freePorts.length === 0;
      form.append(csrf, device, description, label, button);
      list.append(form);
    });
  };
  setInterval(updateStatus, 3000);
  document.addEventListener("visibilitychange", updateStatus);
})();
