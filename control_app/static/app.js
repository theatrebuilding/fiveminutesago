const relayPill = document.getElementById("relay-pill");
const refreshLabel = document.getElementById("refresh-label");
const actionMessage = document.getElementById("action-message");
const processState = document.getElementById("process-state");
const processMeta = document.getElementById("process-meta");
const configState = document.getElementById("config-state");
const configMeta = document.getElementById("config-meta");
const recordingState = document.getElementById("recording-state");
const recordingMeta = document.getElementById("recording-meta");
const workingFiles = document.getElementById("working-files");
const archiveSummary = document.getElementById("archive-summary");
const archiveFiles = document.getElementById("archive-files");
const logOutput = document.getElementById("log-output");
const configEditor = document.getElementById("config-editor");
const configMessage = document.getElementById("config-message");

const commandButtons = Array.from(document.querySelectorAll("[data-action]"));
const saveConfigButton = document.getElementById("save-config");
const applyConfigButton = document.getElementById("apply-config");

let refreshTimer = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });

  if (!response.ok) {
    const payload = await safeJson(response);
    const detail = payload?.detail || payload?.message || `${response.status} ${response.statusText}`;
    throw new Error(detail);
  }

  return safeJson(response);
}

async function safeJson(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return null;
  }
  return response.json();
}

function setBusy(buttons, busy) {
  buttons.forEach((button) => {
    button.disabled = busy;
  });
}

function formatBytes(bytes) {
  if (!bytes) {
    return "0 B";
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatSeconds(seconds) {
  if (seconds == null) {
    return "Unknown";
  }

  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins === 0) {
    return `${secs}s`;
  }
  const hours = Math.floor(mins / 60);
  if (hours === 0) {
    return `${mins}m ${secs}s`;
  }
  return `${hours}h ${mins % 60}m`;
}

function formatFileState(file) {
  if (!file.exists) {
    return "Missing";
  }
  return `${formatBytes(file.size_bytes)} • updated ${formatSeconds(file.age_seconds)} ago`;
}

function renderWorkingFiles(files) {
  workingFiles.innerHTML = "";

  files.forEach((file) => {
    const card = document.createElement("article");
    card.className = "storage-item";
    card.innerHTML = `
      <h3>${file.name}</h3>
      <p class="storage-meta">${formatFileState(file)}</p>
      <p class="storage-meta">${file.path}</p>
    `;
    workingFiles.appendChild(card);
  });
}

function renderArchive(archive) {
  archiveSummary.textContent = archive.exists
    ? `${archive.file_count} files in ${archive.path} • ${formatBytes(archive.total_size_bytes)} total`
    : `Archive directory missing: ${archive.path}`;

  archiveFiles.innerHTML = "";
  archive.latest_files.forEach((file) => {
    const item = document.createElement("li");
    item.innerHTML = `
      <strong>${file.name}</strong>
      <div class="storage-meta">${formatBytes(file.size_bytes)} • ${file.modified_at || "Unknown timestamp"}</div>
    `;
    archiveFiles.appendChild(item);
  });
}

function renderStatus(status) {
  const relay = status.relay;
  const config = status.config;
  const storage = status.storage;

  relayPill.textContent = relay.running ? "Server Running" : "Server Stopped";
  relayPill.className = `status-pill ${relay.running ? "status-running" : "status-stopped"}`;
  refreshLabel.textContent = `Last refreshed ${new Date().toLocaleTimeString()}`;

  processState.textContent = relay.running ? "Online" : "Offline";
  processMeta.textContent = relay.running
    ? `PID ${relay.pid} • up for ${formatSeconds(relay.uptime_seconds)}`
    : relay.last_exit_code == null
      ? "Relay has not started yet."
      : `Last exit code ${relay.last_exit_code}`;

  if (config.error) {
    configState.textContent = "Config Error";
    configMeta.textContent = config.error;
  } else {
    configState.textContent = config.pending_restart ? "Restart Needed" : "In Sync";
    configMeta.textContent = `${config.server_ip || "No server IP"} • updated ${config.updated_at || "unknown"}`;
  }

  const freshCount = storage.working_files.filter((file) => file.fresh).length;
  recordingState.textContent = `${freshCount}/${storage.working_files.length} active`;
  recordingMeta.textContent = `${storage.archive.file_count} archived files`;

  renderWorkingFiles(storage.working_files);
  renderArchive(storage.archive);
  logOutput.textContent = relay.log_tail.length ? relay.log_tail.join("\n") : "No logs yet.";
  logOutput.scrollTop = logOutput.scrollHeight;
}

async function refreshStatus() {
  try {
    const status = await api("/api/status", { method: "GET" });
    renderStatus(status);
  } catch (error) {
    actionMessage.textContent = error.message;
  }
}

async function loadConfig() {
  try {
    const payload = await api("/api/config", { method: "GET" });
    configEditor.value = payload.text;
  } catch (error) {
    configMessage.textContent = error.message;
  }
}

async function runRelayAction(action) {
  setBusy(commandButtons, true);
  actionMessage.textContent = `${action} in progress…`;

  try {
    const payload = await api(`/api/relay/${action}`, { method: "POST" });
    actionMessage.textContent = payload.message;
    await refreshStatus();
  } catch (error) {
    actionMessage.textContent = error.message;
  } finally {
    setBusy(commandButtons, false);
  }
}

async function saveConfig(restart) {
  setBusy([saveConfigButton, applyConfigButton], true);
  configMessage.textContent = restart ? "Saving config and restarting relay…" : "Saving config…";

  try {
    const payload = await api("/api/config", {
      method: "PUT",
      body: JSON.stringify({
        text: configEditor.value,
        restart,
      }),
    });
    configMessage.textContent = payload.message;
    await refreshStatus();
    await loadConfig();
  } catch (error) {
    configMessage.textContent = error.message;
  } finally {
    setBusy([saveConfigButton, applyConfigButton], false);
  }
}

commandButtons.forEach((button) => {
  button.addEventListener("click", () => runRelayAction(button.dataset.action));
});

saveConfigButton.addEventListener("click", () => saveConfig(false));
applyConfigButton.addEventListener("click", () => saveConfig(true));

window.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveConfig(false);
  }
});

async function boot() {
  await Promise.all([refreshStatus(), loadConfig()]);
  refreshTimer = window.setInterval(refreshStatus, 3000);
}

boot();
