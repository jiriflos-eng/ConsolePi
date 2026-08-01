(() => {
  const systemTabs = document.querySelectorAll("[data-system-tab]");
  const systemSections = document.querySelectorAll("[data-system-section]");
  const selectSystemSection = (name, updateHistory = true) => {
    systemTabs.forEach((tab) => {
      const active = tab.dataset.systemTab === name;
      tab.classList.toggle("active", active);
      if (active) tab.setAttribute("aria-current", "page");
      else tab.removeAttribute("aria-current");
    });
    systemSections.forEach((section) => {
      section.hidden = section.dataset.systemSection !== name;
    });
    if (updateHistory) {
      const url = new URL(location.href);
      if (name === "overview") url.searchParams.delete("section");
      else url.searchParams.set("section", name);
      history.pushState({systemSection: name}, "", url);
    }
  };
  systemTabs.forEach((tab) => tab.addEventListener("click", (event) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    selectSystemSection(tab.dataset.systemTab);
  }));
  addEventListener("popstate", () => {
    selectSystemSection(
      new URL(location.href).searchParams.get("section") || "overview",
      false
    );
  });

  const text = (name, value) => {
    const element = document.querySelector(`[data-system="${name}"]`);
    if (element) element.textContent = value;
  };
  const meter = (name, value) => {
    const element = document.querySelector(`[data-meter="${name}"]`);
    if (element) element.style.width = `${Math.max(0, Math.min(100, value || 0))}%`;
  };
  const refresh = async () => {
    if (document.hidden) return;
    try {
      const response = await fetch("/api/system", {
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
      text("cpu_percent", data.cpu_percent === null ? "–" : `${data.cpu_percent} %`);
      text("cpu_cores", data.cpu_cores);
      text("load", `${data.load_1} / ${data.load_5} / ${data.load_15}`);
      text("temperature", data.temperature === null ? "–" : `${data.temperature} °C`);
      text("temperature_note", data.temperature === null || data.temperature < 70 ? "V normálním rozsahu" : "Zvýšená teplota");
      text("memory_percent", `${data.memory_percent} %`);
      text("memory_used", data.memory_used);
      text("memory_total", data.memory_total);
      text("disk_percent", `${data.disk_percent} %`);
      text("disk_free", data.disk_free);
      text("disk_total", data.disk_total);
      text("uptime", data.uptime);
      meter("cpu", data.cpu_percent);
      meter("temperature", data.temperature);
      meter("memory", data.memory_percent);
      meter("disk", data.disk_percent);
      Object.entries(data.services).forEach(([service, running]) => {
        const row = document.querySelector(`[data-service="${service}"]`);
        if (!row) return;
        row.querySelector(".service-dot").className = `service-dot ${running ? "up" : "down"}`;
        const state = row.querySelector(".service-state");
        state.textContent = running ? "Aktivní" : "Neaktivní";
        state.className = `service-state ${running ? "up" : "down"}`;
      });
    } catch (_) {
      // Při krátkém výpadku ponecháme poslední známé hodnoty.
    }
  };

  const firewallDialog = document.querySelector("[data-firewall-drop-dialog]");
  const firewallDropList = document.querySelector("[data-firewall-drop-list]");
  const firewallLogButton = document.querySelector("[data-firewall-drops]");
  const appendFirewallField = (row, className, textValue) => {
    const field = document.createElement("span");
    field.className = className;
    field.textContent = textValue;
    row.append(field);
  };
  const showFirewallDrops = async () => {
    if (!firewallDialog || !firewallDropList) return;
    firewallDropList.replaceChildren();
    const loading = document.createElement("p");
    loading.className = "firewall-drop-empty";
    loading.textContent = "Načítám firewallový log…";
    firewallDropList.append(loading);
    firewallDialog.showModal();
    try {
      const response = await fetch("/api/firewall-drops", {credentials: "same-origin", cache: "no-store"});
      const data = await response.json();
      firewallDropList.replaceChildren();
      if (!response.ok || data.error) throw new Error(data.error || "Firewallový log nelze načíst.");
      if (!data.entries || data.entries.length === 0) {
        const empty = document.createElement("p");
        empty.className = "firewall-drop-empty";
        empty.textContent = "Zatím nejsou k dispozici žádné záznamy zahazovaných paketů mimo lokální síť.";
        firewallDropList.append(empty);
        return;
      }
      data.entries.forEach((entry) => {
        const row = document.createElement("div");
        row.className = "firewall-drop-row";
        appendFirewallField(row, "firewall-drop-time", entry.timestamp);
        appendFirewallField(row, "firewall-drop-source", entry.source);
        appendFirewallField(row, "firewall-drop-ports", `${entry.protocol} ${entry.source_port} → ${entry.destination_port}`);
        firewallDropList.append(row);
      });
    } catch (error) {
      firewallDropList.replaceChildren();
      const failure = document.createElement("p");
      failure.className = "firewall-drop-empty error";
      failure.textContent = error.message;
      firewallDropList.append(failure);
    }
  };
  if (firewallLogButton) firewallLogButton.addEventListener("click", showFirewallDrops);
  document.querySelector("[data-firewall-drop-close]")?.addEventListener("click", () => firewallDialog?.close());

  const updateText = (selector, value) => {
    const element = document.querySelector(`[data-update="${selector}"]`);
    if (element) element.textContent = value;
  };
  const refreshUpdates = async () => {
    if (document.hidden || !document.querySelector('[data-update="summary"]')) return;
    try {
      const response = await fetch("/api/updates", {
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
      const working = data.status === "checking" || data.status === "upgrading";
      const summaries = {
        current: "Systém je aktuální",
        updates: `Dostupné aktualizace: ${data.updates}`,
        checking: "Probíhá kontrola…",
        upgrading: "Probíhá instalace…",
        error: "Kontrola skončila chybou",
        unknown: "Stav zatím není známý"
      };
      const badges = {
        current: "Aktuální",
        updates: "K dispozici",
        checking: "Kontrola",
        upgrading: "Instalace",
        error: "Chyba",
        unknown: "Neznámý"
      };
      updateText("summary", summaries[data.status] || summaries.unknown);
      updateText("badge-text", badges[data.status] || badges.unknown);
      updateText("checked", data.checked_human || "Dosud neprovedena");
      const badge = document.querySelector('[data-update="badge"]');
      if (badge) badge.className = `badge update-badge ${data.status === "current" ? "ready" : working ? "busy" : "offline"}`;
      const spinner = document.querySelector('[data-update="spinner"]');
      if (spinner) spinner.hidden = !working;
      const error = document.querySelector('[data-update="error"]');
      if (error) {
        error.textContent = data.error || "";
        error.hidden = !data.error;
      }
      const packages = document.querySelector('[data-update="packages"]');
      const packagesWrap = document.querySelector('[data-update="packages-wrap"]');
      if (packages) packages.textContent = (data.packages || []).join(", ");
      if (packagesWrap) packagesWrap.hidden = !(data.packages || []).length;
      const reboot = document.querySelector('[data-update="reboot"]');
      if (reboot) reboot.hidden = !data.reboot_required;
      const checkButton = document.querySelector('[data-update="check-button"]');
      if (checkButton) checkButton.disabled = working;
      const upgradeForm = document.querySelector('[data-update="upgrade-form"]');
      if (upgradeForm) upgradeForm.hidden = working || !(data.updates > 0);
    } catch (_) {
      // Stav ponecháme na poslední známé hodnotě.
    }
  };
  setInterval(refresh, 5000);
  setInterval(refreshUpdates, 2500);
  document.addEventListener("visibilitychange", () => {
    refresh();
    refreshUpdates();
  });
  refresh();
  refreshUpdates();
})();
