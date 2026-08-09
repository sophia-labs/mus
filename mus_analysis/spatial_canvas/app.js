const state = {
  scene: null,
  selectedId: null,
  soloIds: new Set(),
  context: null,
  master: null,
  convolver: null,
  reverbGain: null,
  dryGain: null,
  active: [],
  buffers: new Map(),
  playing: false,
  playhead: 0,
  startedAt: 0,
  animation: null,
  drag: null,
  capabilities: { editable: false, reanalyze: true, ingestModes: [] },
  importing: false,
  trajectoryId: null,
};

const $ = (selector) => document.querySelector(selector);
const stage = $("#stage");
const ctx2d = stage.getContext("2d");
const propertyInputs = [...document.querySelectorAll("[data-property]")];

await loadScene();
wireUi();
resizeStage();
renderAll();
window.addEventListener("resize", resizeStage);

async function loadScene() {
  const [sceneResponse, capabilityResponse] = await Promise.all([
    fetch("/api/scene", { cache: "no-store" }),
    fetch("/api/capabilities", { cache: "no-store" }).catch(() => null),
  ]);
  if (!sceneResponse.ok) throw new Error(`Could not load scene: ${sceneResponse.status}`);
  state.scene = await sceneResponse.json();
  if (capabilityResponse?.ok) state.capabilities = await capabilityResponse.json();
  $("#scene-title").textContent = state.scene.title;
  $("#timeline").max = state.scene.durationSeconds;
  $("#room-wet").value = state.scene.room?.wet ?? 0.16;
  $("#room-wet-value").value = `${Math.round((state.scene.room?.wet ?? .16) * 100)}%`;
  const yaw = listenerYawDegrees();
  $("#listener-yaw").value = yaw; $("#listener-yaw-value").value = `${Math.round(yaw)}°`;
  $("#import-toolbar").hidden = !state.capabilities.editable;
  $("#save").hidden = !state.capabilities.editable;
  $("#derive-object").hidden = !state.capabilities.editable;
  state.selectedId = state.scene.objects[0]?.objectId ?? null;
  renderImportMode();
}

function wireUi() {
  $("#play").addEventListener("click", () => state.playing ? pause() : play());
  $("#stop").addEventListener("click", stop);
  $("#timeline").addEventListener("input", (event) => seek(Number(event.target.value)));
  $("#master-gain").addEventListener("input", (event) => {
    const value = Number(event.target.value);
    $("#master-gain-value").value = `${value.toFixed(1)} dB`;
    if (state.master) state.master.gain.setTargetAtTime(dbToGain(value), state.context.currentTime, .02);
  });
  $("#room-wet").addEventListener("input", (event) => {
    const value = Number(event.target.value);
    state.scene.room.wet = value;
    $("#room-wet-value").value = `${Math.round(value * 100)}%`;
    if (state.reverbGain) state.reverbGain.gain.setTargetAtTime(value, state.context.currentTime, .02);
  });
  $("#listener-yaw").addEventListener("input", (event) => {
    setListenerYaw(Number(event.target.value));
    $("#listener-yaw-value").value = `${Math.round(Number(event.target.value))}°`;
    applyListenerToAudio(); renderStage(); restartIfPlaying();
  });
  $("#save").addEventListener("click", saveScene);
  $("#add-sound").addEventListener("click", () => $("#audio-file").click());
  $("#audio-file").addEventListener("change", async (event) => {
    await ingestFiles([...event.target.files]);
    event.target.value = "";
  });
  $("#import-mode").addEventListener("change", renderImportMode);
  $("#trajectory-select").addEventListener("change", (event) => { state.trajectoryId = event.target.value; renderInspector(); });
  $("#clear-solo").addEventListener("click", () => { state.soloIds.clear(); renderAll(); restartIfPlaying(); });
  $("#audition-object").addEventListener("click", () => auditionSelected());
  $("#reset-controls").addEventListener("click", resetSelectedControls);
  $("#reanalyze").addEventListener("click", reanalyzeSelected);
  $("#derive-object").addEventListener("click", deriveSelected);
  $("#clear-analysis-preview").addEventListener("click", clearAnalysisPreview);
  for (const input of propertyInputs) input.addEventListener("input", () => updateSelectedFromInput(input));

  stage.addEventListener("pointerdown", beginDrag);
  stage.addEventListener("pointermove", dragObject);
  stage.addEventListener("pointerup", endDrag);
  stage.addEventListener("pointercancel", endDrag);
}

async function ensureAudio() {
  if (state.context) {
    await state.context.resume();
    return;
  }
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  state.context = new AudioContextClass({ latencyHint: "interactive" });
  state.master = state.context.createGain();
  state.dryGain = state.context.createGain();
  state.convolver = state.context.createConvolver();
  state.reverbGain = state.context.createGain();
  state.master.gain.value = dbToGain(Number($("#master-gain").value));
  state.reverbGain.gain.value = state.scene.room?.wet ?? .16;
  state.convolver.buffer = syntheticImpulse(state.context, state.scene.room?.decaySeconds ?? 1.6, state.scene.room?.damping ?? .45);
  state.dryGain.connect(state.master);
  state.convolver.connect(state.reverbGain).connect(state.master);
  state.master.connect(state.context.destination);
  applyListenerToAudio();
}

async function play() {
  await ensureAudio();
  stopNodes();
  state.playing = true;
  state.startedAt = state.context.currentTime - state.playhead;
  $("#play").textContent = "Pause";
  const enabled = activeObjects();
  await Promise.all(enabled.map(scheduleObject));
  tick();
}

function pause() {
  if (!state.playing) return;
  state.playhead = currentPlayhead();
  state.playing = false;
  stopNodes();
  $("#play").textContent = "Resume";
  cancelAnimationFrame(state.animation);
  renderTransport();
}

function stop() {
  state.playing = false;
  state.playhead = 0;
  stopNodes();
  $("#play").textContent = "Start audio";
  cancelAnimationFrame(state.animation);
  renderTransport();
}

function seek(seconds) {
  state.playhead = clamp(seconds, 0, state.scene.durationSeconds);
  if (state.playing) play();
  else renderTransport();
}

function currentPlayhead() {
  if (!state.playing || !state.context) return state.playhead;
  return clamp(state.context.currentTime - state.startedAt, 0, state.scene.durationSeconds);
}

async function scheduleObject(obj) {
  const sceneTime = state.playhead;
  const objectEnd = obj.startSeconds + (obj.durationSeconds ?? Infinity);
  if (!obj.loop && objectEnd <= sceneTime) return;
  const buffer = await loadBuffer(obj);
  if (!state.playing) return;
  const source = state.context.createBufferSource();
  source.buffer = buffer;
  source.loop = Boolean(obj.loop);
  source.detune.value = (obj.controls?.pitchSemitones ?? 0) * 100;

  const shelf = state.context.createBiquadFilter();
  shelf.type = "highshelf";
  shelf.frequency.value = obj.controls?.brightnessHz ?? 2500;
  shelf.gain.value = obj.controls?.brightnessDb ?? 0;

  const rough = createModulationGain(obj.controls?.roughnessDepth ?? 0, obj.controls?.roughnessRateHz ?? 70);
  const fluct = createModulationGain(obj.controls?.fluctuationDepth ?? 0, obj.controls?.fluctuationRateHz ?? 4);
  const objectGain = state.context.createGain();
  objectGain.gain.value = obj.muted ? 0 : dbToGain(obj.gainDb ?? 0);

  source.connect(shelf).connect(rough.gain).connect(fluct.gain).connect(objectGain);
  rough.oscillator.start(); fluct.oscillator.start();

  const panners = connectPanners(objectGain, obj);
  const roomSend = state.context.createGain();
  roomSend.gain.value = obj.reverbSend ?? 0;
  objectGain.connect(roomSend).connect(state.convolver);

  const when = state.context.currentTime + Math.max(0, obj.startSeconds - sceneTime);
  const offset = Math.max(0, sceneTime - obj.startSeconds);
  const attack = obj.controls?.attackSeconds;
  if (attack != null && attack > 0) {
    objectGain.gain.cancelScheduledValues(when);
    objectGain.gain.setValueAtTime(0, when);
    objectGain.gain.linearRampToValueAtTime(dbToGain(obj.gainDb ?? 0), when + attack);
  }
  source.start(when, obj.loop ? offset % buffer.duration : offset);
  const record = { source, rough, fluct, panners, roomSend, objectGain };
  state.active.push(record);
  source.onended = () => disposeRecord(record);
}

function connectPanners(input, obj) {
  const spread = Math.max(obj.spread ?? 0, ["diffuse", "ambient"].includes(obj.kind) ? .78 : 0);
  const count = spread > .72 ? 4 : spread > .05 ? 3 : 1;
  const result = [];
  for (let i = 0; i < count; i++) {
    const panner = state.context.createPanner();
    panner.panningModel = "HRTF";
    panner.distanceModel = "inverse";
    panner.refDistance = 1;
    panner.maxDistance = 100;
    panner.rolloffFactor = .72;
    panner.coneInnerAngle = 360;
    panner.coneOuterAngle = 360;
    const angle = count === 1 ? 0 : ((i / count) * Math.PI * 2);
    const radius = spread * Math.max(1, Math.hypot(obj.position.x, obj.position.z) * .25);
    const x = obj.position.x + Math.cos(angle) * radius;
    const y = obj.position.y + (i % 2 ? spread : -spread) * .5;
    const z = obj.position.z + Math.sin(angle) * radius;
    panner.positionX.value = x; panner.positionY.value = y; panner.positionZ.value = z;
    const branch = state.context.createGain();
    branch.gain.value = 1 / Math.sqrt(count);
    input.connect(branch).connect(panner).connect(state.dryGain);
    result.push({ panner, branch });
  }
  return result;
}

function createModulationGain(depth, rate) {
  const gain = state.context.createGain();
  gain.gain.value = 1;
  const oscillator = state.context.createOscillator();
  oscillator.frequency.value = Math.max(.01, rate);
  const amount = state.context.createGain();
  amount.gain.value = clamp(depth, 0, 1);
  oscillator.connect(amount).connect(gain.gain);
  return { gain, oscillator, amount };
}

async function loadBuffer(obj) {
  if (state.buffers.has(obj.objectId)) return state.buffers.get(obj.objectId);
  const response = await fetch(`/media/${encodeURIComponent(obj.objectId)}`);
  if (!response.ok) throw new Error(`Could not fetch ${obj.label}: ${response.status}`);
  const buffer = await state.context.decodeAudioData(await response.arrayBuffer());
  state.buffers.set(obj.objectId, buffer);
  return buffer;
}

function stopNodes() {
  for (const record of [...state.active]) {
    try { record.source.stop(); } catch {}
    disposeRecord(record);
  }
  state.active = [];
}

function disposeRecord(record) {
  try { record.rough.oscillator.stop(); } catch {}
  try { record.fluct.oscillator.stop(); } catch {}
  for (const node of [record.source, record.rough.gain, record.rough.amount, record.fluct.gain, record.fluct.amount, record.roomSend, record.objectGain]) {
    try { node.disconnect(); } catch {}
  }
  for (const branch of record.panners ?? []) {
    try { branch.panner.disconnect(); branch.branch.disconnect(); } catch {}
  }
  state.active = state.active.filter((item) => item !== record);
}

function tick() {
  if (!state.playing) return;
  const now = currentPlayhead();
  if (now >= state.scene.durationSeconds) return stop();
  renderTransport();
  state.animation = requestAnimationFrame(tick);
}

function renderAll() {
  renderObjectList();
  renderInspector();
  renderStage();
  renderTransport();
}

function renderObjectList() {
  const list = $("#object-list");
  list.replaceChildren();
  for (const obj of state.scene.objects) {
    const row = document.createElement("div");
    row.className = `object-row${obj.objectId === state.selectedId ? " selected" : ""}`;
    row.innerHTML = `<div class="label"></div><div class="object-actions"></div><div class="meta"></div>`;
    row.querySelector(".label").textContent = obj.label;
    row.querySelector(".meta").textContent = `${obj.kind} · ${formatTime(obj.startSeconds)} · spread ${(obj.spread ?? 0).toFixed(2)}`;
    row.addEventListener("click", () => selectObject(obj.objectId));
    const actions = row.querySelector(".object-actions");
    actions.append(actionButton("M", obj.muted, () => { obj.muted = !obj.muted; renderAll(); restartIfPlaying(); }, "Mute"));
    actions.append(actionButton("S", state.soloIds.has(obj.objectId), () => toggleSolo(obj.objectId), "Solo"));
    if (state.capabilities.editable) {
      const remove = actionButton("×", false, () => deleteObject(obj.objectId), "Remove object");
      remove.classList.add("remove"); actions.append(remove);
    }
    list.append(row);
  }
}

function renderImportMode() {
  const mode = $("#import-mode")?.value ?? "whole";
  const componentOption = document.querySelector(".component-option");
  if (componentOption) componentOption.hidden = !["nmf", "hybrid", "bands"].includes(mode);
}

async function ingestFiles(files) {
  if (!state.capabilities.editable || state.importing || !files.length) return;
  state.importing = true;
  const button = $("#add-sound");
  const progress = $("#import-progress");
  const status = $("#import-status");
  button.disabled = true; button.textContent = "Importing…";
  progress.hidden = false;
  try {
    for (let index = 0; index < files.length; index++) {
      const file = files[index];
      status.textContent = `Analyzing ${file.name} (${index + 1}/${files.length})…`;
      const body = await uploadAudio(file, (loaded, total) => {
        progress.max = Math.max(1, total); progress.value = loaded;
      });
      state.scene = body.scene;
      $("#scene-title").textContent = state.scene.title;
      $("#timeline").max = state.scene.durationSeconds;
      state.selectedId = body.addedObjectIds?.[0] ?? state.selectedId;
      status.textContent = `${file.name}: added ${body.addedObjectIds?.length ?? 0} spatial object(s).`;
      renderAll();
    }
    restartIfPlaying();
    notice(`Added ${files.length} sound${files.length === 1 ? "" : "s"}; every object has an initial psychoacoustic report.`);
  } catch (error) {
    status.textContent = error.message;
    notice(error.message);
  } finally {
    state.importing = false;
    button.disabled = false; button.textContent = "Add sound";
    progress.hidden = true; progress.value = 0;
  }
}

function uploadAudio(file, onProgress) {
  const mode = $("#import-mode").value;
  const components = $("#import-components").value;
  const startSeconds = $("#import-at-playhead").checked ? currentPlayhead() : 0;
  const query = new URLSearchParams({ filename: file.name, mode, components, startSeconds: String(startSeconds) });
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `/api/objects?${query}`);
    request.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    request.upload.addEventListener("progress", (event) => onProgress(event.loaded, event.total || file.size));
    request.addEventListener("load", () => {
      let body = {};
      try { body = JSON.parse(request.responseText); } catch {}
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(body.message ?? `Import failed: HTTP ${request.status}`));
      } else resolve(body);
    });
    request.addEventListener("error", () => reject(new Error(`Could not upload ${file.name}`)));
    request.send(file);
  });
}

async function deleteObject(objectId) {
  const obj = state.scene.objects.find((item) => item.objectId === objectId);
  if (!obj || !state.capabilities.editable) return;
  try {
    const response = await fetch(`/api/objects/${encodeURIComponent(objectId)}`, { method: "DELETE" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.message ?? `Remove failed: ${response.status}`);
    state.scene = body.scene;
    state.soloIds.delete(objectId); state.buffers.delete(objectId);
    if (state.selectedId === objectId) state.selectedId = state.scene.objects[0]?.objectId ?? null;
    renderAll(); restartIfPlaying(); notice(`Removed ${obj.label}.`);
  } catch (error) { notice(error.message); }
}

function actionButton(text, pressed, handler, label) {
  const button = document.createElement("button");
  button.textContent = text; button.title = label; button.setAttribute("aria-pressed", String(pressed));
  button.addEventListener("click", (event) => { event.stopPropagation(); handler(); });
  return button;
}

function toggleSolo(id) {
  state.soloIds.has(id) ? state.soloIds.delete(id) : state.soloIds.add(id);
  renderAll(); restartIfPlaying();
}

function activeObjects() {
  const soloed = state.soloIds.size ? state.scene.objects.filter((obj) => state.soloIds.has(obj.objectId)) : state.scene.objects;
  return soloed.filter((obj) => !obj.muted);
}

function selectObject(id) {
  state.selectedId = id;
  renderAll();
}

function selectedObject() { return state.scene.objects.find((obj) => obj.objectId === state.selectedId); }

function renderInspector() {
  const obj = selectedObject();
  $("#empty-inspector").hidden = Boolean(obj);
  $("#inspector-content").hidden = !obj;
  if (!obj) return;
  $("#object-label").textContent = obj.label;
  $("#object-kind").textContent = `${obj.kind} · ${obj.placementProvenance}`;
  obj.controls ??= defaults().controls;
  for (const input of propertyInputs) {
    const value = getPath(obj, input.dataset.property);
    input.value = value == null ? 0 : value;
    updateOutput(input, value);
  }
  const preview = obj.metadata?.interventionAnalysis;
  const activeAnalysis = preview?.report ?? obj.analysis;
  const calibration = activeAnalysis?.calibration;
  $("#calibration-state").textContent = `${preview ? "intervention · " : ""}${calibration?.kind === "relative" || !calibration ? "relative signal" : "pressure calibrated"}`;
  $("#clear-analysis-preview").hidden = !preview;
  renderMetrics(activeAnalysis?.metrics ?? [], obj.analysis?.metrics ?? []);
  renderTrajectory(activeAnalysis?.trajectories ?? [], obj.analysis?.trajectories ?? []);
  $("#provenance").textContent = JSON.stringify({
    audio: obj.audio,
    sourceRegion: obj.sourceRegion,
    placementProvenance: obj.placementProvenance,
    metadata: obj.metadata,
    calibration: obj.analysis?.calibration,
    diagnostics: obj.analysis?.diagnostics,
  }, null, 2);
}

function renderMetrics(metrics, baselineMetrics = []) {
  const list = $("#metric-list"); list.replaceChildren();
  const priority = [
    "programme.integrated-loudness", "psychoacoustic.loudness-zwicker", "spectrum.centroid-hz",
    "psychoacoustic.sharpness-din", "auditory.relative-sharpness", "psychoacoustic.roughness-daniel-weber",
    "auditory.roughness-proxy", "auditory.fluctuation-proxy", "auditory.pitch-salience-proxy",
    "auditory.harmonic-energy-ratio", "temporal.attack-10-90-seconds", "spectrum.flatness"
  ];
  const order = new Map(priority.map((id, index) => [id, index]));
  const baseline = new Map(baselineMetrics.map((row) => [metricId(row), row.value]));
  const rows = [...metrics].sort((a, b) => (order.get(metricId(a)) ?? 999) - (order.get(metricId(b)) ?? 999));
  for (const metric of rows.slice(0, 18)) {
    const row = document.createElement("div");
    row.className = `metric ${metric.status ?? ""}`;
    const name = document.createElement("span"); name.className = "name"; name.textContent = metric.label ?? metricId(metric);
    const value = document.createElement("span"); value.className = "value";
    value.textContent = metric.value == null ? metric.status : `${formatNumber(metric.value)}${metric.unit ? ` ${metric.unit}` : ""}`;
    const before = baseline.get(metricId(metric));
    if (metric.value != null && before != null && Number.isFinite(Number(before))) {
      const delta = Number(metric.value) - Number(before);
      if (Math.abs(delta) > 1e-9) {
        const span = document.createElement("span"); span.className = "delta"; span.textContent = `${delta > 0 ? "+" : ""}${formatNumber(delta)}`; value.append(span);
      }
    }
    row.title = [...(metric.caveats ?? []), metric.operator ?? ""].filter(Boolean).join("\n");
    row.append(name, value); list.append(row);
  }
}

function renderTrajectory(trajectories, baselineTrajectories = []) {
  const panel = $("#trajectory-panel");
  const select = $("#trajectory-select");
  const canvas = $("#trajectory-chart");
  const range = $("#trajectory-range");
  panel.hidden = !trajectories.length;
  if (!trajectories.length) return;
  const available = new Map(trajectories.map((row) => [trajectoryId(row), row]));
  if (!state.trajectoryId || !available.has(state.trajectoryId)) state.trajectoryId = trajectoryId(trajectories[0]);
  const previous = select.value;
  select.replaceChildren();
  for (const row of trajectories) {
    const option = document.createElement("option"); option.value = trajectoryId(row); option.textContent = row.label ?? trajectoryId(row); select.append(option);
  }
  select.value = state.trajectoryId;
  if (!select.value) { state.trajectoryId = trajectoryId(trajectories[0]); select.value = state.trajectoryId; }
  const active = available.get(state.trajectoryId);
  const baseline = baselineTrajectories.find((row) => trajectoryId(row) === state.trajectoryId);
  const activeValues = trajectoryValues(active);
  const baselineValues = trajectoryValues(baseline);
  const finite = [...activeValues, ...baselineValues].filter(Number.isFinite);
  if (!finite.length) { canvas.hidden = true; range.value = "No finite samples"; return; }
  canvas.hidden = false;
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(220, canvas.clientWidth || 300); const height = Math.max(100, canvas.clientHeight || 128);
  canvas.width = Math.floor(width * ratio); canvas.height = Math.floor(height * ratio);
  const context = canvas.getContext("2d"); context.setTransform(ratio, 0, 0, ratio, 0, 0); context.clearRect(0, 0, width, height);
  const minimum = Math.min(...finite); const maximum = Math.max(...finite); const span = Math.max(maximum - minimum, Math.abs(maximum) * .02, 1e-9);
  const pad = { left: 8, right: 8, top: 8, bottom: 14 };
  context.strokeStyle = "rgba(143,160,181,.18)"; context.lineWidth = 1;
  for (let i = 0; i <= 3; i++) { const y = pad.top + (height - pad.top - pad.bottom) * i / 3; context.beginPath(); context.moveTo(pad.left, y); context.lineTo(width - pad.right, y); context.stroke(); }
  if (baseline && baseline !== active) drawTrajectoryLine(context, baselineValues, minimum, span, width, height, pad, "rgba(149,184,255,.48)", [4, 4]);
  drawTrajectoryLine(context, activeValues, minimum, span, width, height, pad, "#7ee0c3", []);
  const unit = active.unit ? ` ${active.unit}` : "";
  range.value = `${formatNumber(minimum)}–${formatNumber(maximum)}${unit} · ${activeValues.filter(Number.isFinite).length} samples`;
}

function drawTrajectoryLine(context, values, minimum, span, width, height, pad, color, dash) {
  if (!values.length) return;
  context.strokeStyle = color; context.lineWidth = 1.5; context.setLineDash(dash); context.beginPath();
  let drawing = false;
  values.forEach((value, index) => {
    if (!Number.isFinite(value)) { drawing = false; return; }
    const x = pad.left + (width - pad.left - pad.right) * index / Math.max(1, values.length - 1);
    const y = pad.top + (height - pad.top - pad.bottom) * (1 - (value - minimum) / span);
    if (!drawing) { context.moveTo(x, y); drawing = true; } else context.lineTo(x, y);
  });
  context.stroke(); context.setLineDash([]);
}

function trajectoryId(row) { return row?.trajectoryId ?? row?.trajectory_id ?? "trajectory"; }
function trajectoryValues(row) { return (row?.values ?? []).map((value) => value == null ? NaN : Number(value)); }

function updateSelectedFromInput(input) {
  const obj = selectedObject(); if (!obj) return;
  const value = Number(input.value);
  setPath(obj, input.dataset.property, value);
  if (obj.metadata?.interventionAnalysis) delete obj.metadata.interventionAnalysis;
  updateOutput(input, value);
  renderStage(); renderObjectList();
  restartIfPlaying();
}

function updateOutput(input, value) {
  const output = input.parentElement.querySelector("output");
  const key = input.dataset.property;
  const number = value == null ? 0 : Number(value);
  if (key.includes("Db") || key.endsWith("gainDb")) output.value = `${number.toFixed(1)} dB`;
  else if (key.endsWith("Hz")) output.value = number < 100 ? `${number.toFixed(2)} Hz` : `${number.toFixed(0)} Hz`;
  else if (key.includes("Seconds")) output.value = `${number.toFixed(2)} s`;
  else if (key.includes("Semitones")) output.value = `${number.toFixed(1)} st`;
  else output.value = number.toFixed(2);
}

function resetSelectedControls() {
  const obj = selectedObject(); if (!obj) return;
  obj.controls = defaults().controls;
  if (obj.metadata?.interventionAnalysis) delete obj.metadata.interventionAnalysis;
  renderInspector(); restartIfPlaying();
}

async function reanalyzeSelected() {
  const obj = selectedObject(); if (!obj) return;
  $("#reanalyze").disabled = true; $("#reanalyze").textContent = "Analyzing…";
  try {
    const response = await fetch(`/api/analyze/${encodeURIComponent(obj.objectId)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ controls: obj.controls, includeStandardized: true })
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.message ?? `Analysis failed: ${response.status}`);
    obj.metadata ??= {}; obj.metadata.interventionAnalysis = body;
    renderInspector(); notice("Intervention reanalyzed; metric deltas are shown against the original.");
  } catch (error) { notice(error.message); }
  finally { $("#reanalyze").disabled = false; $("#reanalyze").textContent = "Analyze current intervention"; }
}

async function deriveSelected() {
  const obj = selectedObject(); if (!obj || !state.capabilities.editable) return;
  const button = $("#derive-object"); button.disabled = true; button.textContent = "Rendering…";
  try {
    const response = await fetch(`/api/objects/${encodeURIComponent(obj.objectId)}/derive`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ controls: obj.controls, includeStandardized: true })
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.message ?? `Variation failed: ${response.status}`);
    state.scene = body.scene;
    state.selectedId = body.addedObjectIds?.[0] ?? state.selectedId;
    $("#timeline").max = state.scene.durationSeconds;
    renderAll(); restartIfPlaying();
    notice("Materialized the intervention as a new analyzed sound object with explicit lineage.");
  } catch (error) { notice(error.message); }
  finally { button.disabled = false; button.textContent = "Commit variation"; }
}

function clearAnalysisPreview() {
  const obj = selectedObject(); if (!obj?.metadata?.interventionAnalysis) return;
  delete obj.metadata.interventionAnalysis; renderInspector();
}

async function auditionSelected() {
  const obj = selectedObject(); if (!obj) return;
  state.soloIds = new Set([obj.objectId]);
  state.playhead = obj.startSeconds;
  renderAll(); await play();
}

async function saveScene() {
  try {
    const response = await fetch("/api/scene", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state.scene)
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.message ?? `Save failed: ${response.status}`);
    notice(`Saved ${body.saved}`);
  } catch (error) { notice(error.message); }
}

function resizeStage() {
  const rect = stage.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  stage.width = Math.max(1, Math.floor(rect.width * ratio));
  stage.height = Math.max(1, Math.floor(rect.height * ratio));
  ctx2d.setTransform(ratio, 0, 0, ratio, 0, 0);
  renderStage();
}

function renderStage() {
  if (!state.scene) return;
  const width = stage.clientWidth, height = stage.clientHeight;
  ctx2d.clearRect(0, 0, width, height);
  const center = { x: width / 2, y: height / 2 };
  const scale = Math.max(8, Math.min(width, height) / 44);
  ctx2d.save(); ctx2d.translate(center.x, center.y);
  drawGrid(scale, width, height);
  drawListener();
  for (const obj of state.scene.objects) drawObject(obj, scale);
  ctx2d.restore();
}

function drawGrid(scale, width, height) {
  ctx2d.strokeStyle = "rgba(145,170,194,.13)"; ctx2d.lineWidth = 1;
  for (const radius of [2, 5, 10, 15, 20]) {
    ctx2d.beginPath(); ctx2d.arc(0, 0, radius * scale, 0, Math.PI * 2); ctx2d.stroke();
    ctx2d.fillStyle = "rgba(170,190,208,.42)"; ctx2d.font = "10px system-ui"; ctx2d.fillText(`${radius} m`, radius * scale + 3, -3);
  }
  ctx2d.beginPath(); ctx2d.moveTo(-width, 0); ctx2d.lineTo(width, 0); ctx2d.moveTo(0, -height); ctx2d.lineTo(0, height); ctx2d.stroke();
  ctx2d.fillStyle = "rgba(126,224,195,.72)"; ctx2d.fillText("FRONT", 7, -height / 2 + 22);
}

function drawListener() {
  const forward = state.scene.listener?.forward ?? { x: 0, y: 0, z: -1 };
  const length = Math.hypot(forward.x, forward.z) || 1;
  const dx = forward.x / length * 24; const dy = forward.z / length * 24;
  ctx2d.fillStyle = "#edf3f8";
  ctx2d.beginPath(); ctx2d.arc(0, 0, 6, 0, Math.PI * 2); ctx2d.fill();
  ctx2d.strokeStyle = "#7ee0c3"; ctx2d.lineWidth = 2; ctx2d.beginPath(); ctx2d.moveTo(dx * .25, dy * .25); ctx2d.lineTo(dx, dy); ctx2d.stroke();
}

function drawObject(obj, scale) {
  const x = obj.position.x * scale, y = obj.position.z * scale;
  const selected = obj.objectId === state.selectedId;
  const field = ["extended", "diffuse", "ambient"].includes(obj.kind);
  const radius = 7 + (obj.spread ?? 0) * 19;
  ctx2d.globalAlpha = obj.muted ? .3 : 1;
  if (field) {
    ctx2d.strokeStyle = selected ? "#fff" : colorFor(obj.objectId); ctx2d.lineWidth = selected ? 3 : 1.5;
    ctx2d.beginPath(); ctx2d.arc(x, y, radius, 0, Math.PI * 2); ctx2d.stroke();
  } else {
    ctx2d.fillStyle = selected ? "#fff" : colorFor(obj.objectId);
    ctx2d.beginPath(); ctx2d.arc(x, y, selected ? 8 : 6, 0, Math.PI * 2); ctx2d.fill();
  }
  ctx2d.fillStyle = selected ? "#fff" : "rgba(225,235,244,.78)"; ctx2d.font = selected ? "600 11px system-ui" : "10px system-ui";
  ctx2d.fillText(`${obj.label} · ${obj.position.y.toFixed(1)}m`, x + radius + 4, y + 3);
  ctx2d.globalAlpha = 1;
}

function beginDrag(event) {
  const point = stagePoint(event); const scale = stageScale();
  let nearest = null, distance = Infinity;
  for (const obj of state.scene.objects) {
    const d = Math.hypot(point.x - obj.position.x * scale, point.y - obj.position.z * scale);
    if (d < distance && d < 28) { nearest = obj; distance = d; }
  }
  if (!nearest) return;
  state.drag = { id: nearest.objectId };
  stage.setPointerCapture(event.pointerId);
  selectObject(nearest.objectId);
}

function dragObject(event) {
  if (!state.drag) return;
  const point = stagePoint(event), scale = stageScale();
  const obj = state.scene.objects.find((item) => item.objectId === state.drag.id);
  obj.position.x = clamp(point.x / scale, -20, 20);
  obj.position.z = clamp(point.y / scale, -20, 20);
  renderStage(); renderInspector();
}

function endDrag(event) {
  if (!state.drag) return;
  state.drag = null;
  try { stage.releasePointerCapture(event.pointerId); } catch {}
  restartIfPlaying();
}

function stagePoint(event) {
  const rect = stage.getBoundingClientRect();
  return { x: event.clientX - rect.left - rect.width / 2, y: event.clientY - rect.top - rect.height / 2 };
}
function stageScale() { return Math.max(8, Math.min(stage.clientWidth, stage.clientHeight) / 44); }

function renderTransport() {
  const time = currentPlayhead();
  $("#timeline").value = time;
  $("#time-label").value = `${formatTime(time)} / ${formatTime(state.scene.durationSeconds)}`;
}

function listenerYawDegrees() {
  const forward = state.scene?.listener?.forward ?? { x: 0, z: -1 };
  return Math.atan2(forward.x, -forward.z) * 180 / Math.PI;
}

function setListenerYaw(degrees) {
  const angle = degrees * Math.PI / 180;
  state.scene.listener ??= { position: { x: 0, y: 0, z: 0 }, forward: { x: 0, y: 0, z: -1 }, up: { x: 0, y: 1, z: 0 } };
  state.scene.listener.forward = { x: Math.sin(angle), y: 0, z: -Math.cos(angle) };
}

function applyListenerToAudio() {
  if (!state.context || !state.scene) return;
  const pose = state.scene.listener ?? {};
  const position = pose.position ?? { x: 0, y: 0, z: 0 };
  const forward = pose.forward ?? { x: 0, y: 0, z: -1 };
  const up = pose.up ?? { x: 0, y: 1, z: 0 };
  const listener = state.context.listener;
  setAudioParam(listener.positionX, position.x); setAudioParam(listener.positionY, position.y); setAudioParam(listener.positionZ, position.z);
  setAudioParam(listener.forwardX, forward.x); setAudioParam(listener.forwardY, forward.y); setAudioParam(listener.forwardZ, forward.z);
  setAudioParam(listener.upX, up.x); setAudioParam(listener.upY, up.y); setAudioParam(listener.upZ, up.z);
}

function restartIfPlaying() { if (state.playing) play(); }
function metricId(metric) { return metric.metricId ?? metric.metric_id ?? "metric"; }
function getPath(object, path) { return path.split(".").reduce((value, key) => value?.[key], object); }
function setPath(object, path, value) {
  const parts = path.split("."); let target = object;
  for (const key of parts.slice(0, -1)) target = target[key] ??= {};
  target[parts.at(-1)] = value;
}
function defaults() { return { controls: { gainDb: 0, targetLufs: null, brightnessDb: 0, brightnessHz: 2500, roughnessDepth: 0, roughnessRateHz: 70, fluctuationDepth: 0, fluctuationRateHz: 4, attackSeconds: null, pitchSemitones: 0, tonalFocus: 0, safetyPeak: .98 } }; }
function formatNumber(value) { const n = Number(value); return Math.abs(n) >= 100 ? n.toFixed(1) : Math.abs(n) >= 10 ? n.toFixed(2) : n.toFixed(3); }
function formatTime(seconds) { const m = Math.floor(seconds / 60); const s = seconds - m * 60; return `${m}:${s.toFixed(3).padStart(6, "0")}`; }
function dbToGain(db) { return 10 ** (db / 20); }
function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
function setAudioParam(param, value) { if (param) param.value = value; }
function colorFor(text) { let hash = 0; for (const ch of text) hash = ((hash << 5) - hash + ch.charCodeAt(0)) | 0; return `hsl(${Math.abs(hash) % 360} 66% 69%)`; }
function notice(text) { const el = $("#notice"); el.textContent = text; el.classList.add("visible"); clearTimeout(notice.timer); notice.timer = setTimeout(() => el.classList.remove("visible"), 3500); }

function syntheticImpulse(context, duration, damping) {
  const length = Math.max(1, Math.floor(context.sampleRate * duration));
  const buffer = context.createBuffer(2, length, context.sampleRate);
  let seed = state.scene.room?.seed ?? 17;
  const random = () => { seed = (1664525 * seed + 1013904223) >>> 0; return seed / 2 ** 32; };
  for (let channel = 0; channel < 2; channel++) {
    const data = buffer.getChannelData(channel);
    for (let i = 0; i < length; i++) {
      const t = i / length;
      data[i] = (random() * 2 - 1) * Math.exp(-6 * t) * (1 - damping * t);
    }
  }
  return buffer;
}
