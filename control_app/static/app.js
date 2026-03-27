const runtimePill = document.getElementById("runtime-pill");
const refreshLabel = document.getElementById("refresh-label");
const actionMessage = document.getElementById("action-message");
const roleState = document.getElementById("role-state");
const roleMeta = document.getElementById("role-meta");
const processState = document.getElementById("process-state");
const processMeta = document.getElementById("process-meta");
const configState = document.getElementById("config-state");
const configMeta = document.getElementById("config-meta");
const recordingMetric = document.getElementById("recording-metric");
const recordingState = document.getElementById("recording-state");
const recordingMeta = document.getElementById("recording-meta");
const archivePanel = document.getElementById("archive-panel");
const archiveSummary = document.getElementById("archive-summary");
const archiveFiles = document.getElementById("archive-files");
const logOutput = document.getElementById("log-output");
const configEditor = document.getElementById("config-editor");
const configMessage = document.getElementById("config-message");
const recordMessage = document.getElementById("record-message");

const roleSelect = document.getElementById("role-select");
const countryField = document.getElementById("country-field");
const countrySelect = document.getElementById("country-select");
const videoDeviceField = document.getElementById("video-device-field");
const videoDeviceSelect = document.getElementById("video-device-select");
const videoDeviceMessage = document.getElementById("video-device-message");
const audioDeviceField = document.getElementById("audio-device-field");
const audioDeviceSelect = document.getElementById("audio-device-select");
const audioDeviceMessage = document.getElementById("audio-device-message");
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
let videoDevices = [];
let audioDevices = [];

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
  const cameraLabel = launch.video_device ? ` • ${launch.video_device.split("/").pop()}` : "";
  if (launch.role === "sender") {
    const audioLabel = launch.audio_enabled ? `audio on${launch.audio_device ? ` (${launch.audio_device})` : ""}` : "audio off";
    return `Sender ${site}${cameraLabel} • ${audioLabel}`;
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
  const runtimeRole = latestStatus?.runtime?.running ? latestStatus.runtime.role : null;
  const serverContext = (runtimeRole || role) === "server";

  countryField.classList.toggle("hidden", !(sender || receiver));
  videoDeviceField.classList.toggle("hidden", !sender);
  audioDeviceField.classList.toggle("hidden", !sender);
  recordingMetric.classList.toggle("hidden", !serverContext);
  archivePanel.classList.toggle("hidden", !serverContext);
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
  if (launch.video_device) {
    ensureVideoDeviceOption(launch.video_device);
    videoDeviceSelect.value = launch.video_device;
  }
  ensureAudioDeviceOption(launch.audio_device);
  audioDeviceSelect.value = launch.audio_enabled ? (launch.audio_device || "") : "";
  applyRoleFormState();
}

function ensureVideoDeviceOption(path) {
  const existing = Array.from(videoDeviceSelect.options).find((option) => option.value === path);
  if (existing) {
    return;
  }

  const option = document.createElement("option");
  option.value = path;
  option.textContent = path.split("/").pop() || path;
  videoDeviceSelect.appendChild(option);
}

function ensureAudioDeviceOption(path) {
  if (!path) {
    return;
  }

  const existing = Array.from(audioDeviceSelect.options).find((option) => option.value === path);
  if (existing) {
    return;
  }

  const option = document.createElement("option");
  option.value = path;
  option.textContent = path;
  audioDeviceSelect.appendChild(option);
}

function renderVideoDevices(devices) {
  const currentValue = videoDeviceSelect.value;
  videoDeviceSelect.innerHTML = "";

  if (!devices.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No cameras found";
    videoDeviceSelect.appendChild(option);
    videoDeviceSelect.disabled = true;
    videoDeviceMessage.textContent = "No camera devices are currently visible inside the container.";
    return;
  }

  videoDeviceSelect.disabled = false;
  devices.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.path;
    option.textContent = device.alias_path
      ? `${device.label} (${device.alias_path.split("/").pop()})`
      : `${device.label} (${device.path.split("/").pop()})`;
    videoDeviceSelect.appendChild(option);
  });

  const selected = devices.some((device) => device.path === currentValue)
    ? currentValue
    : latestStatus?.runtime?.launch?.video_device || devices[0].path;
  videoDeviceSelect.value = selected;
  videoDeviceMessage.textContent = `${devices.length} camera device${devices.length === 1 ? "" : "s"} discovered inside the container.`;
}

function renderAudioDevices(devices) {
  const currentValue = audioDeviceSelect.value;
  audioDeviceSelect.innerHTML = "";

  const blankOption = document.createElement("option");
  blankOption.value = "";
  blankOption.textContent = "No audio input";
  audioDeviceSelect.appendChild(blankOption);

  if (!devices.length) {
    audioDeviceSelect.disabled = true;
    audioDeviceMessage.textContent = "No capture devices are currently visible inside the container. Audio will stay disabled.";
    return;
  }

  audioDeviceSelect.disabled = false;
  devices.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.path;
    option.textContent = `${device.label} (${device.path})`;
    audioDeviceSelect.appendChild(option);
  });

  const selected = devices.some((device) => device.path === currentValue)
    ? currentValue
    : latestStatus?.runtime?.launch?.audio_enabled
      ? latestStatus.runtime.launch.audio_device || ""
      : "";
  audioDeviceSelect.value = selected;
  audioDeviceMessage.textContent = `${devices.length} audio input${devices.length === 1 ? "" : "s"} discovered inside the container.`;
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
  const serverContext = (runtime.running ? runtime.role : roleSelect.value) === "server";

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

  recordingMetric.classList.toggle("hidden", !serverContext);
  serverPanel.classList.toggle("hidden", !serverActive);
  archivePanel.classList.toggle("hidden", !serverContext);
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

async function loadVideoDevices() {
  try {
    const payload = await api("/api/devices/video", { method: "GET" });
    videoDevices = payload.devices || [];
    renderVideoDevices(videoDevices);
  } catch (error) {
    videoDevices = [];
    videoDeviceSelect.innerHTML = '<option value="">Camera scan failed</option>';
    videoDeviceSelect.disabled = true;
    videoDeviceMessage.textContent = error.message;
  }
}

async function loadAudioDevices() {
  try {
    const payload = await api("/api/devices/audio", { method: "GET" });
    audioDevices = payload.devices || [];
    renderAudioDevices(audioDevices);
  } catch (error) {
    audioDevices = [];
    audioDeviceSelect.innerHTML = '<option value="">Audio scan failed</option>';
    audioDeviceSelect.disabled = true;
    audioDeviceMessage.textContent = error.message;
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
    payload.video_device = videoDeviceSelect.value || null;
    payload.audio_device = audioDeviceSelect.value || null;
    payload.audio_enabled = Boolean(payload.audio_device);
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

roleSelect.addEventListener("change", async () => {
  applyRoleFormState();
  if (roleSelect.value === "sender") {
    await Promise.all([loadVideoDevices(), loadAudioDevices()]);
  }
});
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
  await Promise.all([refreshStatus(), loadConfig(), loadVideoDevices(), loadAudioDevices()]);
  refreshTimer = window.setInterval(refreshStatus, 3000);
}

boot();
