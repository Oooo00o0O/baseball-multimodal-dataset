import WaveSurfer from "/static/vendor/wavesurfer-7.12.11/wavesurfer.esm.js";
import RegionsPlugin from "/static/vendor/wavesurfer-7.12.11/regions.esm.js";


const PAGE_SIZE = 20;
const LEGACY_LABELS = {
  pass: "合格",
  corrected_pass: "修正后合格",
  no_contact: "没有击球",
  material_issue: "音视频或文件问题",
  uncertain: "待定 / 无法判断",
};
const PREP_LABELS = {
  idle: "待命",
  running: "准备中",
  completed: "已完成",
  failed: "失败",
  unavailable: "便携版不下载",
};

const state = {
  samples: [],
  sample: null,
  summary: null,
  errorCodes: {},
  index: 0,
  queueFilter: "all",
  queueSearch: "",
  queuePage: 0,
  wavesurfer: null,
  regions: null,
  hitRegion: null,
  restoredAutoPoint: false,
  loadToken: 0,
  videoFrameRequest: null,
  saving: false,
  videoPreparation: null,
  preparationPoll: null,
  toastTimer: null,
  resultsRelpath: "",
  legacyResultsRelpath: "",
  defaultReviewerId: "",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function formatTime(value) {
  return Number.isFinite(value) ? `${Number(value).toFixed(3)} s` : "—";
}

function formatDate(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? String(value) : parsed.toLocaleString("zh-CN");
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `${response.status} ${response.statusText}`);
  }
  return payload;
}

function showToast(message, error = false) {
  const toast = $("#toast");
  clearTimeout(state.toastTimer);
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.classList.add("show");
  state.toastTimer = setTimeout(() => toast.classList.remove("show"), 3600);
}

function setText(selector, value) {
  const node = $(selector);
  if (node) node.textContent = value;
}

function radioValue(name) {
  return document.querySelector(`input[name="${name}"]:checked`)?.value || "";
}

function setRadio(name, value) {
  $$(`input[name="${name}"]`).forEach((input) => {
    input.checked = input.value === value;
  });
}

function clearRadio(name) {
  $$(`input[name="${name}"]`).forEach((input) => {
    input.checked = false;
  });
}

function setCodes(codes) {
  const selected = new Set(Array.isArray(codes)
    ? codes
    : String(codes || "").split(";").filter(Boolean));
  $$('#errorCodeGrid input[type="checkbox"]').forEach((input) => {
    input.checked = selected.has(input.value);
  });
}

function selectedCodes() {
  return $$('#errorCodeGrid input[type="checkbox"]:checked').map((input) => input.value);
}

function setCodeChecked(code, checked) {
  const input = document.querySelector(`#errorCodeGrid input[value="${code}"]`);
  if (input) input.checked = checked;
}

function renderRelationshipHint() {
  const hint = $("#relationshipHint");
  if (!hint) return;
  const conclusion = radioValue("conclusion");
  const contains = radioValue("contains_contact");
  const timeCorrect = radioValue("original_time_correct");
  const full = radioValue("full_process");
  const replay = radioValue("replay");
  const codes = selectedCodes();
  const missing = [];

  if (conclusion === "D") {
    hint.textContent = "舍弃不计入正式数量；请在备注中写清无法判断的原因。";
    hint.className = "relationship-hint";
    return;
  }
  if (conclusion === "V") {
    const valid = contains === "Y" && timeCorrect === "Y"
      && full === "Y" && replay === "N" && codes.length === 0;
    hint.textContent = valid
      ? "对应关系正确：V = 有击球 + 原时间正确 + 过程完整 + 非回放，并且没有错误代码。"
      : "V 只能对应：有击球=是、原时间正确=是、过程完整=是、回放=否、无错误代码。";
    hint.className = `relationship-hint ${valid ? "is-valid" : "is-warning"}`;
    return;
  }
  if (conclusion === "I") {
    if (contains === "N" && !codes.includes("E01")) missing.push("无击球需要 E01");
    if (contains === "Y" && timeCorrect === "N" && !codes.includes("E02")) missing.push("时间错误需要 E02");
    if (contains === "Y" && full === "N" && !codes.some((code) => ["E04", "E05", "E07"].includes(code))) {
      missing.push("过程不完整需要 E04、E05 或 E07");
    }
    if (replay === "Y" && !codes.includes("E06")) missing.push("回放需要 E06");
    if (!codes.length) missing.push("至少选择一个错误代码");
    hint.textContent = missing.length
      ? `当前 I 还缺少对应关系：${missing.join("；")}。`
      : `当前对应：I · ${codes.join(" + ")}。`;
    hint.className = `relationship-hint ${missing.length ? "is-warning" : "is-valid"}`;
    return;
  }
  hint.textContent = "先选结论或四项判断；系统会自动对应可以确定的错误代码。";
  hint.className = "relationship-hint";
}

function synchronizeConclusionFromChecks() {
  if (radioValue("conclusion") === "D") {
    renderRelationshipHint();
    return;
  }
  const contains = radioValue("contains_contact");
  const timeCorrect = radioValue("original_time_correct");
  const full = radioValue("full_process");
  const replay = radioValue("replay");
  const codes = selectedCodes();
  if (contains === "Y" && timeCorrect === "Y" && full === "Y" && replay === "N" && !codes.length) {
    setRadio("conclusion", "V");
  } else if (contains || timeCorrect || full || replay || codes.length) {
    setRadio("conclusion", "I");
  }
  renderRelationshipHint();
}

function currentQueueItem() {
  return state.samples[state.index] || null;
}

function reviewStateLabel(item) {
  if (item.review_state === "current") return item.conclusion || "新记录";
  if (item.review_state === "legacy") {
    return `旧 · ${LEGACY_LABELS[item.legacy_status] || "已看"}`;
  }
  return "未查看";
}

function renderErrorCodes() {
  const grid = $("#errorCodeGrid");
  grid.replaceChildren();
  Object.entries(state.errorCodes).forEach(([code, definition]) => {
    const label = document.createElement("label");
    label.className = "error-code-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = code;
    const copy = document.createElement("span");
    const strong = document.createElement("strong");
    strong.textContent = code;
    const labelText = typeof definition === "string"
      ? definition
      : `${definition.name}：${definition.description}`;
    copy.append(strong, document.createTextNode(labelText));
    label.append(input, copy);
    grid.append(label);
  });
}

function renderSummary() {
  const summary = state.summary;
  if (!summary) return;
  const counts = summary.export_conclusion_counts || summary.conclusion_counts || {};
  setText("#headerVisited", summary.visited);
  setText("#headerFormal", summary.export_formal_reviewed ?? summary.formal_reviewed);
  setText("#headerRemaining", summary.remaining);
  setText("#statTotal", summary.total);
  setText("#statVisited", summary.visited);
  setText("#statRemaining", summary.remaining);
  setText("#statLegacy", summary.legacy_mapped_total ?? summary.legacy_total);
  setText("#statFormal", summary.export_formal_reviewed ?? summary.formal_reviewed);
  setText("#statDiscarded", summary.export_discarded ?? summary.discarded);
  setText("#statV", counts.V || 0);
  setText("#statI", counts.I || 0);
  setText("#newResultsPath", state.resultsRelpath);
  setText("#legacyResultsPath", state.legacyResultsRelpath);
}

function queueMatches(item) {
  const query = state.queueSearch.trim().toLowerCase();
  if (query && !`${item.sample_id} ${item.audit_id}`.toLowerCase().includes(query)) {
    return false;
  }
  if (state.queueFilter === "all") return true;
  if (state.queueFilter === "untouched") return item.review_state === "untouched";
  if (state.queueFilter === "reviewed") return item.review_state !== "untouched";
  const effectiveConclusion = item.review_state === "current"
    ? item.conclusion
    : item.mapped_conclusion;
  return effectiveConclusion === state.queueFilter;
}

function syncQueuePageToCurrent() {
  const current = currentQueueItem();
  if (!current || !queueMatches(current)) return;
  const filtered = state.samples.filter(queueMatches);
  const filteredIndex = filtered.findIndex((item) => item.audit_id === current.audit_id);
  if (filteredIndex >= 0) state.queuePage = Math.floor(filteredIndex / PAGE_SIZE);
}

function renderQueue() {
  const filtered = state.samples.filter(queueMatches);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  state.queuePage = Math.min(state.queuePage, pages - 1);
  const begin = state.queuePage * PAGE_SIZE;
  const visible = filtered.slice(begin, begin + PAGE_SIZE);
  setText("#queueCount", `${filtered.length} 条`);
  setText("#queuePage", `${state.queuePage + 1} / ${pages}`);
  $("#queuePrevPage").disabled = state.queuePage <= 0;
  $("#queueNextPage").disabled = state.queuePage >= pages - 1;

  const list = $("#queueList");
  list.replaceChildren();
  if (!visible.length) {
    const empty = document.createElement("p");
    empty.className = "empty-queue";
    empty.textContent = "这个筛选下没有样本。";
    list.append(empty);
    return;
  }
  visible.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "queue-item";
    if (item.audit_id === currentQueueItem()?.audit_id) button.classList.add("active");
    button.dataset.auditId = item.audit_id;

    const position = document.createElement("span");
    position.className = "queue-position";
    position.textContent = item.position;
    const copy = document.createElement("span");
    copy.className = "queue-copy";
    const title = document.createElement("strong");
    title.textContent = item.sample_id;
    const meta = document.createElement("small");
    meta.textContent = `第 ${item.batch_number} 批 · ${item.batch_position}/20${item.video_state === "ready_local" ? "" : " · 缺视频"}`;
    copy.append(title, meta);
    const status = document.createElement("span");
    status.className = "queue-status";
    status.textContent = reviewStateLabel(item);
    if (item.review_state === "legacy") status.classList.add("legacy");
    if (item.review_state === "current") status.classList.add(item.conclusion);
    button.append(position, copy, status);
    list.append(button);
  });
}

function renderSampleHeader() {
  const sample = state.sample;
  const item = currentQueueItem();
  if (!sample || !item) return;
  setText("#samplePosition", `${sample.position} / ${sample.total}`);
  setText("#sampleId", sample.sample_id);
  setText("#sampleAuditId", sample.audit_id);
  setText("#batchBadge", `第 ${sample.batch_number} 批 · ${sample.batch_position} / 20`);
  setText("#intervalReadout", `原标注：${formatTime(sample.event_start)} – ${formatTime(sample.event_end)}`);
  const automaticPoint = Number.isFinite(sample.auto_hit_time) ? sample.auto_hit_time : null;
  $("#restoreAutoPointButton").disabled = automaticPoint === null;
  $("#restoreAutoPointButton").title = automaticPoint === null
    ? "本条没有自动建议点"
    : `恢复到最初自动建议点 ${automaticPoint.toFixed(3)} s`;

  const record = $("#recordBadge");
  record.className = "soft-badge";
  record.textContent = reviewStateLabel(item);
  if (item.review_state === "legacy") record.classList.add("is-legacy");
  if (item.review_state === "current") record.classList.add(`is-${item.conclusion}`);

  const video = $("#videoBadge");
  video.className = "soft-badge";
  if (sample.video_state === "ready_local") {
    video.textContent = "视频已准备";
  } else {
    video.textContent = "视频未准备";
    video.classList.add("is-missing");
  }
}

function legacyValueRow(term, value, wide = false) {
  const wrapper = document.createElement("div");
  if (wide) wrapper.className = "wide";
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value || "—";
  wrapper.append(dt, dd);
  return wrapper;
}

function renderLegacy() {
  const card = $("#legacyCard");
  const legacy = state.sample?.legacy_review;
  if (!legacy) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  const label = LEGACY_LABELS[legacy.review_status] || legacy.review_status;
  setText("#legacyTitle", `旧结论：${label}`);
  setText("#legacyBadge", state.sample.review ? "旧记录仍保留" : "当前只读记录");
  const details = $("#legacyDetails");
  details.replaceChildren(
    legacyValueRow("旧版状态", label),
    legacyValueRow("旧版有效击球点", formatTime(legacy.effective_hit_time)),
    legacyValueRow("保存时间", formatDate(legacy.reviewed_at_utc)),
    legacyValueRow("文件问题原因", legacy.material_reason || "—"),
    legacyValueRow("击球点来源", legacy.effective_hit_source || "—"),
    legacyValueRow("旧版备注", legacy.notes || "—", true),
  );
}

function resetForm() {
  state.restoredAutoPoint = false;
  ["conclusion", "contains_contact", "original_time_correct", "full_process", "replay"].forEach(clearRadio);
  setCodes([]);
  $("#correctContactTime").value = "";
  $("#reviewNotes").value = "";
}

function populateReviewFields(record) {
  setRadio("conclusion", record.conclusion);
  setRadio("contains_contact", record.contains_contact);
  setRadio("original_time_correct", record.original_time_correct);
  setRadio("full_process", record.full_process);
  setRadio("replay", record.replay);
  setCodes(record.error_codes);
  $("#correctContactTime").value = Number.isFinite(record.correct_contact_time)
    ? Number(record.correct_contact_time).toFixed(3)
    : "";
  $("#reviewNotes").value = record.notes || "";
}

function loadForm() {
  const review = state.sample?.review;
  const mapped = state.sample?.legacy_mapped_review;
  resetForm();
  if (review) {
    populateReviewFields(review);
    $("#deleteReviewButton").hidden = false;
    setText("#formState", `新记录已保存：${review.conclusion} · ${formatDate(review.reviewed_at_utc)}`);
    $("#formState").className = "form-state is-saved";
  } else if (mapped) {
    populateReviewFields(mapped);
    $("#deleteReviewButton").hidden = true;
    const codes = mapped.error_codes ? ` / ${mapped.error_codes}` : "";
    setText(
      "#formState",
      `旧版 ${mapped.legacy_review_status} 已自动对应为 ${mapped.conclusion}${codes}；会直接进入合并导出，保存只用于人工调整。`,
    );
    $("#formState").className = "form-state is-saved";
  } else {
    $("#deleteReviewButton").hidden = true;
    setText("#formState", "尚未保存记录");
    $("#formState").className = "form-state";
  }
  renderRelationshipHint();
}

function destroyMedia() {
  const video = $("#videoPlayer");
  if (video && state.videoFrameRequest !== null && "cancelVideoFrameCallback" in video) {
    video.cancelVideoFrameCallback(state.videoFrameRequest);
  }
  state.videoFrameRequest = null;
  if (video) {
    video.pause();
    video.removeAttribute("src");
    video.load();
  }
  state.wavesurfer?.destroy();
  state.wavesurfer = null;
  state.regions = null;
  state.hitRegion = null;
  $("#waveform")?.replaceChildren();
}

function setupVideo(sample, token) {
  const video = $("#videoPlayer");
  const placeholder = $("#videoPlaceholder");
  video.muted = true;
  video.volume = 0;
  video.onvolumechange = () => {
    video.muted = true;
    video.volume = 0;
  };
  if (!sample.video_url) {
    video.hidden = true;
    placeholder.hidden = false;
    return;
  }
  video.hidden = false;
  placeholder.hidden = true;
  video.src = sample.video_url;
  video.playbackRate = Number($("#playbackRate").value);
  video.load();
  monitorVideoFrames(video, token);
}

function effectivePoint() {
  if (state.restoredAutoPoint && Number.isFinite(state.sample?.auto_hit_time)) {
    return state.sample.auto_hit_time;
  }
  const typed = Number($("#correctContactTime")?.value);
  if ($("#correctContactTime")?.value !== "" && Number.isFinite(typed)) return typed;
  if (Number.isFinite(state.sample?.review?.correct_contact_time)) {
    return state.sample.review.correct_contact_time;
  }
  return Number.isFinite(state.sample?.auto_hit_time) ? state.sample.auto_hit_time : null;
}

function addHitRegion(value, duration = state.wavesurfer?.getDuration() || 0) {
  state.hitRegion?.remove();
  state.hitRegion = null;
  if (!state.regions || !Number.isFinite(value) || duration <= 0) return;
  state.hitRegion = state.regions.addRegion({
    id: "hit-point",
    start: Math.max(0, Math.min(duration, value)),
    color: "#b42318",
    drag: true,
    resize: false,
    content: "击球点",
  });
}

function setupWaveform(sample, token) {
  const regions = RegionsPlugin.create();
  const wavesurfer = WaveSurfer.create({
    container: "#waveform",
    url: sample.audio_url,
    height: 118,
    waveColor: "#9aa7b3",
    progressColor: "#4f7fbd",
    cursorColor: "#17202a",
    cursorWidth: 2,
    normalize: true,
    dragToSeek: true,
    hideScrollbar: true,
    plugins: [regions],
  });
  state.wavesurfer = wavesurfer;
  state.regions = regions;

  wavesurfer.on("ready", (duration) => {
    if (token !== state.loadToken) return;
    setText("#waveDuration", formatTime(duration));
    const start = Number.isFinite(sample.event_start) ? Math.max(0, Math.min(duration, sample.event_start)) : null;
    const end = Number.isFinite(sample.event_end) ? Math.max(0, Math.min(duration, sample.event_end)) : null;
    if (start !== null && end !== null && end > start) {
      regions.addRegion({
        id: "candidate-interval",
        start,
        end,
        color: "rgba(37, 99, 235, 0.14)",
        drag: false,
        resize: false,
        content: "原范围",
      });
    }
    addHitRegion(effectivePoint(), duration);
    const cue = Number.isFinite(start) ? start : effectivePoint() || 0;
    wavesurfer.setTime(Math.max(0, cue - 0.45));
    syncVideo(true);
    renderTimeReadout();
  });
  wavesurfer.on("error", (error) => showToast(`音频加载失败：${error?.message || error}`, true));
  wavesurfer.on("play", () => {
    $("#playPauseButton").textContent = "暂停";
    followAudioPlay(token);
  });
  wavesurfer.on("pause", () => {
    $("#playPauseButton").textContent = "播放";
    $("#videoPlayer").pause();
  });
  wavesurfer.on("finish", () => {
    $("#playPauseButton").textContent = "播放";
    $("#videoPlayer").pause();
  });
  wavesurfer.on("seeking", () => syncVideo(true));
  wavesurfer.on("interaction", () => syncVideo(true));
  wavesurfer.on("timeupdate", () => {
    renderTimeReadout();
    syncVideo(false);
  });
  regions.on("region-updated", (region) => {
    if (region.id !== "hit-point") return;
    state.restoredAutoPoint = false;
    $("#correctContactTime").value = region.start.toFixed(3);
    showToast(`正确击球秒已移到 ${region.start.toFixed(3)} s；保存后才会写入 CSV。`);
  });
}

function renderTimeReadout() {
  const current = state.wavesurfer?.getCurrentTime() || 0;
  const duration = state.wavesurfer?.getDuration();
  setText("#timeReadout", `${current.toFixed(3)} / ${Number.isFinite(duration) ? duration.toFixed(3) : "—"}`);
}

async function followAudioPlay(token) {
  if (token !== state.loadToken) return;
  const video = $("#videoPlayer");
  if (!video || video.hidden || !video.src) return;
  video.muted = true;
  video.volume = 0;
  syncVideo(true);
  await video.play().catch(() => {});
}

function syncVideo(force) {
  const video = $("#videoPlayer");
  const wavesurfer = state.wavesurfer;
  if (!video || video.hidden || !video.src || !wavesurfer || video.readyState < 1) return;
  const audioTime = wavesurfer.getCurrentTime();
  const drift = video.currentTime - audioTime;
  if (force || Math.abs(drift) > 0.05) {
    video.currentTime = Math.max(0, Math.min(video.duration || audioTime, audioTime));
  }
  if (wavesurfer.isPlaying() && video.paused) {
    video.play().catch(() => {});
  } else if (!wavesurfer.isPlaying() && !video.paused) {
    video.pause();
  }
}

function monitorVideoFrames(video, token) {
  if (!("requestVideoFrameCallback" in video)) return;
  const callback = () => {
    if (token !== state.loadToken || video.hidden) return;
    syncVideo(false);
    state.videoFrameRequest = video.requestVideoFrameCallback(callback);
  };
  state.videoFrameRequest = video.requestVideoFrameCallback(callback);
}

async function loadSample(notice = "") {
  const item = currentQueueItem();
  if (!item) return;
  const token = ++state.loadToken;
  destroyMedia();
  try {
    const sample = await fetchJson(`/api/sample/${encodeURIComponent(item.audit_id)}`);
    if (token !== state.loadToken) return;
    state.sample = sample;
    renderSampleHeader();
    renderLegacy();
    loadForm();
    setupVideo(sample, token);
    setupWaveform(sample, token);
    renderQueue();
    if (notice) showToast(notice);
  } catch (error) {
    if (token !== state.loadToken) return;
    showToast(`样本载入失败：${error.message}`, true);
  }
}

function collectForm() {
  const timeText = $("#correctContactTime").value.trim();
  return {
    reviewer_id: state.sample?.review?.reviewer_id || state.defaultReviewerId,
    conclusion: radioValue("conclusion"),
    contains_contact: radioValue("contains_contact"),
    original_time_correct: radioValue("original_time_correct"),
    full_process: radioValue("full_process"),
    replay: radioValue("replay"),
    correct_contact_time: timeText === "" ? null : Number(timeText),
    error_codes: selectedCodes(),
    notes: $("#reviewNotes").value.trim(),
  };
}

function validateForm(payload) {
  if (!["V", "I", "D"].includes(payload.conclusion)) return "请选择 V、I 或舍弃。";
  if (payload.conclusion !== "D") {
    const checks = [
      ["contains_contact", "是否包含击球事件"],
      ["original_time_correct", "原击球时间是否正确"],
      ["full_process", "击球前后过程是否完整"],
      ["replay", "是否为回放 / 慢动作"],
    ];
    const missing = checks.find(([field]) => !payload[field]);
    if (missing) return `请完成“四项判断”中的：${missing[1]}。`;
  }
  if (payload.conclusion === "I" && !payload.error_codes.length) return "I 至少需要选择一个错误代码。";
  if (payload.conclusion === "D" && !payload.notes) {
    return "舍弃需要写一句无法判断的原因。";
  }
  if (payload.contains_contact === "Y" && payload.original_time_correct === "N"
      && !Number.isFinite(payload.correct_contact_time)) {
    return "有击球但原时间错误时，必须填写正确击球秒数。";
  }
  return "";
}

function updateQueueAfterSave(review) {
  const item = currentQueueItem();
  item.review_state = "current";
  item.conclusion = review.conclusion;
  item.error_codes = review.error_codes;
}

async function saveReview(moveNext) {
  if (!state.sample || state.saving) return;
  const payload = collectForm();
  const problem = validateForm(payload);
  if (problem) {
    $("#formState").textContent = problem;
    $("#formState").className = "form-state is-error";
    showToast(problem, true);
    return;
  }
  state.saving = true;
  $("#saveStayButton").disabled = true;
  $("#saveNextButton").disabled = true;
  try {
    const response = await fetchJson(`/api/review/${encodeURIComponent(state.sample.audit_id)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.sample.review = response.review;
    state.summary = response.summary;
    updateQueueAfterSave(response.review);
    renderSummary();
    renderSampleHeader();
    renderLegacy();
    loadForm();
    renderQueue();
    showToast(`已保存 ${state.sample.sample_id}：${response.review.conclusion}`);
    if (moveNext) await goNextUntouched();
  } catch (error) {
    $("#formState").textContent = `保存失败：${error.message}`;
    $("#formState").className = "form-state is-error";
    showToast(`保存失败：${error.message}`, true);
  } finally {
    state.saving = false;
    $("#saveStayButton").disabled = false;
    $("#saveNextButton").disabled = false;
  }
}

async function deleteReview() {
  if (!state.sample?.review || state.saving) return;
  if (!window.confirm("只删除这条“新格式”记录吗？旧版 CSV（若存在）不会被删除。")) return;
  state.saving = true;
  try {
    const response = await fetchJson(`/api/review/${encodeURIComponent(state.sample.audit_id)}`, {
      method: "DELETE",
    });
    state.summary = response.summary;
    state.sample.review = null;
    const item = currentQueueItem();
    item.review_state = state.sample.legacy_review ? "legacy" : "untouched";
    item.conclusion = null;
    item.error_codes = "";
    renderSummary();
    renderSampleHeader();
    loadForm();
    renderQueue();
    addHitRegion(effectivePoint());
    showToast("本条新格式记录已删除；旧版记录没有改变。");
  } catch (error) {
    showToast(`删除失败：${error.message}`, true);
  } finally {
    state.saving = false;
  }
}

async function goTo(index, notice = "") {
  if (!state.samples.length) return;
  const scrollTop = window.scrollY;
  state.index = Math.max(0, Math.min(state.samples.length - 1, index));
  syncQueuePageToCurrent();
  await loadSample(notice);
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: scrollTop, behavior: "auto" });
  });
}

async function goNextUntouched() {
  for (let offset = 1; offset <= state.samples.length; offset += 1) {
    const candidate = (state.index + offset) % state.samples.length;
    if (state.samples[candidate].review_state === "untouched") {
      await goTo(candidate);
      return;
    }
  }
  showToast("队列里已经没有未查看样本。");
}

function applyPreset(preset) {
  if (preset === "valid") {
    state.restoredAutoPoint = true;
    setRadio("conclusion", "V");
    setRadio("contains_contact", "Y");
    setRadio("original_time_correct", "Y");
    setRadio("full_process", "Y");
    setRadio("replay", "N");
    setCodes([]);
    $("#correctContactTime").value = "";
  } else if (preset === "no-contact") {
    state.restoredAutoPoint = false;
    setRadio("conclusion", "I");
    setRadio("contains_contact", "N");
    setRadio("original_time_correct", "N");
    setRadio("full_process", "N");
    setRadio("replay", "N");
    setCodes(["E01"]);
    $("#correctContactTime").value = "";
  } else if (preset === "wrong-time") {
    state.restoredAutoPoint = false;
    setRadio("conclusion", "I");
    setRadio("contains_contact", "Y");
    setRadio("original_time_correct", "N");
    setRadio("full_process", "Y");
    setRadio("replay", "N");
    setCodes(["E02"]);
    const current = state.wavesurfer?.getCurrentTime();
    const point = Number.isFinite(current) && current > 0 ? current : state.sample?.auto_hit_time;
    $("#correctContactTime").value = Number.isFinite(point) ? Number(point).toFixed(3) : "";
  } else if (preset === "discard") {
    state.restoredAutoPoint = false;
    setRadio("conclusion", "D");
    ["contains_contact", "original_time_correct", "full_process", "replay"].forEach(clearRadio);
    setCodes([]);
    $("#correctContactTime").value = "";
    $("#reviewNotes").focus();
    showToast("请在备注中写明为什么无法判断；舍弃不计入正式 20 条。");
  }
  addHitRegion(effectivePoint());
  renderRelationshipHint();
}

function handleBinaryChange(event) {
  if (!(event.target instanceof HTMLInputElement) || !event.target.checked) return;
  const field = event.target.name;
  const value = event.target.value;
  if (field === "contains_contact") {
    if (value === "N") {
      setRadio("conclusion", "I");
      setRadio("original_time_correct", "N");
      setRadio("full_process", "N");
      if (!radioValue("replay")) setRadio("replay", "N");
      setCodeChecked("E01", true);
      setCodeChecked("E02", false);
      $("#correctContactTime").value = "";
    } else {
      setCodeChecked("E01", false);
    }
  } else if (field === "original_time_correct") {
    if (value === "N" && radioValue("contains_contact") === "Y") {
      setRadio("conclusion", "I");
      setCodeChecked("E02", true);
      const point = effectivePoint();
      if (!$("#correctContactTime").value && Number.isFinite(point)) {
        $("#correctContactTime").value = Number(point).toFixed(3);
      }
    } else if (value === "Y") {
      setCodeChecked("E02", false);
    }
  } else if (field === "full_process") {
    if (value === "N" && radioValue("contains_contact") === "Y") {
      setRadio("conclusion", "I");
      setCodeChecked("E07", true);
    } else if (value === "Y") {
      ["E04", "E05", "E07"].forEach((code) => setCodeChecked(code, false));
    }
  } else if (field === "replay") {
    setCodeChecked("E06", value === "Y");
    if (value === "Y") {
      setRadio("conclusion", "I");
    }
  }
  synchronizeConclusionFromChecks();
  addHitRegion(effectivePoint());
}

function handleCodeChange(event) {
  if (!(event.target instanceof HTMLInputElement) || event.target.type !== "checkbox") return;
  if (!event.target.checked) {
    synchronizeConclusionFromChecks();
    return;
  }
  setRadio("conclusion", "I");
  const code = event.target.value;
  if (code === "E01" || code === "E03") {
    setRadio("contains_contact", "N");
    setRadio("original_time_correct", "N");
    setRadio("full_process", "N");
    if (!radioValue("replay")) setRadio("replay", "N");
    setCodeChecked("E01", true);
    $("#correctContactTime").value = "";
  } else if (code === "E02") {
    setRadio("contains_contact", "Y");
    setRadio("original_time_correct", "N");
    if (!radioValue("full_process")) setRadio("full_process", "Y");
    if (!radioValue("replay")) setRadio("replay", "N");
    const point = effectivePoint();
    if (!$("#correctContactTime").value && Number.isFinite(point)) {
      $("#correctContactTime").value = Number(point).toFixed(3);
    }
  } else if (["E04", "E05", "E07"].includes(code)) {
    if (!radioValue("contains_contact")) setRadio("contains_contact", "Y");
    setRadio("full_process", "N");
    if (!radioValue("original_time_correct")) setRadio("original_time_correct", "Y");
    if (!radioValue("replay")) setRadio("replay", "N");
  } else if (code === "E06") {
    setRadio("replay", "Y");
  }
  synchronizeConclusionFromChecks();
  addHitRegion(effectivePoint());
}

function renderVideoPreparation() {
  const prep = state.videoPreparation || { state: "idle" };
  const status = prep.state || "idle";
  setText("#videoPrepStatus", PREP_LABELS[status] || status);
  $("#prepareVideosButton").disabled = status === "running" || status === "unavailable";
  let percent = 0;
  let message = "当前没有运行视频准备任务。";
  if (status === "running") {
    percent = 35;
    message = `正在从当前条开始检查，最多处理 ${prep.max_files || "—"} 个文件…`;
  } else if (status === "completed") {
    percent = 100;
    const summary = prep.summary || {};
    const prepared = summary.downloaded ?? summary.prepared ?? summary.downloaded_count;
    message = prepared === undefined
      ? "视频准备已完成。队列状态将刷新。"
      : `视频准备已完成，本次新增或更新 ${prepared} 个文件。`;
  } else if (status === "failed") {
    message = `视频准备失败：${prep.error || "未知错误"}`;
  } else if (status === "unavailable") {
    message = prep.error || "便携版不会联网下载或修改视频。";
  }
  $("#videoPrepBar").style.width = `${percent}%`;
  setText("#videoPrepMessage", message);
}

async function refreshWorkbenchAfterPreparation() {
  const currentId = currentQueueItem()?.audit_id;
  const payload = await fetchJson("/api/workbench");
  state.samples = payload.samples;
  state.summary = payload.summary;
  state.index = Math.max(0, state.samples.findIndex((item) => item.audit_id === currentId));
  renderSummary();
  renderQueue();
  await loadSample("视频准备状态已刷新。");
}

async function pollVideoPreparation() {
  clearTimeout(state.preparationPoll);
  try {
    state.videoPreparation = await fetchJson("/api/video-preparation");
    renderVideoPreparation();
    if (state.videoPreparation.state === "running") {
      state.preparationPoll = setTimeout(pollVideoPreparation, 1500);
    } else if (state.videoPreparation.state === "completed") {
      await refreshWorkbenchAfterPreparation();
    }
  } catch (error) {
    state.videoPreparation = { state: "failed", error: error.message };
    renderVideoPreparation();
  }
}

async function startVideoPreparation() {
  if (!state.sample || state.videoPreparation?.state === "running") return;
  const maxFiles = Number($("#videoPrepCount").value || 25);
  try {
    state.videoPreparation = await fetchJson("/api/video-preparation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        start_audit_id: state.sample.audit_id,
        max_files: maxFiles,
      }),
    });
    renderVideoPreparation();
    showToast("视频准备已开始；页面会自动刷新状态。");
    state.preparationPoll = setTimeout(pollVideoPreparation, 1000);
  } catch (error) {
    showToast(`无法开始视频准备：${error.message}`, true);
  }
}

function bindEvents() {
  $("#playPauseButton").addEventListener("click", () => state.wavesurfer?.playPause());
  $("#restartButton").addEventListener("click", () => {
    state.wavesurfer?.setTime(0);
    syncVideo(true);
  });
  $("#playbackRate").addEventListener("change", () => {
    const rate = Number($("#playbackRate").value);
    state.wavesurfer?.setPlaybackRate(rate);
    $("#videoPlayer").playbackRate = rate;
  });
  $("#setCurrentTimeButton").addEventListener("click", () => {
    if (!state.wavesurfer) return;
    const value = state.wavesurfer.getCurrentTime();
    state.restoredAutoPoint = false;
    $("#correctContactTime").value = value.toFixed(3);
    addHitRegion(value);
  });
  $("#restoreAutoPointButton").addEventListener("click", () => {
    const value = state.sample?.auto_hit_time;
    if (!Number.isFinite(value)) {
      showToast("本条没有可恢复的自动建议点。", true);
      return;
    }
    state.restoredAutoPoint = true;
    $("#correctContactTime").value = "";
    addHitRegion(value);
    if (state.wavesurfer) {
      state.wavesurfer.setTime(value);
      syncVideo(true);
    }
    renderRelationshipHint();
    showToast(`已恢复最初自动建议点 ${value.toFixed(3)} s；V / I 判断没有自动改变。`);
  });
  $("#jumpPointButton").addEventListener("click", () => {
    const value = effectivePoint();
    if (state.wavesurfer && Number.isFinite(value)) {
      state.wavesurfer.setTime(value);
      syncVideo(true);
    }
  });
  $("#correctContactTime").addEventListener("input", () => {
    state.restoredAutoPoint = false;
    addHitRegion(effectivePoint());
    renderRelationshipHint();
  });
  $$(".quick-button").forEach((button) => button.addEventListener("click", () => applyPreset(button.dataset.preset)));
  $$('input[name="conclusion"]').forEach((input) => input.addEventListener("change", () => {
    if (input.checked && input.value === "V") applyPreset("valid");
    if (input.checked && input.value === "D") {
      setCodes([]);
      $("#correctContactTime").value = "";
    }
    renderRelationshipHint();
  }));
  ["contains_contact", "original_time_correct", "full_process", "replay"].forEach((name) => {
    $$(`input[name="${name}"]`).forEach((input) => input.addEventListener("change", handleBinaryChange));
  });
  $("#errorCodeGrid").addEventListener("change", handleCodeChange);
  $("#saveStayButton").addEventListener("click", () => saveReview(false));
  $("#saveNextButton").addEventListener("click", () => saveReview(true));
  $("#deleteReviewButton").addEventListener("click", deleteReview);
  $("#previousButton").addEventListener("click", () => goTo(state.index - 1));
  $("#nextButton").addEventListener("click", () => goTo(state.index + 1));
  $("#nextUntouchedButton").addEventListener("click", goNextUntouched);
  $("#queueSearch").addEventListener("input", (event) => {
    state.queueSearch = event.target.value;
    state.queuePage = 0;
    renderQueue();
  });
  $$(".filter-button").forEach((button) => button.addEventListener("click", () => {
    $$(".filter-button").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
    state.queueFilter = button.dataset.filter;
    state.queuePage = 0;
    renderQueue();
  }));
  $("#queueList").addEventListener("click", (event) => {
    const item = event.target.closest(".queue-item");
    if (!item) return;
    const index = state.samples.findIndex((sample) => sample.audit_id === item.dataset.auditId);
    if (index >= 0) goTo(index);
  });
  $("#queuePrevPage").addEventListener("click", () => {
    state.queuePage = Math.max(0, state.queuePage - 1);
    renderQueue();
  });
  $("#queueNextPage").addEventListener("click", () => {
    state.queuePage += 1;
    renderQueue();
  });
  $("#prepareVideosButton").addEventListener("click", startVideoPreparation);
  window.addEventListener("keydown", (event) => {
    const typing = event.target instanceof HTMLInputElement
      || event.target instanceof HTMLTextAreaElement
      || event.target instanceof HTMLSelectElement
      || event.target?.isContentEditable;
    if (event.ctrlKey && event.key === "Enter") {
      event.preventDefault();
      saveReview(true);
      return;
    }
    const plainShortcut = !typing
      && !event.ctrlKey
      && !event.altKey
      && !event.metaKey
      && !event.repeat;
    if (plainShortcut && event.key.toLowerCase() === "j") {
      event.preventDefault();
      goTo(state.index + 1);
      return;
    }
    if (plainShortcut && event.key.toLowerCase() === "k") {
      event.preventDefault();
      goTo(state.index - 1);
      return;
    }
    if (plainShortcut && event.key.toLowerCase() === "v") {
      event.preventDefault();
      applyPreset("valid");
      showToast("快捷键 V：已选择完全合格。");
      return;
    }
    if (plainShortcut && (event.code === "Space" || event.key === " ")) {
      event.preventDefault();
      state.wavesurfer?.playPause();
    }
  });
}

async function init() {
  const payload = await fetchJson("/api/workbench");
  if (!payload.owner_validation) throw new Error("当前端口运行的不是 Groundball 新版验证服务");
  state.samples = payload.samples;
  state.summary = payload.summary;
  state.errorCodes = payload.error_codes;
  state.resultsRelpath = payload.results_relpath;
  state.defaultReviewerId = payload.default_reviewer_id || "";
  state.legacyResultsRelpath = payload.legacy_results_relpath;
  renderErrorCodes();
  bindEvents();
  renderSummary();
  const firstUntouched = state.samples.findIndex((item) => item.review_state === "untouched");
  state.index = firstUntouched >= 0 ? firstUntouched : 0;
  syncQueuePageToCurrent();
  renderQueue();
  await loadSample(
    state.summary.legacy_total
      ? `旧的 ${state.summary.legacy_total} 条记录已保留并可浏览；现在从第一条未查看样本继续。`
      : "现在从第一条未查看样本开始。",
  );
  $("#loadingOverlay").hidden = true;
  pollVideoPreparation();
}

init().catch((error) => {
  $("#loadingOverlay").hidden = true;
  showToast(`界面启动失败：${error.message}`, true);
  document.body.insertAdjacentHTML(
    "afterbegin",
    `<div style="margin:20px;padding:16px;border:1px solid #e0a29d;background:#fff4f3;color:#9f2218">
      Groundball 验证台无法启动：${String(error.message).replaceAll("<", "&lt;")}
    </div>`,
  );
});
