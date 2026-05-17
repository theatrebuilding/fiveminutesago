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
const archiveWarning = document.getElementById("archive-warning");
const archiveFiles = document.getElementById("archive-files");
const archiveRefreshButton = document.getElementById("archive-refresh-button");
const archiveSelectedName = document.getElementById("archive-selected-name");
const archiveSelectedMeta = document.getElementById("archive-selected-meta");
const archiveOpenLink = document.getElementById("archive-open-link");
const archiveDownloadLink = document.getElementById("archive-download-link");
const archiveRenameButton = document.getElementById("archive-rename-button");
const archiveDeleteButton = document.getElementById("archive-delete-button");
const archiveActionMessage = document.getElementById("archive-action-message");
const logOutput = document.getElementById("log-output");
const configPanelTitle = document.getElementById("config-panel-title");
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
const senderAudioModeField = document.getElementById("sender-audio-mode-field");
const senderAudioModeSelect = document.getElementById("sender-audio-mode-select");
const senderPlaybackDeviceField = document.getElementById("sender-playback-device-field");
const senderPlaybackDeviceSelect = document.getElementById("sender-playback-device-select");
const senderPlaybackDeviceMessage = document.getElementById("sender-playback-device-message");
const senderAudioDelayField = document.getElementById("sender-audio-delay-field");
const senderAudioDelayInput = document.getElementById("sender-audio-delay-input");
const senderAudioDelayValue = document.getElementById("sender-audio-delay-value");
const senderAudioDelayMessage = document.getElementById("sender-audio-delay-message");
const receiverAudioField = document.getElementById("receiver-audio-field");
const receiverAudioSelect = document.getElementById("receiver-audio-select");
const receiverAudioMessage = document.getElementById("receiver-audio-message");
const receiverPlaybackDeviceField = document.getElementById("receiver-playback-device-field");
const receiverPlaybackDeviceSelect = document.getElementById("receiver-playback-device-select");
const receiverPlaybackDeviceMessage = document.getElementById("receiver-playback-device-message");
const receiverVideoOutputField = document.getElementById("receiver-video-output-field");
const receiverVideoOutputSelect = document.getElementById("receiver-video-output-select");
const receiverVideoOutputMessage = document.getElementById("receiver-video-output-message");
const receiverVideoDelayField = document.getElementById("receiver-video-delay-field");
const receiverVideoDelayInput = document.getElementById("receiver-video-delay-input");
const receiverVideoDelayValue = document.getElementById("receiver-video-delay-value");
const receiverVideoDelayMessage = document.getElementById("receiver-video-delay-message");
const startRoleButton = document.getElementById("start-role");
const saveConfigButton = document.getElementById("save-config");
const applyConfigButton = document.getElementById("apply-config");
const showConfigButton = document.getElementById("show-config");
const serverPanel = document.getElementById("server-panel");
const senderPanel = document.getElementById("sender-panel");
const receiverPanel = document.getElementById("receiver-panel");
const recordToggleButton = document.getElementById("record-toggle");

const previewTnMeta = document.getElementById("preview-tn-meta");
const previewTnImage = document.getElementById("preview-tn-image");
const previewTnEmpty = document.getElementById("preview-tn-empty");
const previewDkMeta = document.getElementById("preview-dk-meta");
const previewDkImage = document.getElementById("preview-dk-image");
const previewDkEmpty = document.getElementById("preview-dk-empty");
const senderPreviewTitle = document.getElementById("sender-preview-title");
const senderPreviewMeta = document.getElementById("sender-preview-meta");
const senderPreviewImage = document.getElementById("sender-preview-image");
const senderPreviewEmpty = document.getElementById("sender-preview-empty");
const receiverPreviewTitle = document.getElementById("receiver-preview-title");
const receiverPreviewMeta = document.getElementById("receiver-preview-meta");
const receiverPreviewImage = document.getElementById("receiver-preview-image");
const receiverPreviewEmpty = document.getElementById("receiver-preview-empty");

let refreshTimer = null;
let latestStatus = null;
let videoDevices = [];
let audioDevices = [];
let playbackDevices = [];
let displayOutputs = [];
let launchFormDirty = false;
let selectedArchiveName = null;
let selectedArchiveRevision = null;
let selectedArchiveFile = null;
let lastConfigPanelRole = null;

const AUDIO_OFF_VALUE = "__audio_off__";
const AUDIO_TEST_VALUE = "__audio_test__";
const AUDIO_DEFAULT_DEVICE_VALUE = "__audio_default__";
const AUDIO_PLAYBACK_DEFAULT_DEVICE_VALUE = "__audio_playback_default__";
const RECEIVER_AUDIO_PLAYBACK_DEFAULT_DEVICE_VALUE = "__receiver_audio_playback_default__";
const RECEIVER_VIDEO_OUTPUT_AUTO_VALUE = "__receiver_video_output_auto__";
const VIDEO_CONFIG_SOURCE_VALUE = "__video_config__";
const VIDEO_TEST_SOURCE_VALUE = "__video_test__";
const MAX_SYNC_DELAY_MS = 3000;
const SYNC_DELAY_DEBOUNCE_MS = 250;

let syncDelayTimer = null;

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

function normalizeSyncDelayMs(value) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return 0;
  }
  return Math.min(MAX_SYNC_DELAY_MS, Math.max(0, parsed));
}

function formatSyncDelay(value) {
  return `${normalizeSyncDelayMs(value)} ms`;
}

function updateSyncDelayLabels() {
  senderAudioDelayValue.textContent = formatSyncDelay(senderAudioDelayInput.value);
  receiverVideoDelayValue.textContent = formatSyncDelay(receiverVideoDelayInput.value);
}

function describeSenderAudioChoice(launch) {
  const source = launch?.audio_source || (launch?.audio_enabled ? "device" : "off");
  const senderAudioMode = launch?.sender_audio_mode || "aec";
  if (source === "off") {
    return "audio off";
  }

  let sourceLabel = "";
  if (source === "test") {
    sourceLabel = "test tone";
  } else {
    sourceLabel = launch.audio_device ? `mic (${launch.audio_device})` : "mic (config default)";
  }

  if (senderAudioMode === "capture-only") {
    return `${sourceLabel} • capture only`;
  }

  const delayMs = normalizeSyncDelayMs(launch.sender_audio_delay_ms);
  const delayLabel = delayMs ? ` • audio delay ${delayMs} ms` : "";
  return `${sourceLabel} • playback+dsp${delayLabel}`;
}

function shouldShowSenderPlaybackField() {
  if (roleSelect.value !== "sender") {
    return false;
  }
  if (senderAudioModeSelect.value !== "aec") {
    return false;
  }
  const selectedAudioValue = audioDeviceSelect.value || AUDIO_OFF_VALUE;
  return selectedAudioValue !== AUDIO_OFF_VALUE;
}

function shouldShowSenderAudioDelayField() {
  return shouldShowSenderPlaybackField();
}

function getLaunchVideoSource(launch) {
  if (launch?.video_device) {
    return "device";
  }
  return launch?.video_source || "test";
}

function describeSenderVideoChoice(launch) {
  if (launch?.video_device) {
    return launch.video_device.split("/").pop() || launch.video_device;
  }

  return getLaunchVideoSource(launch) === "config" ? "config video source" : "test signal";
}

function describeReceiverAudioChoice(launch) {
  const transport = normalizeReceiverAudioTransport(launch?.receiver_audio_transport).toUpperCase();
  if (transport === "CONFIG") {
    return "audio from config";
  }
  if (transport === "L16") {
    return "uncompressed audio";
  }
  if (transport === "AAC") {
    return "AAC from muxed stream";
  }
  return `audio ${transport}`;
}

function normalizeReceiverAudioTransport(value) {
  const normalized = String(value || "config").trim().toLowerCase();
  if (normalized === "muxed") {
    return "aac";
  }
  if (normalized === "pcm" || normalized === "uncompressed") {
    return "l16";
  }
  return normalized || "config";
}

function describeReceiverVideoChoice(launch) {
  const delayMs = normalizeSyncDelayMs(launch?.receiver_video_delay_ms);
  const delayLabel = delayMs ? ` • video delay ${delayMs} ms` : "";
  if (launch?.receiver_video_output) {
    return `display ${launch.receiver_video_output}${delayLabel}`;
  }
  return `auto display${delayLabel}`;
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
    const videoLabel = describeSenderVideoChoice(launch);
    const audioLabel = describeSenderAudioChoice(launch);
    return `Sender ${site} • ${videoLabel} • ${audioLabel}`;
  }

  return `Receiver ${site} • ${describeReceiverVideoChoice(launch)} • ${describeReceiverAudioChoice(launch)}`;
}

function formatCountryLabel(country) {
  if (country === "tn") {
    return "Tunisia";
  }
  if (country === "dk") {
    return "Denmark";
  }
  return country ? country.toUpperCase() : "Receiver";
}

function archiveFileUrl(file) {
  return `/api/archive/files/${encodeURIComponent(file.name)}`;
}

function archiveDownloadUrl(file) {
  return `/api/archive/files/${encodeURIComponent(file.name)}/download`;
}

function formatArchiveRefreshedAt(value) {
  if (!value) {
    return "not refreshed yet";
  }
  return new Date(value).toLocaleTimeString();
}

function clearArchiveSelection(message = "Select a file and open it in a new tab.") {
  selectedArchiveFile = null;
  archiveSelectedName.textContent = "No file selected";
  archiveSelectedMeta.textContent = message;
  archiveOpenLink.removeAttribute("href");
  archiveOpenLink.classList.add("hidden");
  archiveDownloadLink.removeAttribute("href");
  archiveDownloadLink.classList.add("hidden");
  archiveRenameButton.disabled = true;
  archiveDeleteButton.disabled = true;
  selectedArchiveRevision = null;
}

function renderArchiveSelection(file) {
  selectedArchiveFile = file;
  const nextRevision = String(file.modified_at_ts || file.size_bytes || file.name);
  if (selectedArchiveName !== file.name) {
    selectedArchiveName = file.name;
  }

  if (selectedArchiveRevision !== nextRevision) {
    selectedArchiveRevision = nextRevision;
  }

  archiveSelectedName.textContent = file.name;
  archiveSelectedMeta.textContent = `${formatBytes(file.size_bytes)} • ${file.modified_at || "Unknown timestamp"}`;
  archiveOpenLink.href = archiveFileUrl(file);
  archiveOpenLink.classList.remove("hidden");
  archiveDownloadLink.href = archiveDownloadUrl(file);
  archiveDownloadLink.classList.remove("hidden");
  archiveRenameButton.disabled = false;
  archiveDeleteButton.disabled = false;
}

function renderArchive(storage) {
  const archive = storage?.archive || {};
  const refreshedAt = formatArchiveRefreshedAt(archive.refreshed_at);
  archiveSummary.textContent = archive.exists
    ? `${archive.file_count} files in ${archive.path} • ${formatBytes(archive.total_size_bytes)} total • scanned ${refreshedAt}`
    : `Archive directory missing: ${archive.path} • scanned ${refreshedAt}`;
  archiveWarning.textContent = storage?.warning || "";
  archiveWarning.classList.toggle("hidden", !storage?.warning);

  archiveFiles.innerHTML = "";
  const files = archive.latest_files || [];
  files.forEach((file) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "archive-file-button";
    if (file.name === selectedArchiveName) {
      button.classList.add("is-selected");
    }
    button.innerHTML = `
      <strong>${file.name}</strong>
      <div class="storage-meta">${formatBytes(file.size_bytes)} • ${file.modified_at || "Unknown timestamp"}</div>
    `;
    button.addEventListener("click", () => {
      selectedArchiveName = file.name;
      renderArchive(latestStatus?.storage || storage);
    });
    item.appendChild(button);
    archiveFiles.appendChild(item);
  });

  if (!files.length) {
    selectedArchiveName = null;
    clearArchiveSelection("No archived TS or MP4 files are available yet.");
    return;
  }

  const selectedFile = files.find((file) => file.name === selectedArchiveName) || null;
  if (selectedFile) {
    renderArchiveSelection(selectedFile);
    return;
  }

  clearArchiveSelection("Select a file and open it in a new tab.");
}

function getConfigPanelRole() {
  return latestStatus?.runtime?.running ? latestStatus.runtime.role : roleSelect.value;
}

function applyConfigPanelState() {
  const role = getConfigPanelRole();
  const editable = role === "server";
  const roleChanged = role !== lastConfigPanelRole;
  const configShown = configEditor.dataset.configShown === "true";
  lastConfigPanelRole = role;

  configPanelTitle.textContent = editable ? "Config Editor" : "Server Config";
  saveConfigButton.classList.toggle("hidden", !editable);
  applyConfigButton.classList.toggle("hidden", !editable);
  showConfigButton.classList.toggle("hidden", editable);
  showConfigButton.textContent = configShown ? "Update config" : "Show Config";
  configEditor.readOnly = !editable;

  if (editable) {
    configEditor.classList.remove("hidden");
    configEditor.dataset.configShown = "true";
    if (roleChanged) {
      configMessage.textContent = "";
    }
    return;
  }

  if (roleChanged) {
    configEditor.classList.add("hidden");
    configEditor.dataset.configShown = "false";
    showConfigButton.textContent = "Show Config";
    configMessage.textContent = "Click Show Config to read the central server config mounted on this Pi.";
  } else if (configEditor.dataset.configShown !== "true") {
    configEditor.classList.add("hidden");
    showConfigButton.textContent = "Show Config";
  }
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
  senderAudioModeField.classList.toggle("hidden", !sender);
  senderPlaybackDeviceField.classList.toggle("hidden", !shouldShowSenderPlaybackField());
  senderAudioDelayField.classList.toggle("hidden", !shouldShowSenderAudioDelayField());
  receiverAudioField.classList.toggle("hidden", !receiver);
  receiverPlaybackDeviceField.classList.toggle("hidden", !receiver);
  receiverVideoOutputField.classList.toggle("hidden", !receiver);
  receiverVideoDelayField.classList.toggle("hidden", !receiver);
  recordingMetric.classList.toggle("hidden", !serverContext);
  archivePanel.classList.toggle("hidden", !serverContext);
  updateSyncDelayLabels();
  applyConfigPanelState();
}

function markLaunchFormDirty() {
  launchFormDirty = true;
}

function syncFormFromRuntime(runtime) {
  if (!runtime.running || launchFormDirty) {
    applyRoleFormState();
    return;
  }

  const launch = runtime.launch;
  if (!launch) {
    applyRoleFormState();
    return;
  }

  roleSelect.value = launch.role;
  if (launch.country) {
    countrySelect.value = launch.country;
  }
  if (launch.role === "sender") {
    const audioSource = launch.audio_source || (launch.audio_enabled ? "device" : "off");
    senderAudioModeSelect.value = launch.sender_audio_mode || "aec";
    if (launch.video_device) {
      ensureVideoDeviceOption(launch.video_device);
      videoDeviceSelect.value = launch.video_device;
    } else if (getLaunchVideoSource(launch) === "config") {
      videoDeviceSelect.value = VIDEO_CONFIG_SOURCE_VALUE;
    } else {
      videoDeviceSelect.value = VIDEO_TEST_SOURCE_VALUE;
    }
    ensureAudioDeviceOption(launch.audio_device);
    if (audioSource === "test") {
      audioDeviceSelect.value = AUDIO_TEST_VALUE;
    } else if (audioSource === "device") {
      audioDeviceSelect.value = launch.audio_device || AUDIO_DEFAULT_DEVICE_VALUE;
    } else {
      audioDeviceSelect.value = AUDIO_OFF_VALUE;
    }
    ensurePlaybackDeviceOption(launch.sender_playback_device);
    senderPlaybackDeviceSelect.value = launch.sender_playback_device || AUDIO_PLAYBACK_DEFAULT_DEVICE_VALUE;
    senderAudioDelayInput.value = normalizeSyncDelayMs(launch.sender_audio_delay_ms);
  }

  if (launch.role === "receiver") {
    receiverAudioSelect.value = normalizeReceiverAudioTransport(launch.receiver_audio_transport);
    ensureReceiverPlaybackDeviceOption(launch.receiver_playback_device);
    receiverPlaybackDeviceSelect.value = launch.receiver_playback_device || RECEIVER_AUDIO_PLAYBACK_DEFAULT_DEVICE_VALUE;
    ensureReceiverVideoOutputOption(
      launch.receiver_video_output,
      launch.receiver_video_output ? `Unavailable display output (${launch.receiver_video_output})` : null,
    );
    receiverVideoOutputSelect.value = launch.receiver_video_output || RECEIVER_VIDEO_OUTPUT_AUTO_VALUE;
    receiverVideoDelayInput.value = normalizeSyncDelayMs(launch.receiver_video_delay_ms);
  }
  applyRoleFormState();
}

function ensureVideoDeviceOption(path) {
  if (!path) {
    return;
  }

  const existing = Array.from(videoDeviceSelect.options).find((option) => option.value === path);
  if (existing) {
    return;
  }

  const option = document.createElement("option");
  option.value = path;
  option.textContent = `Unavailable camera override (${path})`;
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

function ensurePlaybackDeviceOption(path) {
  if (!path) {
    return;
  }

  const existing = Array.from(senderPlaybackDeviceSelect.options).find((option) => option.value === path);
  if (existing) {
    return;
  }

  const option = document.createElement("option");
  option.value = path;
  option.textContent = path;
  senderPlaybackDeviceSelect.appendChild(option);
}

function ensureReceiverPlaybackDeviceOption(path) {
  if (!path) {
    return;
  }

  const existing = Array.from(receiverPlaybackDeviceSelect.options).find((option) => option.value === path);
  if (existing) {
    return;
  }

  const option = document.createElement("option");
  option.value = path;
  option.textContent = path;
  receiverPlaybackDeviceSelect.appendChild(option);
}

function ensureReceiverVideoOutputOption(value, label = null) {
  if (!value) {
    return;
  }

  const existing = Array.from(receiverVideoOutputSelect.options).find((option) => option.value === value);
  if (existing) {
    return;
  }

  const option = document.createElement("option");
  option.value = value;
  option.textContent = label || `Unavailable display output (${value})`;
  receiverVideoOutputSelect.appendChild(option);
}

function renderVideoDevices(devices) {
  const currentValue = videoDeviceSelect.value;
  const runtimeLaunch = latestStatus?.runtime?.launch;
  const runtimeVideoSource = runtimeLaunch?.role === "sender" ? getLaunchVideoSource(runtimeLaunch) : undefined;
  const runtimeSenderVideoDevice = runtimeLaunch?.role === "sender" ? runtimeLaunch.video_device : undefined;
  videoDeviceSelect.innerHTML = "";

  const defaultOption = document.createElement("option");
  defaultOption.value = VIDEO_CONFIG_SOURCE_VALUE;
  defaultOption.textContent = "Use config video source";
  videoDeviceSelect.appendChild(defaultOption);

  const testOption = document.createElement("option");
  testOption.value = VIDEO_TEST_SOURCE_VALUE;
  testOption.textContent = "Test signal";
  videoDeviceSelect.appendChild(testOption);

  devices.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.path;
    option.textContent = device.alias_path
      ? `${device.label} (${device.alias_path.split("/").pop()})`
      : `${device.label} (${device.path.split("/").pop()})`;
    videoDeviceSelect.appendChild(option);
  });
  ensureVideoDeviceOption(runtimeSenderVideoDevice);
  videoDeviceSelect.disabled = false;

  if (!devices.length) {
    if (launchFormDirty && currentValue === VIDEO_TEST_SOURCE_VALUE) {
      videoDeviceSelect.value = VIDEO_TEST_SOURCE_VALUE;
    } else {
      videoDeviceSelect.value = runtimeVideoSource === "test" ? VIDEO_TEST_SOURCE_VALUE : VIDEO_CONFIG_SOURCE_VALUE;
    }
    videoDeviceMessage.textContent = "No camera devices are currently visible inside the container. Sender can still use the config video source or the test signal.";
    return;
  }

  let selected = VIDEO_CONFIG_SOURCE_VALUE;
  if (
    launchFormDirty &&
    (
      currentValue === VIDEO_CONFIG_SOURCE_VALUE ||
      currentValue === VIDEO_TEST_SOURCE_VALUE ||
      devices.some((device) => device.path === currentValue)
    )
  ) {
    selected = currentValue;
  } else if (runtimeVideoSource === "test") {
    selected = VIDEO_TEST_SOURCE_VALUE;
  } else if (runtimeVideoSource === "device" && runtimeSenderVideoDevice) {
    selected = runtimeSenderVideoDevice;
  } else if (runtimeVideoSource === "config") {
    selected = VIDEO_CONFIG_SOURCE_VALUE;
  }
  videoDeviceSelect.value = selected;
  videoDeviceMessage.textContent = `${devices.length} camera device${devices.length === 1 ? "" : "s"} discovered inside the container. Choose a device, the config video source, or the test signal.`;
}

function renderAudioDevices(devices) {
  const currentValue = audioDeviceSelect.value;
  const runtimeLaunch = latestStatus?.runtime?.launch;
  const runtimeAudioSource = runtimeLaunch?.role === "sender"
    ? (runtimeLaunch.audio_source || (runtimeLaunch.audio_enabled ? "device" : "off"))
    : undefined;
  const runtimeAudioDevice = runtimeLaunch?.role === "sender" ? runtimeLaunch.audio_device : undefined;
  audioDeviceSelect.innerHTML = "";

  const offOption = document.createElement("option");
  offOption.value = AUDIO_OFF_VALUE;
  offOption.textContent = "No audio input";
  audioDeviceSelect.appendChild(offOption);

  const testOption = document.createElement("option");
  testOption.value = AUDIO_TEST_VALUE;
  testOption.textContent = "Test audio signal";
  audioDeviceSelect.appendChild(testOption);

  const defaultOption = document.createElement("option");
  defaultOption.value = AUDIO_DEFAULT_DEVICE_VALUE;
  defaultOption.textContent = "Default input from config";
  audioDeviceSelect.appendChild(defaultOption);

  devices.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.path;
    option.textContent = `${device.label} (${device.path})`;
    audioDeviceSelect.appendChild(option);
  });
  ensureAudioDeviceOption(runtimeAudioDevice);

  audioDeviceSelect.disabled = false;

  let selected = AUDIO_OFF_VALUE;
  if (
    launchFormDirty &&
    (currentValue === AUDIO_OFF_VALUE ||
      currentValue === AUDIO_TEST_VALUE ||
      currentValue === AUDIO_DEFAULT_DEVICE_VALUE ||
      devices.some((device) => device.path === currentValue))
  ) {
    selected = currentValue;
  } else if (runtimeAudioSource === "test") {
    selected = AUDIO_TEST_VALUE;
  } else if (runtimeAudioSource === "device") {
    selected = runtimeAudioDevice || AUDIO_DEFAULT_DEVICE_VALUE;
  }
  audioDeviceSelect.value = selected;
  if (!devices.length) {
    audioDeviceMessage.textContent = "No capture devices are currently visible inside the container. Sender can still use the config default input or the test signal.";
    return;
  }

  audioDeviceMessage.textContent = `${devices.length} audio input${devices.length === 1 ? "" : "s"} discovered inside the container. Choose a device, the config default input, or the test signal.`;
}

function renderPlaybackDevices(devices) {
  const currentValue = senderPlaybackDeviceSelect.value;
  const runtimeLaunch = latestStatus?.runtime?.launch;
  const runtimePlaybackDevice = runtimeLaunch?.role === "sender" ? runtimeLaunch.sender_playback_device : undefined;
  senderPlaybackDeviceSelect.innerHTML = "";

  const defaultOption = document.createElement("option");
  defaultOption.value = AUDIO_PLAYBACK_DEFAULT_DEVICE_VALUE;
  defaultOption.textContent = "Default output from config";
  senderPlaybackDeviceSelect.appendChild(defaultOption);

  devices.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.path;
    option.textContent = `${device.label} (${device.path})`;
    senderPlaybackDeviceSelect.appendChild(option);
  });
  ensurePlaybackDeviceOption(runtimePlaybackDevice);
  senderPlaybackDeviceSelect.disabled = false;

  let selected = AUDIO_PLAYBACK_DEFAULT_DEVICE_VALUE;
  if (
    launchFormDirty &&
    (currentValue === AUDIO_PLAYBACK_DEFAULT_DEVICE_VALUE ||
      devices.some((device) => device.path === currentValue))
  ) {
    selected = currentValue;
  } else if (runtimePlaybackDevice) {
    selected = runtimePlaybackDevice;
  }
  senderPlaybackDeviceSelect.value = selected;

  if (!devices.length) {
    senderPlaybackDeviceMessage.textContent = "No playback devices are currently visible inside the container. Sender can still use the config default output.";
    return;
  }

  senderPlaybackDeviceMessage.textContent = `${devices.length} playback output${devices.length === 1 ? "" : "s"} discovered inside the container. Choose a playback device or the config default output.`;
}

function renderReceiverPlaybackDevices(devices) {
  const currentValue = receiverPlaybackDeviceSelect.value;
  const runtimeLaunch = latestStatus?.runtime?.launch;
  const runtimePlaybackDevice = runtimeLaunch?.role === "receiver" ? runtimeLaunch.receiver_playback_device : undefined;
  receiverPlaybackDeviceSelect.innerHTML = "";

  const defaultOption = document.createElement("option");
  defaultOption.value = RECEIVER_AUDIO_PLAYBACK_DEFAULT_DEVICE_VALUE;
  defaultOption.textContent = "Default output from config";
  receiverPlaybackDeviceSelect.appendChild(defaultOption);

  devices.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.path;
    option.textContent = `${device.label} (${device.path})`;
    receiverPlaybackDeviceSelect.appendChild(option);
  });
  ensureReceiverPlaybackDeviceOption(runtimePlaybackDevice);
  receiverPlaybackDeviceSelect.disabled = false;

  let selected = RECEIVER_AUDIO_PLAYBACK_DEFAULT_DEVICE_VALUE;
  if (
    launchFormDirty &&
    (currentValue === RECEIVER_AUDIO_PLAYBACK_DEFAULT_DEVICE_VALUE ||
      devices.some((device) => device.path === currentValue))
  ) {
    selected = currentValue;
  } else if (runtimePlaybackDevice) {
    selected = runtimePlaybackDevice;
  }
  receiverPlaybackDeviceSelect.value = selected;

  if (!devices.length) {
    receiverPlaybackDeviceMessage.textContent = "No playback devices are currently visible inside the container. Receiver can still use the config default output.";
    return;
  }

  receiverPlaybackDeviceMessage.textContent = `${devices.length} playback output${devices.length === 1 ? "" : "s"} discovered inside the container. Choose a playback device or the config default output.`;
}

function renderDisplayOutputs(outputs) {
  const currentValue = receiverVideoOutputSelect.value;
  const runtimeLaunch = latestStatus?.runtime?.launch;
  const runtimeVideoOutput = runtimeLaunch?.role === "receiver" ? runtimeLaunch.receiver_video_output : undefined;
  receiverVideoOutputSelect.innerHTML = "";

  const autoOption = document.createElement("option");
  autoOption.value = RECEIVER_VIDEO_OUTPUT_AUTO_VALUE;
  autoOption.textContent = "Automatic output";
  receiverVideoOutputSelect.appendChild(autoOption);

  outputs.forEach((output) => {
    const option = document.createElement("option");
    option.value = output.path;
    option.textContent = output.label;
    receiverVideoOutputSelect.appendChild(option);
  });
  ensureReceiverVideoOutputOption(runtimeVideoOutput);
  receiverVideoOutputSelect.disabled = false;

  let selected = RECEIVER_VIDEO_OUTPUT_AUTO_VALUE;
  if (
    launchFormDirty &&
    (
      currentValue === RECEIVER_VIDEO_OUTPUT_AUTO_VALUE ||
      outputs.some((output) => output.path === currentValue)
    )
  ) {
    selected = currentValue;
  } else if (runtimeVideoOutput) {
    selected = runtimeVideoOutput;
  }
  receiverVideoOutputSelect.value = selected;

  if (!outputs.length) {
    receiverVideoOutputMessage.textContent = "No DRM display outputs are currently visible inside the container. Receiver can still use automatic output selection.";
    return;
  }

  receiverVideoOutputMessage.textContent = `${outputs.length} display output${outputs.length === 1 ? "" : "s"} discovered inside the container. Choose a connector or leave it on automatic selection.`;
}

function renderPreview(preview, imageUrl, image, meta, empty) {
  if (!preview || !preview.available) {
    image.removeAttribute("src");
    image.classList.add("hidden");
    empty.classList.remove("hidden");
    meta.textContent = "No snapshot yet.";
    return;
  }

  image.src = `${imageUrl}?t=${Date.now()}`;
  image.classList.remove("hidden");
  empty.classList.add("hidden");
  meta.textContent = `Updated ${formatSeconds(preview.age_seconds)} ago`;
}

function describePacketActivity(activity) {
  if (!activity) {
    return "";
  }
  if (activity.receiving) {
    return "UDP packets incoming";
  }
  if (activity.last_packet_age_seconds != null) {
    return `UDP last seen ${formatSeconds(Math.round(activity.last_packet_age_seconds))} ago`;
  }
  if (activity.error) {
    return "UDP monitor unavailable";
  }
  return "No UDP packets yet";
}

function renderServerPreview(preview, packetActivity, imageUrl, image, meta, empty) {
  if (!preview || !preview.available) {
    image.removeAttribute("src");
    image.classList.add("hidden");
    empty.classList.remove("hidden");
    const packetText = describePacketActivity(packetActivity);
    meta.textContent = packetText || "No snapshot yet.";
    return;
  }

  image.src = `${imageUrl}?t=${Date.now()}`;
  image.classList.remove("hidden");
  empty.classList.add("hidden");

  const packetText = describePacketActivity(packetActivity);
  meta.textContent = packetText
    ? `Updated ${formatSeconds(preview.age_seconds)} ago • ${packetText}`
    : `Updated ${formatSeconds(preview.age_seconds)} ago`;
}

function renderSenderPreview(sender) {
  const country = sender?.country || latestStatus?.runtime?.launch?.country || null;
  const countryLabel = formatCountryLabel(country);
  senderPreviewTitle.textContent = `${countryLabel} Feed`;
  senderPreviewImage.alt = `${countryLabel} sender preview`;
  renderPreview(sender?.preview, "/api/sender/preview.jpg", senderPreviewImage, senderPreviewMeta, senderPreviewEmpty);
}

function renderReceiverPreview(receiver) {
  const country = receiver?.country || latestStatus?.runtime?.launch?.country || null;
  const countryLabel = formatCountryLabel(country);
  receiverPreviewTitle.textContent = `${countryLabel} Feed`;
  receiverPreviewImage.alt = `${countryLabel} receiver preview`;
  renderPreview(receiver?.preview, "/api/receiver/preview.jpg", receiverPreviewImage, receiverPreviewMeta, receiverPreviewEmpty);
}

function renderRoleActionButton(runtime) {
  const running = Boolean(runtime?.running);
  startRoleButton.textContent = running ? "Stop Selected Role" : "Start Selected Role";
  startRoleButton.classList.toggle("button-accent", !running);
  startRoleButton.classList.toggle("button-danger", running);
}

function renderStatus(status) {
  latestStatus = status;
  const runtime = status.runtime;
  const config = status.config;
  const storage = status.storage;
  const server = runtime.server;
  const sender = runtime.sender;
  const receiver = runtime.receiver;
  const recording = server?.recording;
  const launch = runtime.launch;
  const serverActive = runtime.running && runtime.role === "server";
  const senderActive = runtime.running && runtime.role === "sender";
  const receiverActive = runtime.running && runtime.role === "receiver";
  const serverContext = (runtime.running ? runtime.role : roleSelect.value) === "server";

  syncFormFromRuntime(runtime);

  runtimePill.textContent = runtime.running ? `${runtime.role || "Role"} Running` : "No Active Role";
  runtimePill.className = `status-pill ${runtime.running ? "status-running" : "status-stopped"}`;
  refreshLabel.textContent = `Last refreshed ${new Date().toLocaleTimeString()}`;
  renderRoleActionButton(runtime);

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
    if (recording?.active) {
      recordingState.textContent = "Recording";
      recordingMeta.textContent = `Started ${new Date(recording.started_at).toLocaleTimeString()}`;
    } else if (recording?.finalizing) {
      recordingState.textContent = "Finalizing";
      recordingMeta.textContent = "Archiving the last recording in the background.";
    } else {
      recordingState.textContent = "Ready";
      recordingMeta.textContent = `${storage.archive.file_count} archived files`;
    }
  }

  recordToggleButton.textContent = recording?.active ? "Stop Recording" : "Start Recording";
  recordToggleButton.disabled = !serverActive;

  recordingMetric.classList.toggle("hidden", !serverContext);
  serverPanel.classList.toggle("hidden", !serverActive);
  senderPanel.classList.toggle("hidden", !senderActive);
  receiverPanel.classList.toggle("hidden", !receiverActive);
  archivePanel.classList.toggle("hidden", !serverContext);
  renderServerPreview(
    server?.previews?.tn,
    server?.packet_activity?.tn,
    "/api/server/preview/tn.jpg",
    previewTnImage,
    previewTnMeta,
    previewTnEmpty,
  );
  renderServerPreview(
    server?.previews?.dk,
    server?.packet_activity?.dk,
    "/api/server/preview/dk.jpg",
    previewDkImage,
    previewDkMeta,
    previewDkEmpty,
  );
  renderSenderPreview(sender);
  renderReceiverPreview(receiver);

  renderArchive(storage);
  logOutput.textContent = runtime.log_tail.length ? runtime.log_tail.join("\n") : "No logs yet.";
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

async function refreshArchive() {
  setBusy([archiveRefreshButton], true);
  archiveActionMessage.textContent = "Refreshing archive…";

  try {
    const payload = await api("/api/archive/refresh", { method: "POST" });
    if (latestStatus) {
      latestStatus.storage = payload.storage;
      renderArchive(payload.storage);
    }
    archiveActionMessage.textContent = payload.message;
  } catch (error) {
    archiveActionMessage.textContent = error.message;
  } finally {
    setBusy([archiveRefreshButton], false);
  }
}

async function loadConfig(options = {}) {
  const reveal = options.reveal !== false;
  const showSuccess = Boolean(options.showSuccess);
  const sync = options.sync ?? getConfigPanelRole() !== "server";
  const path = sync ? "/api/config?sync=1" : "/api/config";
  try {
    const payload = await api(path, { method: "GET" });
    configEditor.value = payload.text;
    configEditor.dataset.configShown = "true";
    showConfigButton.textContent = getConfigPanelRole() === "server" ? "Show Config" : "Update config";
    if (reveal) {
      configEditor.classList.remove("hidden");
    }
    if (showSuccess) {
      if (payload.sync_error) {
        configMessage.textContent = `Showing local cached config from ${payload.path}. Central sync failed: ${payload.sync_error}`;
      } else if (payload.sync?.attempted) {
        configMessage.textContent = `${payload.sync.updated ? "Synced" : "Loaded"} central config from ${payload.sync.url} into ${payload.path}.`;
      } else {
        configMessage.textContent = `Loaded config from ${payload.path}.`;
      }
    }
  } catch (error) {
    configEditor.value = "";
    configEditor.dataset.configShown = "false";
    configEditor.classList.add("hidden");
    showConfigButton.textContent = "Show Config";
    configMessage.textContent = `Server config file is not available. ${error.message}`;
  }
}

async function loadVideoDevices() {
  try {
    const payload = await api("/api/devices/video", { method: "GET" });
    videoDevices = payload.devices || [];
    renderVideoDevices(videoDevices);
  } catch (error) {
    videoDevices = [];
    renderVideoDevices(videoDevices);
    videoDeviceMessage.textContent = `${error.message} Sender can still use the config video source or the test signal.`;
  }
}

async function loadAudioDevices() {
  try {
    const payload = await api("/api/devices/audio", { method: "GET" });
    audioDevices = payload.devices || [];
    renderAudioDevices(audioDevices);
  } catch (error) {
    audioDevices = [];
    renderAudioDevices(audioDevices);
    audioDeviceMessage.textContent = `${error.message} Sender can still use the config default input or the test signal.`;
  }
}

async function loadPlaybackDevices() {
  try {
    const payload = await api("/api/devices/audio/playback", { method: "GET" });
    playbackDevices = payload.devices || [];
    renderPlaybackDevices(playbackDevices);
    renderReceiverPlaybackDevices(playbackDevices);
  } catch (error) {
    playbackDevices = [];
    renderPlaybackDevices(playbackDevices);
    renderReceiverPlaybackDevices(playbackDevices);
    senderPlaybackDeviceMessage.textContent = `${error.message} Sender can still use the config default output.`;
    receiverPlaybackDeviceMessage.textContent = `${error.message} Receiver can still use the config default output.`;
  }
}

async function loadDisplayOutputs() {
  try {
    const payload = await api("/api/devices/display", { method: "GET" });
    displayOutputs = payload.devices || [];
    renderDisplayOutputs(displayOutputs);
  } catch (error) {
    displayOutputs = [];
    renderDisplayOutputs(displayOutputs);
    receiverVideoOutputMessage.textContent = `${error.message} Receiver can still use automatic output selection.`;
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
    if (!videoDeviceSelect.value || videoDeviceSelect.value === VIDEO_CONFIG_SOURCE_VALUE) {
      payload.video_source = "config";
      payload.video_device = null;
    } else if (videoDeviceSelect.value === VIDEO_TEST_SOURCE_VALUE) {
      payload.video_source = "test";
      payload.video_device = null;
    } else {
      payload.video_source = "device";
      payload.video_device = videoDeviceSelect.value || null;
    }
    payload.sender_audio_mode = senderAudioModeSelect.value;
    if (audioDeviceSelect.value === AUDIO_TEST_VALUE) {
      payload.audio_source = "test";
      payload.audio_device = null;
    } else if (audioDeviceSelect.value === AUDIO_DEFAULT_DEVICE_VALUE) {
      payload.audio_source = "device";
      payload.audio_device = null;
    } else if (audioDeviceSelect.value && audioDeviceSelect.value !== AUDIO_OFF_VALUE) {
      payload.audio_source = "device";
      payload.audio_device = audioDeviceSelect.value;
    } else {
      payload.audio_source = "off";
      payload.audio_device = null;
    }
    payload.audio_enabled = payload.audio_source !== "off";
    if (payload.audio_enabled && payload.sender_audio_mode === "aec") {
      payload.sender_playback_device =
        senderPlaybackDeviceSelect.value && senderPlaybackDeviceSelect.value !== AUDIO_PLAYBACK_DEFAULT_DEVICE_VALUE
          ? senderPlaybackDeviceSelect.value
          : null;
      payload.sender_audio_delay_ms = normalizeSyncDelayMs(senderAudioDelayInput.value);
    } else {
      payload.sender_playback_device = null;
      payload.sender_audio_delay_ms = 0;
    }
  }

  if (payload.role === "receiver") {
    payload.receiver_audio_transport = receiverAudioSelect.value;
    payload.receiver_playback_device =
      receiverPlaybackDeviceSelect.value && receiverPlaybackDeviceSelect.value !== RECEIVER_AUDIO_PLAYBACK_DEFAULT_DEVICE_VALUE
        ? receiverPlaybackDeviceSelect.value
        : null;
    payload.receiver_video_output =
      receiverVideoOutputSelect.value && receiverVideoOutputSelect.value !== RECEIVER_VIDEO_OUTPUT_AUTO_VALUE
        ? receiverVideoOutputSelect.value
        : null;
    payload.receiver_video_delay_ms = normalizeSyncDelayMs(receiverVideoDelayInput.value);
  }

  return payload;
}

async function startRole() {
  setBusy([startRoleButton], true);
  actionMessage.textContent = "Starting selected role…";

  try {
    const payload = await api("/api/runtime/start", {
      method: "POST",
      body: JSON.stringify(buildLaunchPayload()),
    });
    actionMessage.textContent = payload.message;
    launchFormDirty = false;
    await refreshStatus();
  } catch (error) {
    actionMessage.textContent = error.message;
  } finally {
    setBusy([startRoleButton], false);
  }
}

async function stopRole() {
  setBusy([startRoleButton], true);
  actionMessage.textContent = "Stopping selected role…";

  try {
    const payload = await api("/api/runtime/stop", { method: "POST" });
    actionMessage.textContent = payload.message;
    await refreshStatus();
  } catch (error) {
    actionMessage.textContent = error.message;
  } finally {
    setBusy([startRoleButton], false);
  }
}

async function updateRuntimeSyncDelay(payload, messageElement, successMessage) {
  try {
    const response = await api("/api/runtime/sync-delay", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    messageElement.textContent = successMessage || response.message;
    await refreshStatus();
  } catch (error) {
    messageElement.textContent = error.message;
  }
}

function scheduleRuntimeSyncDelay(payload, messageElement, successMessage) {
  window.clearTimeout(syncDelayTimer);
  syncDelayTimer = window.setTimeout(() => {
    updateRuntimeSyncDelay(payload, messageElement, successMessage);
  }, SYNC_DELAY_DEBOUNCE_MS);
}

function handleSenderAudioDelayInput() {
  const delayMs = normalizeSyncDelayMs(senderAudioDelayInput.value);
  senderAudioDelayInput.value = delayMs;
  updateSyncDelayLabels();

  if (latestStatus?.runtime?.running && latestStatus.runtime.role === "sender") {
    senderAudioDelayMessage.textContent = `Updating sender audio playback/probe delay to ${delayMs} ms…`;
    scheduleRuntimeSyncDelay(
      { sender_audio_delay_ms: delayMs },
      senderAudioDelayMessage,
      `Sender audio playback/probe delay set to ${delayMs} ms.`,
    );
    return;
  }

  markLaunchFormDirty();
  senderAudioDelayMessage.textContent = `Sender will start with ${delayMs} ms audio playback/probe delay.`;
}

function handleReceiverVideoDelayInput() {
  const delayMs = normalizeSyncDelayMs(receiverVideoDelayInput.value);
  receiverVideoDelayInput.value = delayMs;
  updateSyncDelayLabels();

  if (latestStatus?.runtime?.running && latestStatus.runtime.role === "receiver") {
    receiverVideoDelayMessage.textContent = `Updating receiver video delay to ${delayMs} ms…`;
    scheduleRuntimeSyncDelay(
      { receiver_video_delay_ms: delayMs },
      receiverVideoDelayMessage,
      `Receiver video delay set to ${delayMs} ms.`,
    );
    return;
  }

  markLaunchFormDirty();
  receiverVideoDelayMessage.textContent = `Receiver will start with ${delayMs} ms video delay.`;
}

async function toggleRoleAction() {
  if (latestStatus?.runtime?.running) {
    await stopRole();
    return;
  }
  await startRole();
}

async function toggleRecording() {
  if (!latestStatus?.runtime?.running || latestStatus.runtime.role !== "server") {
    return;
  }

  const action = latestStatus.runtime.server?.recording?.active ? "stop" : "start";
  setBusy([recordToggleButton], true);
  recordMessage.textContent = action === "start" ? "Starting recording…" : "Stopping recording and finalizing…";

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

function selectedArchiveBaseName() {
  if (!selectedArchiveFile) {
    return "";
  }
  return selectedArchiveFile.base_name || selectedArchiveFile.name;
}

async function renameSelectedArchive() {
  if (!selectedArchiveFile) {
    return;
  }

  const nextBaseName = window.prompt("Rename selected file", selectedArchiveBaseName());
  if (nextBaseName == null) {
    return;
  }

  setBusy([archiveRenameButton, archiveDeleteButton], true);
  archiveActionMessage.textContent = "Renaming selected file…";

  try {
    const payload = await api(`/api/archive/files/${encodeURIComponent(selectedArchiveFile.name)}/rename`, {
      method: "POST",
      body: JSON.stringify({
        base_name: nextBaseName,
      }),
    });
    selectedArchiveName = payload.file?.name || selectedArchiveName;
    archiveActionMessage.textContent = payload.message;
    await refreshStatus();
  } catch (error) {
    archiveActionMessage.textContent = error.message;
  } finally {
    setBusy([archiveRenameButton, archiveDeleteButton], false);
  }
}

async function deleteSelectedArchive() {
  if (!selectedArchiveFile) {
    return;
  }
  if (!window.confirm(`Delete ${selectedArchiveFile.name}?`)) {
    return;
  }

  setBusy([archiveRenameButton, archiveDeleteButton], true);
  archiveActionMessage.textContent = "Deleting selected file…";

  try {
    const payload = await api(`/api/archive/files/${encodeURIComponent(selectedArchiveFile.name)}`, {
      method: "DELETE",
    });
    selectedArchiveName = null;
    archiveActionMessage.textContent = payload.message;
    await refreshStatus();
  } catch (error) {
    archiveActionMessage.textContent = error.message;
  } finally {
    setBusy([archiveRenameButton, archiveDeleteButton], false);
  }
}

async function saveConfig(restart) {
  if (getConfigPanelRole() !== "server") {
    await loadConfig({ reveal: true, showSuccess: true, sync: true });
    return;
  }

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
  markLaunchFormDirty();
  applyRoleFormState();
  if (roleSelect.value === "sender") {
    await Promise.all([loadVideoDevices(), loadAudioDevices(), loadPlaybackDevices()]);
    return;
  }
  if (roleSelect.value === "receiver") {
    await Promise.all([loadPlaybackDevices(), loadDisplayOutputs()]);
    return;
  }
  if (roleSelect.value === "server") {
    await loadConfig({ reveal: true });
  }
});
countrySelect.addEventListener("change", markLaunchFormDirty);
videoDeviceSelect.addEventListener("change", markLaunchFormDirty);
audioDeviceSelect.addEventListener("change", () => {
  markLaunchFormDirty();
  applyRoleFormState();
});
senderAudioModeSelect.addEventListener("change", () => {
  markLaunchFormDirty();
  applyRoleFormState();
});
senderPlaybackDeviceSelect.addEventListener("change", markLaunchFormDirty);
senderAudioDelayInput.addEventListener("input", handleSenderAudioDelayInput);
receiverAudioSelect.addEventListener("change", markLaunchFormDirty);
receiverPlaybackDeviceSelect.addEventListener("change", markLaunchFormDirty);
receiverVideoOutputSelect.addEventListener("change", markLaunchFormDirty);
receiverVideoDelayInput.addEventListener("input", handleReceiverVideoDelayInput);
startRoleButton.addEventListener("click", toggleRoleAction);
recordToggleButton.addEventListener("click", toggleRecording);
saveConfigButton.addEventListener("click", () => saveConfig(false));
applyConfigButton.addEventListener("click", () => saveConfig(true));
showConfigButton.addEventListener("click", () => loadConfig({ reveal: true, showSuccess: true, sync: true }));
archiveRenameButton.addEventListener("click", renameSelectedArchive);
archiveDeleteButton.addEventListener("click", deleteSelectedArchive);
archiveRefreshButton.addEventListener("click", refreshArchive);

window.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveConfig(false);
  }
});

async function boot() {
  applyRoleFormState();
  await refreshStatus();
  if (getConfigPanelRole() === "server") {
    await loadConfig({ reveal: true });
  }
  await Promise.all([loadVideoDevices(), loadAudioDevices(), loadPlaybackDevices(), loadDisplayOutputs()]);
  refreshTimer = window.setInterval(refreshStatus, 3000);
}

boot();
