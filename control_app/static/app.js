const runtimePill = document.getElementById("runtime-pill");
const refreshLabel = document.getElementById("refresh-label");
const actionMessage = document.getElementById("action-message");
const roleState = document.getElementById("role-state");
const roleMeta = document.getElementById("role-meta");
const processState = document.getElementById("process-state");
const processMeta = document.getElementById("process-meta");
const configState = document.getElementById("config-state");
const configMeta = document.getElementById("config-meta");
const recordingState = document.getElementById("recording-state");
const recordingMeta = document.getElementById("recording-meta");
const archiveSummary = document.getElementById("archive-summary");
const archiveFiles = document.getElementById("archive-files");
const logOutput = document.getElementById("log-output");
const configEditor = document.getElementById("config-editor");
const configMessage = document.getElementById("config-message");
const recordMessage = document.getElementById("record-message");

const roleSelect = document.getElementById("role-select");
const countryField = document.getElementById("country-field");
const countrySelect = document.getElementById("country-select");
const audioToggleField = document.getElementById("audio-toggle-field");
const audioEnabled = document.getElementById("audio-enabled");
const audioDeviceField = document.getElementById("audio-device-field");
const audioDeviceInput = document.getElementById("audio-device");
const startRoleButton = document.getElementById("start-role");
const stopRoleButton = document.getElementById("stop-role");
const saveConfigButton = document.getElementById("save-config");
const applyConfigButton = document.getElementById("apply-config");
const serverPanel = document.getElementById("server-panel");
const recordToggleButton = document.getElementById("record-toggle");

const previewTnMeta = document.getElementById("preview-tn-meta");
const previewTnImage = document.getElementById("preview-tn-image");
const previewTnEmpty = document.getElementById("preview-tn-empty");
const previewDkMeta = document.getElementById("preview-dk-meta");
const previewDkImage = document.getElementById("preview-dk-image");
const previewDkEmpty = document.getElementById("preview-dk-empty");

let refreshTimer = null;
let latestStatus = null;

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

function describeLaunch(launch) {
  if (!launch || !launch.role) {
    return "No role selected yet.";
  }

  if (launch.role === "server") {
    return "Server role";
  }

  const site = launch.country ? launch.country.toUpperCase() : "Unknown site";
  if (launch.role === "sender") {
    const audioLabel = launch.audio_enabled ? `audio on${launch.audio_device ? ` (${launch.audio_device})` : ""}` : "audio off";
    return `Sender ${site} • ${audioLabel}`;
  }

  return `Receiver ${site}`;
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

function applyRoleFormState() {
  const role = roleSelect.value;
  const sender = role === "sender";
  const receiver = role === "receiver";

  countryField.classList.toggle("hidden", !(sender || receiver));
  audioToggleField.classList.toggle("hidden", !sender);
  audioDeviceField.classList.toggle("hidden", !sender || !audioEnabled.checked);
}

function syncFormFromRuntime(runtime) {
  const launch = runtime.launch;
  if (!launch) {
    applyRoleFormState();
    return;
  }

  roleSelect.value = launch.role;
  if (launch.country) {
    countrySelect.value = launch.country;
  }
  audioEnabled.checked = Boolean(launch.audio_enabled);
  audioDeviceInput.value = launch.audio_device || "";
  applyRoleFormState();
}

function renderPreview(feed, preview, image, meta, empty) {
  if (!preview || !preview.available) {
    image.removeAttribute("src");
    image.classList.add("hidden");
    empty.classList.remove("hidden");
    meta.textContent = "No snapshot yet.";
    return;
  }

  image.src = `/api/server/preview/${feed}.jpg?t=${Date.now()}`;
  image.classList.remove("hidden");
  empty.classList.add("hidden");
  meta.textContent = `Updated ${formatSeconds(preview.age_seconds)} ago`;
}

function renderStatus(status) {
  latestStatus = status;
  const runtime = status.runtime;
  const config = status.config;
  const storage = status.storage;
  const server = runtime.server;
  const recording = server?.recording;
  const launch = runtime.launch;
  const serverActive = runtime.running && runtime.role === "server";

  syncFormFromRuntime(runtime);

  runtimePill.textContent = runtime.running ? `${runtime.role || "Role"} Running` : "No Active Role";
  runtimePill.className = `status-pill ${runtime.running ? "status-running" : "status-stopped"}`;
  refreshLabel.textContent = `Last refreshed ${new Date().toLocaleTimeString()}`;

  roleState.textContent = launch?.role ? launch.role.toUpperCase() : "Idle";
  roleMeta.textContent = describeLaunch(launch);

  processState.textContent = runtime.running ? "Online" : "Offline";
  processMeta.textContent = runtime.running
    ? runtime.pid
      ? `PID ${runtime.pid} • up for ${formatSeconds(runtime.uptime_seconds)}`
      : `In-process runtime • up for ${formatSeconds(runtime.uptime_seconds)}`
    : runtime.last_exit_code == null
      ? "Nothing is running."
      : `Last exit code ${runtime.last_exit_code}`;

  if (config.error) {
    configState.textContent = "Config Error";
    configMeta.textContent = config.error;
  } else {
    configState.textContent = config.pending_relaunch ? "Relaunch Needed" : "In Sync";
    configMeta.textContent = `${config.server_ip || "No server IP"} • updated ${config.updated_at || "unknown"}`;
  }

  if (!serverActive) {
    recordingState.textContent = "Idle";
    recordingMeta.textContent = `${storage.archive.file_count} archived files`;
  } else {
    recordingState.textContent = recording?.active ? "Recording" : "Ready";
    recordingMeta.textContent = recording?.active
      ? `Started ${new Date(recording.started_at).toLocaleTimeString()}`
      : `${storage.archive.file_count} archived files`;
  }

  recordToggleButton.textContent = recording?.active ? "Stop Recording" : "Start Recording";
  recordToggleButton.disabled = !serverActive;

  serverPanel.classList.toggle("hidden", !serverActive);
  renderPreview("tn", server?.previews?.tn, previewTnImage, previewTnMeta, previewTnEmpty);
  renderPreview("dk", server?.previews?.dk, previewDkImage, previewDkMeta, previewDkEmpty);

  renderArchive(storage.archive);
  logOutput.textContent = runtime.log_tail.length ? runtime.log_tail.join("\n") : "No logs yet.";
  logOutput.scrollTop = logOutput.scrollHeight;

  stopRoleButton.disabled = !runtime.running;
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

function buildLaunchPayload() {
  const payload = {
    role: roleSelect.value,
  };

  if (payload.role === "sender" || payload.role === "receiver") {
    payload.country = countrySelect.value;
  }

  if (payload.role === "sender") {
    payload.audio_enabled = audioEnabled.checked;
    payload.audio_device = audioDeviceInput.value.trim();
  }

  return payload;
}

async function startRole() {
  setBusy([startRoleButton, stopRoleButton], true);
  actionMessage.textContent = "Starting selected role…";

  try {
    const payload = await api("/api/runtime/start", {
      method: "POST",
      body: JSON.stringify(buildLaunchPayload()),
    });
    actionMessage.textContent = payload.message;
    await refreshStatus();
  } catch (error) {
    actionMessage.textContent = error.message;
  } finally {
    setBusy([startRoleButton, stopRoleButton], false);
  }
}

async function stopRole() {
  setBusy([startRoleButton, stopRoleButton], true);
  actionMessage.textContent = "Stopping active role…";

  try {
    const payload = await api("/api/runtime/stop", { method: "POST" });
    actionMessage.textContent = payload.message;
    await refreshStatus();
  } catch (error) {
    actionMessage.textContent = error.message;
  } finally {
    setBusy([startRoleButton, stopRoleButton], false);
  }
}

async function toggleRecording() {
  if (!latestStatus?.runtime?.running || latestStatus.runtime.role !== "server") {
    return;
  }

  const action = latestStatus.runtime.server?.recording?.active ? "stop" : "start";
  setBusy([recordToggleButton], true);
  recordMessage.textContent = action === "start" ? "Starting recording…" : "Stopping recording…";

  try {
    const payload = await api(`/api/server/recording/${action}`, { method: "POST" });
    recordMessage.textContent = payload.message;
    await refreshStatus();
  } catch (error) {
    recordMessage.textContent = error.message;
  } finally {
    setBusy([recordToggleButton], false);
  }
}

async function saveConfig(restart) {
  setBusy([saveConfigButton, applyConfigButton], true);
  configMessage.textContent = restart ? "Saving config and relaunching active role…" : "Saving config…";

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

roleSelect.addEventListener("change", applyRoleFormState);
audioEnabled.addEventListener("change", applyRoleFormState);
startRoleButton.addEventListener("click", startRole);
stopRoleButton.addEventListener("click", stopRole);
recordToggleButton.addEventListener("click", toggleRecording);
saveConfigButton.addEventListener("click", () => saveConfig(false));
applyConfigButton.addEventListener("click", () => saveConfig(true));

window.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveConfig(false);
  }
});

async function boot() {
  applyRoleFormState();
  await Promise.all([refreshStatus(), loadConfig()]);
  refreshTimer = window.setInterval(refreshStatus, 3000);
}

boot();
