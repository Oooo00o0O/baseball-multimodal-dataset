import WaveSurfer from "/shared/vendor/wavesurfer-7.12.11/wavesurfer.esm.js";
import RegionsPlugin from "/shared/vendor/wavesurfer-7.12.11/regions.esm.js";


const PAGE_SIZE = 20;
const CONCLUSION_LABELS = {
  V: "V · 有效",
  I: "I · 无效",
  U: "U · 不确定",
};
const TRI_LABELS = {
  original_time_correct: ["原时间正确", "原区间是否框住真正击球声"],
  sound: ["声音", "是否有明确、短促的球棒击球声"],
  picture: ["画面", "声音附近是否看见击球接触阶段"],
  full_process: ["全过程", "击球前后长度与内容是否完整"],
  replay: ["回放", "Y 表示确实是回放或慢动作"],
};
const TRAJECTORIES = ["fly", "line_drive", "pop_fly", "unknown"];
let configuredReviewerId = "";

const state = {
  samples: [],
  sample: null,
  index: 0,
  summary: null,
  manifestSummary: null,
  errorCodes: {},
  resultsRelpath: "",
  queueFilter: "remaining",
  queueSearch: "",
  queuePage: 0,
  saving: false,
  message: "正在读取 Flyball 校准队列……",
  draft: emptyDraft(),
  wavesurfer: null,
  regions: null,
  contactRegion: null,
  loopCandidate: false,
  loadToken: 0,
  videoFrameRequest: null,
  videoDuration: null,
  fullPlaybackCount: 0,
  defaultReviewerId: "",
  drift: { currentMs: null, maxAbsMs: 0, corrections: 0, frames: 0 },
};


function emptyDraft() {
  return {
    reviewer_id: configuredReviewerId || localStorage.getItem("flyballCalibrationReviewerId") || "",
    conclusion: "",
    original_time_correct: "",
    contact_time: null,
    sound: "",
    picture: "",
    full_process: "",
    replay: "",
    trajectory: "",
    error_codes: new Set(),
    notes: "",
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatTime(value) {
  return Number.isFinite(value) ? `${value.toFixed(3)} s` : "—";
}

function conclusionLabel(value) {
  return CONCLUSION_LABELS[value] ?? "未审核";
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error ?? `${response.status} ${response.statusText}`);
  }
  return payload;
}

function topBar() {
  return `
    <header class="topbar">
      <div>
        <p class="eyebrow">团队便携版 · Flyball · 自动保存</p>
        <h1>Flyball 人工校准工作台</h1>
      </div>
      <div class="topbar-stats">
        <span id="progressText">样本 — / —</span>
        <span>已审核 <strong id="reviewedCount">0</strong></span>
        <span>剩余 <strong id="remainingCount">—</strong></span>
        <a class="button-link" href="/api/reviews/export" download>下载正式 CSV</a>
      </div>
    </header>`;
}

function videoPanel() {
  return `
    <section class="panel video-panel">
      <div class="section-heading">
        <div>
          <span class="step">01</span>
          <div>
            <p>正常速度完整播放两遍；不要把回放当成现场击球</p>
            <h2>静音视频 · <span id="sampleIdHeading" class="sample-id">—</span></h2>
          </div>
        </div>
        <span class="pill" id="videoState">准备状态</span>
      </div>
      <div class="video-stage">
        <video id="reviewVideo" muted playsinline preload="metadata"></video>
        <div id="videoPlaceholder" class="video-placeholder">
          <strong>视频未准备或缺失</strong>
          <span>请选择 E09，不要把文件问题判成没有击球</span>
        </div>
      </div>
      <div class="sync-strip">
        <span>audio.wav 是唯一声音；视频始终静音且跟随 0.000 秒时间轴</span>
        <span id="syncMetric">A/V 漂移：—</span>
      </div>
      <div class="sample-meta">
        <div><span>远程记录轨迹</span><strong id="recordedTrajectory">—</strong></div>
        <div><span>落地区</span><strong id="landingZone">—</strong></div>
        <div><span>强度</span><strong id="strength">—</strong></div>
        <div><span>完整播放</span><strong id="playbackCount">0 / 2</strong></div>
      </div>
      <p class="instruction-strip">
        <strong>判断顺序：</strong>先确认真实比赛和击球声音/画面，再检查原时间、片段长度、回放、轨迹与音画同步。不要根据标题或文件名猜。
      </p>
    </section>`;
}

function waveformPanel() {
  return `
    <section class="panel waveform-panel">
      <div class="section-heading">
        <div>
          <span class="step">02</span>
          <div><p>从当前 sample 的 0.000 秒计时</p><h2>音频波形、原范围与 contact_time</h2></div>
        </div>
        <span class="pill" id="contactState">击球点：—</span>
      </div>
      <div class="wave-shell">
        <div id="waveform"></div>
        <div id="waveLoading" class="wave-loading">正在解码 WAV……</div>
      </div>
      <div class="time-row">
        <span id="currentTime">0.000 s</span>
        <span id="intervalText">原范围：—</span>
        <span id="proposalText">建议点：—</span>
      </div>
      <div class="transport">
        <button data-action="play" class="primary">空格 · 播放/暂停</button>
        <button data-action="play-full">从 0.000 完整播放</button>
        <button data-action="loop">R · 循环候选附近</button>
        <button data-action="set-contact">在播放头设为击球点</button>
        <button data-action="reset-contact">恢复建议点</button>
      </div>
      <div class="length-guide">
        <div class="length-metric" id="preMetric"><span>击球前长度</span><strong>—</strong></div>
        <div class="length-metric" id="postMetric"><span>击球后长度</span><strong>—</strong></div>
        <div class="length-metric" id="ruleMetric"><span>当前长度标准</span><strong>—</strong></div>
      </div>
    </section>`;
}

function triField(field) {
  const [label, help] = TRI_LABELS[field];
  return `
    <div class="tri-field">
      <div><strong>${label}</strong><small>${help}</small></div>
      <div class="tri-options" role="group" aria-label="${label}">
        ${["Y", "N", "U"].map((value) => `
          <button type="button" data-tri-field="${field}" data-value="${value}">${value}</button>
        `).join("")}
      </div>
    </div>`;
}

function decisionPanel() {
  return `
    <section class="panel decision-panel">
      <div class="section-heading">
        <div>
          <span class="step">03</span>
          <div><p>按负责人文档填写全部字段</p><h2>校准记录</h2></div>
        </div>
        <span class="pill" id="currentConclusion">尚未审核</span>
      </div>
      <div class="calibration-body">
        <p class="owner-rule">I 必须选择错误代码；U 必须写明疑点。宁可 U，不要猜，也不要为了凑有效数量放宽标准。</p>
        <div class="reviewer-row">
          <label class="compact-field">
            <span>标注者姓名 / ID</span>
            <input id="reviewerId" maxlength="100" autocomplete="off" />
          </label>
          <label class="compact-field">
            <span>正确击球秒（约 0.05–0.10 秒精度）</span>
            <input id="contactTime" type="number" min="0" step="0.001" placeholder="无法确认时留空并选 U" />
          </label>
        </div>
        <div class="conclusion-grid">
          <button type="button" class="conclusion-button" data-conclusion="V">
            <strong>V · 有效</strong><small>快捷填入全部硬标准通过</small>
          </button>
          <button type="button" class="conclusion-button" data-conclusion="I">
            <strong>I · 无效</strong><small>至少一项硬标准失败，必须选代码</small>
          </button>
          <button type="button" class="conclusion-button" data-conclusion="U">
            <strong>U · 不确定</strong><small>无法可靠判断，必须写清疑点</small>
          </button>
        </div>
        <div class="tri-grid">
          ${Object.keys(TRI_LABELS).map(triField).join("")}
        </div>
        <div class="trajectory-row">
          <label class="compact-field">
            <span>远程原记录（只用于核对）</span>
            <div id="recordedTrajectoryForm" class="recorded-value">—</div>
          </label>
          <label class="compact-field">
            <span>人工观察轨迹</span>
            <select id="trajectory">
              <option value="">请选择</option>
              ${TRAJECTORIES.map((value) => `<option value="${value}">${value}</option>`).join("")}
            </select>
          </label>
        </div>
        <div class="error-heading">
          <span class="field-title">错误代码（可多选）</span>
          <p>只选实际观察到的；E11 必须写备注</p>
        </div>
        <div id="codeGrid" class="code-grid"></div>
        <label class="form-field notes-field">
          <span>备注 / 证据（最多 2000 字）</span>
          <textarea id="reviewNotes" maxlength="2000" rows="4" placeholder="写明你看到或听到的证据，不要只写“有问题”"></textarea>
        </label>
        <div class="save-row">
          <button type="button" class="danger-quiet" data-action="clear-review">清除本条已保存记录</button>
          <button type="button" class="primary" data-action="save">Ctrl+Enter · 保存并下一条</button>
        </div>
        <div class="navigation">
          <button data-action="previous">K · 上一条</button>
          <button data-action="skip">S · 跳过但不保存</button>
          <button data-action="next">J · 下一条</button>
        </div>
        <p id="message" class="message">${escapeHtml(state.message)}</p>
      </div>
    </section>`;
}

function queuePanel() {
  return `
    <section class="panel queue-panel">
      <div class="section-heading queue-heading">
        <div>
          <span class="step">04</span>
          <div><p>每页正好 20 条，对应负责人“每人20条”批次</p><h2>Flyball 候选队列</h2></div>
        </div>
        <span class="pill" id="queueRange">—</span>
      </div>
      <div class="queue-controls">
        <label>
          <span>显示</span>
          <select id="queueFilter">
            <option value="remaining">未审核</option>
            <option value="all">全部</option>
            <option value="reviewed">已审核</option>
            <option value="V">V 有效</option>
            <option value="I">I 无效</option>
            <option value="U">U 不确定</option>
          </select>
        </label>
        <label class="queue-search">
          <span>搜索样本 ID</span>
          <input id="queueSearch" type="search" placeholder="例如 F_0123" />
        </label>
        <div class="queue-pagination">
          <button data-action="queue-previous">上一页</button>
          <span id="queuePageText">第 1 页</span>
          <button data-action="queue-next">下一页</button>
        </div>
      </div>
      <div id="queueList" class="queue-list"></div>
      <p id="emptyQueue" class="empty-queue" hidden>当前筛选条件下没有样本。</p>
    </section>`;
}

function progressPanel() {
  return `
    <section class="panel">
      <div class="section-heading">
        <div><span class="step">05</span><div><p>结果与源媒体分开保存</p><h2>保存状态与文档口径</h2></div></div>
        <span class="pill">单人 · CSV · 原子更新</span>
      </div>
      <div class="save-explainer">
        <p>每个样本只保留一条当前记录；返回修改会替换原行，不会改动 video.mp4、audio.wav、sample.csv 或 label.txt。</p>
        <code id="resultsPath">—</code>
      </div>
      <div class="summary-grid">
        <div><span>总候选</span><strong id="summaryTotal">—</strong></div>
        <div><span>已审核</span><strong id="summaryReviewed">0</strong></div>
        <div><span>剩余</span><strong id="summaryRemaining">—</strong></div>
        <div><span>V 有效</span><strong id="summaryV">0</strong></div>
        <div><span>I 无效</span><strong id="summaryI">0</strong></div>
        <div><span>U 不确定</span><strong id="summaryU">0</strong></div>
      </div>
      <div class="contract-summary">
        <div><strong>fly / pop_fly</strong><span>击球前 ≥1 秒，击球后 ≥10 秒</span></div>
        <div><strong>line_drive</strong><span>击球前 ≥0.8 秒，击球后 ≥4 秒</span></div>
        <div><strong>时间口径</strong><span>从当前 sample 的 video.mp4 起点 0.000 秒计算</span></div>
      </div>
    </section>`;
}

function renderShell() {
  document.querySelector("#app").innerHTML = `
    ${topBar()}
    <main class="workbench-layout">
      <div class="media-column">${videoPanel()}${waveformPanel()}</div>
      <div class="decision-column">${decisionPanel()}</div>
      <div class="lower-column">${queuePanel()}${progressPanel()}</div>
    </main>
    <dialog id="troubleshootingDialog">
      <div class="dialog-heading"><h2>文件与哈希信息</h2><button data-action="close-dialog">关闭</button></div>
      <pre id="troubleshootingDump"></pre>
    </dialog>`;
  bindControls();
}

function bindControls() {
  document.addEventListener("click", (event) => {
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (action) handleAction(action);
    const conclusion = event.target.closest("[data-conclusion]")?.dataset.conclusion;
    if (conclusion) selectConclusion(conclusion);
    const triButton = event.target.closest("[data-tri-field]");
    if (triButton) {
      setTriValue(triButton.dataset.triField, triButton.dataset.value);
    }
  });
  document.querySelector("#reviewerId")?.addEventListener("input", (event) => {
    state.draft.reviewer_id = event.target.value;
    localStorage.setItem("flyballCalibrationReviewerId", event.target.value.trim());
  });
  document.querySelector("#contactTime")?.addEventListener("input", (event) => {
    const value = Number(event.target.value);
    state.draft.contact_time = event.target.value === "" || !Number.isFinite(value)
      ? null
      : value;
    addContactRegion(state.draft.contact_time);
    renderLengthGuide();
    renderState();
  });
  document.querySelector("#trajectory")?.addEventListener("change", (event) => {
    state.draft.trajectory = event.target.value;
    renderLengthGuide();
  });
  document.querySelector("#reviewNotes")?.addEventListener("input", (event) => {
    state.draft.notes = event.target.value;
  });
  document.querySelector("#queueFilter")?.addEventListener("change", (event) => {
    state.queueFilter = event.target.value;
    state.queuePage = 0;
    renderQueue();
  });
  document.querySelector("#queueSearch")?.addEventListener("input", (event) => {
    state.queueSearch = event.target.value.trim().toUpperCase();
    state.queuePage = 0;
    renderQueue();
  });
}

function renderCodeGrid() {
  const grid = document.querySelector("#codeGrid");
  if (!grid) return;
  grid.innerHTML = Object.entries(state.errorCodes).map(([code, item]) => `
    <label class="code-option ${state.draft.error_codes.has(code) ? "selected" : ""}">
      <input type="checkbox" value="${code}" ${state.draft.error_codes.has(code) ? "checked" : ""} />
      <span><strong>${code} · ${escapeHtml(item.name)}</strong><small>${escapeHtml(item.description)}</small></span>
    </label>
  `).join("");
  grid.querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) state.draft.error_codes.add(input.value);
      else state.draft.error_codes.delete(input.value);
      renderCodeGrid();
    });
  });
}

function selectConclusion(conclusion) {
  state.draft.conclusion = conclusion;
  if (conclusion === "V") {
    state.draft.original_time_correct = "Y";
    state.draft.sound = "Y";
    state.draft.picture = "Y";
    state.draft.full_process = "Y";
    state.draft.replay = "N";
    state.draft.error_codes.clear();
    if (!state.draft.trajectory && TRAJECTORIES.includes(state.sample?.recorded_trajectory)) {
      state.draft.trajectory = state.sample.recorded_trajectory;
    }
    state.message = "已按 V 有效填入全部硬标准通过；请确认轨迹和 contact_time 后保存。";
  } else if (conclusion === "U") {
    Object.keys(TRI_LABELS).forEach((field) => {
      if (!state.draft[field]) state.draft[field] = "U";
    });
    if (!state.draft.trajectory) state.draft.trajectory = "unknown";
    state.message = "U 不确定必须在备注里写明具体疑点。";
  } else {
    state.message = "I 无效：逐项填写，并选择所有适用的 E01–E11。";
  }
  renderState();
}

function setTriValue(field, value) {
  state.draft[field] = value;
  const automaticCode = {
    original_time_correct: value === "N" ? "E02" : null,
    sound: value === "N" ? "E01" : null,
    picture: value === "N" ? "E03" : null,
    replay: value === "Y" ? "E06" : null,
  }[field];
  if (automaticCode) state.draft.error_codes.add(automaticCode);
  if (field === "full_process" && value === "N") {
    state.message = "全过程为 N：请根据是开头过短还是结尾过短，选择 E04、E05 或两者。";
  }
  renderState();
}

function filteredSamples() {
  return state.samples.filter((sample) => {
    if (state.queueSearch && !sample.sample_id.includes(state.queueSearch)) return false;
    if (state.queueFilter === "remaining") return !sample.conclusion;
    if (state.queueFilter === "reviewed") return Boolean(sample.conclusion);
    if (["V", "I", "U"].includes(state.queueFilter)) {
      return sample.conclusion === state.queueFilter;
    }
    return true;
  });
}

function renderQueue() {
  const samples = filteredSamples();
  const pageCount = Math.max(1, Math.ceil(samples.length / PAGE_SIZE));
  state.queuePage = Math.min(state.queuePage, pageCount - 1);
  const start = state.queuePage * PAGE_SIZE;
  const page = samples.slice(start, start + PAGE_SIZE);
  const list = document.querySelector("#queueList");
  if (!list) return;
  list.innerHTML = page.map((sample) => {
    const index = state.samples.findIndex((item) => item.audit_id === sample.audit_id);
    return `
      <button class="queue-item ${index === state.index ? "active" : ""} ${sample.conclusion ? `status-${sample.conclusion}` : ""}" data-queue-index="${index}">
        <span>${sample.position}</span>
        <strong>${sample.sample_id}</strong>
        <em>${sample.conclusion ? `${conclusionLabel(sample.conclusion)}${sample.error_codes ? ` · ${sample.error_codes}` : ""}` : `批次 ${sample.batch_number} · 未审核`}</em>
      </button>`;
  }).join("");
  list.querySelectorAll("[data-queue-index]").forEach((button) => {
    button.addEventListener("click", () => goTo(Number(button.dataset.queueIndex)));
  });
  const empty = document.querySelector("#emptyQueue");
  if (empty) empty.hidden = page.length > 0;
  const range = document.querySelector("#queueRange");
  if (range) range.textContent = page.length
    ? `${start + 1}–${start + page.length} / ${samples.length}`
    : `0 / ${samples.length}`;
  const pageText = document.querySelector("#queuePageText");
  if (pageText) pageText.textContent = `第 ${state.queuePage + 1} / ${pageCount} 页`;
}

async function loadSample(notice = "") {
  const token = ++state.loadToken;
  destroyMedia();
  state.message = "正在载入样本……";
  state.sample = null;
  state.videoDuration = null;
  state.fullPlaybackCount = 0;
  state.drift = { currentMs: null, maxAbsMs: 0, corrections: 0, frames: 0 };
  renderState();
  const queueItem = state.samples[state.index];
  if (!queueItem) return;
  const sample = await fetchJson(`/api/sample/${encodeURIComponent(queueItem.audit_id)}`);
  if (token !== state.loadToken) return;
  state.sample = sample;
  const review = sample.review;
  state.draft = {
    reviewer_id: review?.reviewer_id
      || localStorage.getItem("flyballCalibrationReviewerId")
      || configuredReviewerId,
    conclusion: review?.conclusion || "",
    original_time_correct: review?.original_time_correct || "",
    contact_time: Number.isFinite(review?.contact_time)
      ? review.contact_time
      : sample.proposed_contact_time,
    sound: review?.sound || "",
    picture: review?.picture || "",
    full_process: review?.full_process || "",
    replay: review?.replay || "",
    trajectory: review?.trajectory || "",
    error_codes: new Set(
      String(review?.error_codes || "").split(";").filter(Boolean),
    ),
    notes: review?.notes || "",
  };
  setupVideo(sample, token);
  setupWaveform(sample, token);
  state.message = notice || (
    review
      ? `已读取 ${sample.sample_id} 的保存记录：${conclusionLabel(review.conclusion)}。修改后重新保存即可覆盖本条。`
      : "请先用耳机完整播放两遍，再按负责人标准填写。"
  );
  renderCodeGrid();
  renderState();
}

function setupVideo(sample, token) {
  const video = document.querySelector("#reviewVideo");
  const placeholder = document.querySelector("#videoPlaceholder");
  if (!video || !placeholder) return;
  video.muted = true;
  video.volume = 0;
  video.addEventListener("volumechange", () => {
    video.muted = true;
    video.volume = 0;
  });
  video.addEventListener("loadedmetadata", () => {
    if (token !== state.loadToken) return;
    state.videoDuration = video.duration;
    renderLengthGuide();
  });
  if (!sample.video_url) {
    video.hidden = true;
    placeholder.hidden = false;
    return;
  }
  placeholder.hidden = true;
  video.hidden = false;
  video.src = sample.video_url;
  video.load();
  monitorVideoFrames(video, token);
}

function setupWaveform(sample, token) {
  const container = document.querySelector("#waveform");
  if (!container || !sample.audio_url) {
    state.message = "audio.wav 缺失；应判 I 并选择 E09。";
    return;
  }
  const regions = RegionsPlugin.create();
  const wavesurfer = WaveSurfer.create({
    container,
    url: sample.audio_url,
    height: 118,
    waveColor: "#9aadb8",
    progressColor: "#3f7188",
    cursorColor: "#a9652a",
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
    document.querySelector("#waveLoading")?.setAttribute("hidden", "");
    addRegions(sample, duration);
    wavesurfer.setTime(0);
    syncVideo(true);
    renderState();
  });
  wavesurfer.on("error", (error) => {
    state.message = `音频加载失败：${error?.message ?? error}；应检查 E09。`;
    renderState();
  });
  wavesurfer.on("play", () => followAudioPlay(token));
  wavesurfer.on("pause", () => document.querySelector("#reviewVideo")?.pause());
  wavesurfer.on("seeking", () => syncVideo(true));
  wavesurfer.on("interaction", () => syncVideo(true));
  wavesurfer.on("finish", () => {
    state.fullPlaybackCount = Math.min(2, state.fullPlaybackCount + 1);
    renderState();
  });
  wavesurfer.on("timeupdate", (current) => {
    const currentLabel = document.querySelector("#currentTime");
    if (currentLabel) currentLabel.textContent = formatTime(current);
    enforceLoop(current);
    syncVideo(false);
  });
  regions.on("region-updated", (region) => {
    if (region.id !== "contact-point") return;
    state.draft.contact_time = region.start;
    state.message = `contact_time 已移到 ${formatTime(region.start)}。`;
    renderState();
  });
}

function addRegions(sample, duration) {
  if (
    Number.isFinite(sample.event_start)
    && Number.isFinite(sample.event_end)
    && sample.event_end > sample.event_start
  ) {
    state.regions.addRegion({
      id: "candidate-interval",
      start: Math.max(0, Math.min(duration, sample.event_start)),
      end: Math.max(0, Math.min(duration, sample.event_end)),
      color: "rgba(73, 124, 149, 0.18)",
      drag: false,
      resize: false,
      content: "原范围",
    });
  }
  addContactRegion(state.draft.contact_time, duration);
}

function addContactRegion(time, duration = state.wavesurfer?.getDuration() ?? 0) {
  if (state.contactRegion) {
    state.contactRegion.remove();
    state.contactRegion = null;
  }
  if (!Number.isFinite(time) || !state.regions || duration <= 0) return;
  state.contactRegion = state.regions.addRegion({
    id: "contact-point",
    start: Math.max(0, Math.min(duration, time)),
    color: "#ad6a2e",
    drag: true,
    resize: false,
    content: "击球点",
  });
}

async function followAudioPlay(token) {
  if (token !== state.loadToken) return;
  const video = document.querySelector("#reviewVideo");
  if (!video || video.hidden || !video.src) return;
  video.muted = true;
  video.volume = 0;
  syncVideo(true);
  try {
    await video.play();
  } catch {
    state.message = "视频跟随播放被浏览器暂时阻止；再按一次播放即可。";
    renderState();
  }
}

function syncVideo(force) {
  const video = document.querySelector("#reviewVideo");
  const wavesurfer = state.wavesurfer;
  if (!video || video.hidden || !video.src || !wavesurfer || video.readyState < 1) return;
  const audioTime = wavesurfer.getCurrentTime();
  const driftSeconds = video.currentTime - audioTime;
  state.drift.currentMs = driftSeconds * 1000;
  state.drift.maxAbsMs = Math.max(state.drift.maxAbsMs, Math.abs(state.drift.currentMs));
  if (force || Math.abs(driftSeconds) > 0.05) {
    video.currentTime = Math.max(0, Math.min(video.duration || audioTime, audioTime));
    state.drift.corrections += 1;
  }
  if (wavesurfer.isPlaying() && video.paused) video.play().catch(() => {});
  if (!wavesurfer.isPlaying() && !video.paused) video.pause();
  updateSyncMetric();
}

function monitorVideoFrames(video, token) {
  if (!("requestVideoFrameCallback" in video)) return;
  const callback = () => {
    if (token !== state.loadToken || video.hidden) return;
    state.drift.frames += 1;
    syncVideo(false);
    state.videoFrameRequest = video.requestVideoFrameCallback(callback);
  };
  state.videoFrameRequest = video.requestVideoFrameCallback(callback);
}

function updateSyncMetric() {
  const metric = document.querySelector("#syncMetric");
  if (!metric) return;
  metric.textContent = Number.isFinite(state.drift.currentMs)
    ? `A/V 漂移：${state.drift.currentMs.toFixed(1)} ms · 已校正 ${state.drift.corrections} 次`
    : "A/V 漂移：—";
}

function enforceLoop(current) {
  if (!state.loopCandidate || !state.sample || !state.wavesurfer) return;
  const start = state.sample.event_start;
  const end = state.sample.event_end;
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
  if (current > Math.min(state.wavesurfer.getDuration(), end + 0.4)) {
    state.wavesurfer.setTime(Math.max(0, start - 0.4));
  }
}

function validateDraft() {
  if (!state.draft.reviewer_id.trim()) return "请填写标注者姓名或 ID。";
  if (!["V", "I", "U"].includes(state.draft.conclusion)) return "请选择 V、I 或 U。";
  for (const [field, [label]] of Object.entries(TRI_LABELS)) {
    if (!["Y", "N", "U"].includes(state.draft[field])) return `${label}必须填写 Y、N 或 U。`;
  }
  if (!TRAJECTORIES.includes(state.draft.trajectory)) return "请选择人工观察轨迹。";
  if (state.draft.conclusion === "I" && state.draft.error_codes.size === 0) {
    return "I 无效必须选择至少一个错误代码。";
  }
  if (state.draft.conclusion === "U" && !state.draft.notes.trim()) {
    return "U 不确定必须在备注中写明疑点。";
  }
  if (state.draft.error_codes.has("E11") && !state.draft.notes.trim()) {
    return "E11 其他问题必须在备注中写清楚。";
  }
  if (state.draft.conclusion === "V" && !Number.isFinite(state.draft.contact_time)) {
    return "V 有效必须填写正确击球秒。";
  }
  return "";
}

async function saveReview() {
  if (!state.sample || state.saving) return;
  const validation = validateDraft();
  if (validation) {
    state.message = validation;
    renderState();
    return;
  }
  state.saving = true;
  state.message = "正在原子保存本条校准记录……";
  renderState();
  try {
    const payload = await fetchJson(`/api/review/${encodeURIComponent(state.sample.audit_id)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...state.draft,
        reviewer_id: state.draft.reviewer_id.trim(),
        error_codes: [...state.draft.error_codes],
        notes: state.draft.notes.trim(),
      }),
    });
    const queueItem = state.samples[state.index];
    queueItem.conclusion = payload.review.conclusion;
    queueItem.error_codes = payload.review.error_codes;
    state.sample.review = payload.review;
    state.summary = payload.summary;
    renderQueue();
    renderState();
    const next = findNextUnreviewed(state.index);
    if (next === null) {
      state.message = "全部候选都已有记录。可以筛选 I/U 或已审核样本继续复查。";
      renderState();
    } else {
      await goTo(next, `已保存 ${queueItem.sample_id}：${conclusionLabel(payload.review.conclusion)}。`);
    }
  } catch (error) {
    state.message = `保存失败：${error.message}`;
    renderState();
  } finally {
    state.saving = false;
    renderState();
  }
}

function findNextUnreviewed(current) {
  for (let index = current + 1; index < state.samples.length; index += 1) {
    if (!state.samples[index].conclusion) return index;
  }
  for (let index = 0; index <= current; index += 1) {
    if (!state.samples[index].conclusion) return index;
  }
  return null;
}

async function clearReview() {
  if (!state.sample?.review || state.saving) {
    state.message = "当前样本没有已保存记录。";
    renderState();
    return;
  }
  if (!window.confirm("清除这条样本的已保存记录？源数据不会受影响。")) return;
  state.saving = true;
  try {
    const payload = await fetchJson(`/api/review/${encodeURIComponent(state.sample.audit_id)}`, {
      method: "DELETE",
    });
    state.samples[state.index].conclusion = null;
    state.samples[state.index].error_codes = "";
    state.summary = payload.summary;
    await loadSample("本条保存记录已清除，重新变为未审核。");
    renderQueue();
  } catch (error) {
    state.message = `清除失败：${error.message}`;
  } finally {
    state.saving = false;
    renderState();
  }
}

async function goTo(index, notice = "") {
  if (!state.samples.length) return;
  state.index = Math.max(0, Math.min(state.samples.length - 1, index));
  await loadSample(notice);
  renderQueue();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function handleAction(action) {
  if (action === "play") {
    state.wavesurfer?.playPause();
  } else if (action === "play-full") {
    state.wavesurfer?.setTime(0);
    state.wavesurfer?.play();
  } else if (action === "loop") {
    state.loopCandidate = !state.loopCandidate;
    if (state.loopCandidate && state.sample && state.wavesurfer) {
      state.wavesurfer.setTime(Math.max(0, (state.sample.event_start ?? 0) - 0.4));
      state.wavesurfer.play();
    }
    state.message = state.loopCandidate ? "候选附近循环已开启。" : "候选附近循环已关闭。";
  } else if (action === "set-contact") {
    if (state.wavesurfer) {
      state.draft.contact_time = state.wavesurfer.getCurrentTime();
      addContactRegion(state.draft.contact_time);
      state.message = `contact_time 已设置为 ${formatTime(state.draft.contact_time)}。`;
    }
  } else if (action === "reset-contact") {
    state.draft.contact_time = state.sample?.proposed_contact_time ?? null;
    addContactRegion(state.draft.contact_time);
    state.message = "已恢复批量建议点。";
  } else if (action === "save") {
    await saveReview();
  } else if (action === "previous") {
    await goTo(state.index - 1);
  } else if (action === "next" || action === "skip") {
    await goTo(state.index + 1, action === "skip" ? "已跳过；没有保存任何记录。" : "");
  } else if (action === "queue-previous") {
    state.queuePage = Math.max(0, state.queuePage - 1);
    renderQueue();
  } else if (action === "queue-next") {
    const pageCount = Math.max(1, Math.ceil(filteredSamples().length / PAGE_SIZE));
    state.queuePage = Math.min(pageCount - 1, state.queuePage + 1);
    renderQueue();
  } else if (action === "clear-review") {
    await clearReview();
  } else if (action === "close-dialog") {
    document.querySelector("#troubleshootingDialog")?.close();
  }
  renderState();
}

function renderLengthGuide() {
  const contact = state.draft.contact_time;
  const duration = state.videoDuration;
  const trajectory = state.draft.trajectory || state.sample?.recorded_trajectory;
  const lineDrive = trajectory === "line_drive";
  const preRequired = lineDrive ? 0.8 : 1.0;
  const postRequired = lineDrive ? 4.0 : 10.0;
  const pre = Number.isFinite(contact) ? contact : null;
  const post = Number.isFinite(contact) && Number.isFinite(duration)
    ? duration - contact
    : null;
  const metrics = [
    ["#preMetric", pre, preRequired, `要求 ≥ ${preRequired.toFixed(1)} s`],
    ["#postMetric", post, postRequired, `要求 ≥ ${postRequired.toFixed(1)} s`],
  ];
  metrics.forEach(([selector, value, required, suffix]) => {
    const element = document.querySelector(selector);
    if (!element) return;
    element.classList.remove("pass", "fail");
    const strong = element.querySelector("strong");
    if (strong) strong.textContent = Number.isFinite(value)
      ? `${value.toFixed(3)} s · ${suffix}`
      : `— · ${suffix}`;
    if (Number.isFinite(value)) element.classList.add(value >= required ? "pass" : "fail");
  });
  const rule = document.querySelector("#ruleMetric strong");
  if (rule) rule.textContent = lineDrive
    ? "line_drive：前 0.8 / 后 4 秒"
    : "fly / pop_fly：前 1 / 后 10 秒";
}

function renderSummary() {
  if (!state.summary) return;
  const counts = state.summary.conclusion_counts;
  const values = {
    reviewedCount: state.summary.reviewed,
    remainingCount: state.summary.remaining,
    summaryTotal: state.summary.total,
    summaryReviewed: state.summary.reviewed,
    summaryRemaining: state.summary.remaining,
    summaryV: counts.V,
    summaryI: counts.I,
    summaryU: counts.U,
  };
  Object.entries(values).forEach(([id, value]) => {
    const element = document.querySelector(`#${id}`);
    if (element) element.textContent = String(value);
  });
}

function renderState() {
  document.body.classList.toggle("saving", state.saving);
  document.querySelectorAll("button, select, textarea, input").forEach((element) => {
    if (element.dataset.action === "close-dialog") return;
    if (state.saving) element.setAttribute("disabled", "");
    else element.removeAttribute("disabled");
  });
  const message = document.querySelector("#message");
  if (message) message.textContent = state.message;
  const progress = document.querySelector("#progressText");
  if (progress) progress.textContent = state.sample
    ? `${state.sample.sample_id} · ${state.sample.position} / ${state.sample.total} · 批次 ${state.sample.batch_number}`
    : "样本 — / —";
  const simpleText = {
    sampleIdHeading: state.sample?.sample_id ?? "—",
    recordedTrajectory: state.sample?.recorded_trajectory || "—",
    recordedTrajectoryForm: state.sample?.recorded_trajectory || "—",
    landingZone: state.sample?.landing_zone || "—",
    strength: state.sample?.strength || "—",
    playbackCount: `${state.fullPlaybackCount} / 2`,
    resultsPath: state.resultsRelpath || "—",
  };
  Object.entries(simpleText).forEach(([id, value]) => {
    const element = document.querySelector(`#${id}`);
    if (element) element.textContent = value;
  });
  const videoState = document.querySelector("#videoState");
  if (videoState) videoState.textContent = state.sample?.video_state === "ready_local"
    ? "视频已准备"
    : "视频缺失";
  const interval = document.querySelector("#intervalText");
  if (interval) interval.textContent = state.sample
    ? `原范围：${formatTime(state.sample.event_start)} → ${formatTime(state.sample.event_end)}`
    : "原范围：—";
  const proposal = document.querySelector("#proposalText");
  if (proposal) proposal.textContent = `建议点：${formatTime(state.sample?.proposed_contact_time)}`;
  const contactState = document.querySelector("#contactState");
  if (contactState) {
    contactState.textContent = `contact_time：${formatTime(state.draft.contact_time)}`;
    contactState.classList.toggle(
      "changed",
      Number.isFinite(state.draft.contact_time)
        && Number.isFinite(state.sample?.proposed_contact_time)
        && Math.abs(state.draft.contact_time - state.sample.proposed_contact_time) > 0.001,
    );
  }
  const conclusion = document.querySelector("#currentConclusion");
  if (conclusion) conclusion.textContent = state.sample?.review
    ? `已保存：${conclusionLabel(state.sample.review.conclusion)}`
    : "尚未审核";
  document.querySelectorAll("[data-conclusion]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.conclusion === state.draft.conclusion);
  });
  document.querySelectorAll("[data-tri-field]").forEach((button) => {
    button.classList.toggle(
      "selected",
      state.draft[button.dataset.triField] === button.dataset.value,
    );
  });
  const reviewer = document.querySelector("#reviewerId");
  if (reviewer && reviewer.value !== state.draft.reviewer_id) reviewer.value = state.draft.reviewer_id;
  const contactInput = document.querySelector("#contactTime");
  const contactValue = Number.isFinite(state.draft.contact_time)
    ? state.draft.contact_time.toFixed(3)
    : "";
  if (contactInput && contactInput.value !== contactValue) contactInput.value = contactValue;
  const trajectory = document.querySelector("#trajectory");
  if (trajectory && trajectory.value !== state.draft.trajectory) trajectory.value = state.draft.trajectory;
  const notes = document.querySelector("#reviewNotes");
  if (notes && notes.value !== state.draft.notes) notes.value = state.draft.notes;
  renderCodeGrid();
  renderLengthGuide();
  renderSummary();
  updateSyncMetric();
}

function destroyMedia() {
  const video = document.querySelector("#reviewVideo");
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
  state.contactRegion = null;
}

function isTypingTarget(target) {
  return target instanceof HTMLInputElement
    || target instanceof HTMLTextAreaElement
    || target instanceof HTMLSelectElement
    || target?.isContentEditable;
}

function bindKeyboard() {
  window.addEventListener("keydown", (event) => {
    if (state.saving) return;
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      saveReview();
      return;
    }
    if (isTypingTarget(event.target)) return;
    if (event.key === " ") {
      event.preventDefault();
      handleAction("play");
    } else if (event.key.toLowerCase() === "v") selectConclusion("V");
    else if (event.key.toLowerCase() === "i") selectConclusion("I");
    else if (event.key.toLowerCase() === "u") selectConclusion("U");
    else if (event.key.toLowerCase() === "j") handleAction("next");
    else if (event.key.toLowerCase() === "k") handleAction("previous");
    else if (event.key.toLowerCase() === "s") handleAction("skip");
    else if (event.key.toLowerCase() === "r") handleAction("loop");
  });
}

function showFatal(error) {
  state.message = `Flyball 工作台加载失败：${error?.message ?? error}`;
  renderState();
  console.error(error);
}

async function init() {
  renderShell();
  bindKeyboard();
  const payload = await fetchJson("/api/workbench");
  if (!payload.formal_workbench || payload.workbench_kind !== "flyball_calibration") {
    throw new Error("服务器不是 Flyball 校准工作台");
  }
  state.samples = payload.samples;
  state.summary = payload.summary;
  state.manifestSummary = payload.manifest_summary;
  state.errorCodes = payload.error_codes;
  state.resultsRelpath = payload.results_relpath;
  state.defaultReviewerId = payload.default_reviewer_id || "";
  configuredReviewerId = state.defaultReviewerId;
  localStorage.setItem("flyballCalibrationReviewerId", state.defaultReviewerId);
  if (!state.samples.length) throw new Error("Flyball 候选队列为空");
  const firstUnreviewed = state.samples.findIndex((sample) => !sample.conclusion);
  state.index = firstUnreviewed >= 0 ? firstUnreviewed : 0;
  renderQueue();
  renderSummary();
  await loadSample(
    payload.summary.reviewed
      ? `已恢复 ${payload.summary.reviewed} 条保存结果，从第一条未审核样本继续。`
      : "结果会在“保存并下一条”时原子写入独立 CSV。",
  );
}


init().catch(showFatal);
