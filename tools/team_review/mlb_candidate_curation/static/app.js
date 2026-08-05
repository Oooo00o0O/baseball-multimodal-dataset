import WaveSurfer from "/static/vendor/wavesurfer-7.12.11/wavesurfer.esm.js";
import RegionsPlugin from "/static/vendor/wavesurfer-7.12.11/regions.esm.js";


const PAGE_SIZE = 20;
const TRAJECTORY_KEYS = {
  g: "ground_ball",
  f: "fly_ball",
  l: "line_drive",
  p: "pop_fly",
  u: "unknown",
};
const state = {
  samples: [],
  sample: null,
  index: 0,
  summary: null,
  trajectoryLabels: {},
  exclusionLabels: {},
  resultsPath: "",
  draft: emptyDraft(),
  wavesurfer: null,
  regions: null,
  targetRegion: null,
  loadToken: 0,
  saving: false,
  audioMode: "original",
  filter: "all",
  search: "",
  queuePage: 0,
  message: "正在读取审核队列……",
  messageError: false,
};

function emptyDraft() {
  return {
    admission_status: "",
    exclusion_reason: "",
    observed_trajectory: "",
    reviewed_location: "",
    reviewed_hit_time: null,
    broken_bat: false,
    reviewer_id: "",
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

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error ?? `${response.status} ${response.statusText}`);
  return payload;
}

function renderShell() {
  document.querySelector("#app").className = "";
  document.querySelector("#app").innerHTML = `
    <header class="topbar">
      <div class="brand">
        <h1>MLB 候选筛选台</h1>
        <span id="sampleTitle" class="sample-title">—</span>
      </div>
      <div class="top-actions">
        <span id="assignment" class="progress">—</span>
        <span id="progress" class="progress">—</span>
        <a class="download" href="/api/reviews/export" download>审核 CSV</a>
        <a class="download" href="/api/audit/export" download>合并审计 CSV</a>
        <a class="download" href="/api/team-bundle/export" download>团队结果包 ZIP</a>
      </div>
    </header>
    <main class="layout">
      <div class="media-column">
        <section class="panel">
          <div class="panel-head">
            <div><h2>静音视频</h2><p>视频始终静音；下方音频是唯一声音来源</p></div>
            <span id="mediaState" class="pill">—</span>
          </div>
          <div class="video-stage">
            <video id="video" muted playsinline preload="metadata"></video>
            <div id="videoPlaceholder" class="placeholder" hidden>视频没有准备好</div>
          </div>
          <div class="meta-grid">
            <div><span>MLB 原轨迹</span><strong id="rawTrajectory">—</strong></div>
            <div><span>MLB 原位置</span><strong id="rawLocation">—</strong></div>
            <div><span>局次</span><strong id="inning">—</strong></div>
            <div><span>媒体匹配</span><strong id="matchReason">—</strong></div>
          </div>
          <p id="description" class="description">—</p>
        </section>
        <section class="panel">
          <div class="panel-head">
            <div><h2>原始音频波形与击球点</h2><p>点波形、拖动橙线或选择候选点，都会修改同一个人工点</p></div>
            <span id="targetTime" class="pill">击球点：—</span>
          </div>
          <div class="wave-shell">
            <div id="waveform"></div>
            <div id="waveLoading" class="wave-loading">正在解码音频……</div>
          </div>
          <div class="time-row">
            <span id="currentTime">0.000 s</span>
            <span id="duration">总时长：—</span>
            <span id="detector">检测器：—</span>
          </div>
          <div id="candidateRow" class="candidate-row"></div>
          <div class="transport">
            <button data-action="play" class="primary">Space · 播放 / 暂停</button>
            <button data-action="mode">原始音频 / 击球增强</button>
            <button data-action="restore">R · 恢复第 1 候选</button>
          </div>
        </section>
      </div>
      <aside class="review-column">
        <section class="panel">
          <div class="panel-head">
            <div><h2>本条人工结论</h2><p>只有“保存并下一条”才会写 CSV</p></div>
            <span id="savedState" class="pill">未审核</span>
          </div>
          <div class="review-body">
            <div class="admission-grid">
              <button class="admit" data-admission="admitted"><strong>A · 合格收录</strong><small>有一次正常击球，轨迹可判断</small></button>
              <button class="exclude" data-admission="excluded"><strong>X · 不合格排除</strong><small>选择一个明确原因即可</small></button>
            </div>
            <div id="excludeFields" class="conditional">
              <label class="field"><span>不合格原因</span><select id="exclusionReason"></select></label>
            </div>
            <div id="admitFields" class="conditional">
              <div>
                <span class="field-label">人工轨迹（G / F / L / P / U）</span>
                <div id="trajectoryGrid" class="trajectory-grid"></div>
              </div>
              <div>
                <span class="field-label">人工 MLB 位置（数字键 1–9；不确定可选 unknown）</span>
                <div id="locationGrid" class="location-grid"></div>
              </div>
              <label class="check-row"><input id="brokenBat" type="checkbox" /> 明确发生断棒（不影响主结论，单独记录）</label>
            </div>
            <label class="field"><span>审核人（可空）</span><input id="reviewerId" maxlength="100" /></label>
            <label class="field"><span>备注（可空；只写真正有补充价值的内容）</span><textarea id="notes" maxlength="2000"></textarea></label>
            <div class="shortcut-note">
              Space 播放/暂停 · J 下一条 · K 上一条 · A 收录 · X 排除 ·
              G/F/L/P/U 轨迹 · 1–9 位置 · Q/W/E 候选点 · R 归位 · Ctrl+Enter 保存
            </div>
            <div class="save-row">
              <button data-action="clear" class="danger">清除本条记录</button>
              <button data-action="save" class="primary">Ctrl+Enter · 保存并下一条</button>
            </div>
            <div class="nav-row">
              <button data-action="previous">K · 上一条</button>
              <button data-action="next">J · 下一条</button>
            </div>
            <p id="message" class="message">—</p>
          </div>
        </section>
      </aside>
      <div class="lower">
        <section class="panel">
          <div class="panel-head">
            <div><h2>样本队列</h2><p>已审核样本保留在队列里，可随时返回修改</p></div>
            <span id="queueSummary" class="pill">—</span>
          </div>
          <div class="queue-tools">
            <select id="queueFilter">
              <option value="all">全部</option>
              <option value="remaining">未审核</option>
              <option value="reviewed">已审核</option>
              <option value="admitted">已收录</option>
              <option value="excluded">已排除</option>
            </select>
            <input id="queueSearch" type="search" placeholder="搜索击球手、日期或 source play ID" />
            <button data-action="queue-previous">队列上一页</button>
            <button data-action="queue-next">队列下一页</button>
          </div>
          <div id="queueList" class="queue-list"></div>
          <div id="emptyQueue" class="empty" hidden>当前筛选下没有样本。</div>
        </section>
      </div>
    </main>`;
  bindInputs();
}

function bindInputs() {
  document.addEventListener("click", (event) => {
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (action) handleAction(action);
    const admission = event.target.closest("[data-admission]")?.dataset.admission;
    if (admission) setAdmission(admission);
    const trajectory = event.target.closest("[data-trajectory]")?.dataset.trajectory;
    if (trajectory) setTrajectory(trajectory);
    const location = event.target.closest("[data-location]")?.dataset.location;
    if (location) setLocation(location);
    const candidate = event.target.closest("[data-candidate-rank]")?.dataset.candidateRank;
    if (candidate) chooseCandidate(Number(candidate));
    const queueId = event.target.closest("[data-queue-id]")?.dataset.queueId;
    if (queueId) {
      const index = state.samples.findIndex((item) => item.source_play_id === queueId);
      if (index >= 0) goTo(index);
    }
  });
  document.querySelector("#exclusionReason").addEventListener("change", (event) => {
    state.draft.exclusion_reason = event.target.value;
  });
  document.querySelector("#brokenBat").addEventListener("change", (event) => {
    state.draft.broken_bat = event.target.checked;
  });
  document.querySelector("#reviewerId").addEventListener("input", (event) => {
    state.draft.reviewer_id = event.target.value;
  });
  document.querySelector("#notes").addEventListener("input", (event) => {
    state.draft.notes = event.target.value;
  });
  document.querySelector("#queueFilter").addEventListener("change", (event) => {
    state.filter = event.target.value;
    state.queuePage = 0;
    renderQueue();
  });
  document.querySelector("#queueSearch").addEventListener("input", (event) => {
    state.search = event.target.value.trim().toLowerCase();
    state.queuePage = 0;
    renderQueue();
  });
}

function renderChoices() {
  document.querySelector("#exclusionReason").innerHTML = `
    <option value="">请选择一个明确原因</option>
    ${Object.entries(state.exclusionLabels).map(([value, label]) =>
      `<option value="${value}">${escapeHtml(label)}</option>`).join("")}`;
  document.querySelector("#trajectoryGrid").innerHTML = Object.entries(state.trajectoryLabels)
    .map(([value, label]) => `<button data-trajectory="${value}">${escapeHtml(label)}</button>`)
    .join("");
  document.querySelector("#locationGrid").innerHTML = [
    ...Array.from({ length: 9 }, (_, index) => String(index + 1)),
    "unknown",
  ].map((value) => `<button data-location="${value}">${value}</button>`).join("");
}

function setAdmission(value) {
  state.draft.admission_status = value;
  if (value === "admitted") {
    state.draft.exclusion_reason = "";
    if (!state.draft.reviewed_location && /^[1-9]$/.test(state.sample?.mlb_location_raw ?? "")) {
      state.draft.reviewed_location = state.sample.mlb_location_raw;
    }
    if (!state.draft.reviewed_hit_time) restoreProposal(false);
    state.message = "已选择合格收录；请确认轨迹、位置和击球点。";
  } else {
    state.message = "已选择不合格排除；只需选择一个明确原因，备注可以留空。";
  }
  state.messageError = false;
  renderState();
}

function setTrajectory(value) {
  state.draft.admission_status = "admitted";
  state.draft.observed_trajectory = value;
  renderState();
}

function setLocation(value) {
  state.draft.admission_status = "admitted";
  state.draft.reviewed_location = value;
  renderState();
}

function currentProposal() {
  return state.sample?.contact_candidates?.[0]?.time_sec ?? null;
}

function restoreProposal(withMessage = true) {
  state.draft.reviewed_hit_time = currentProposal();
  addTargetRegion(state.draft.reviewed_hit_time);
  if (withMessage) state.message = "已恢复为自动候选 1；尚未保存。";
  renderState();
}

function chooseCandidate(rank) {
  const candidate = state.sample?.contact_candidates?.find((item) => item.rank === rank);
  if (!candidate) return;
  state.draft.reviewed_hit_time = candidate.time_sec;
  addTargetRegion(candidate.time_sec);
  state.message = `已选择自动候选 ${rank}（${formatTime(candidate.time_sec)}）；尚未保存。`;
  renderState();
}

function setupVideo(sample) {
  const video = document.querySelector("#video");
  const placeholder = document.querySelector("#videoPlaceholder");
  video.pause();
  video.muted = true;
  video.volume = 0;
  if (!sample.video_url) {
    video.hidden = true;
    placeholder.hidden = false;
    video.removeAttribute("src");
    return;
  }
  placeholder.hidden = true;
  video.hidden = false;
  video.src = sample.video_url;
  video.load();
}

function setupWaveform(sample, token) {
  state.wavesurfer?.destroy();
  state.wavesurfer = null;
  state.regions = null;
  state.targetRegion = null;
  const audioUrl = state.audioMode === "enhanced"
    ? sample.enhanced_audio_url
    : sample.audio_url;
  const loading = document.querySelector("#waveLoading");
  loading.hidden = false;
  if (!audioUrl) {
    loading.textContent = "音频没有准备好";
    return;
  }
  const regions = RegionsPlugin.create();
  const wavesurfer = WaveSurfer.create({
    container: "#waveform",
    url: audioUrl,
    height: 116,
    waveColor: "#94aaa1",
    progressColor: "#34765f",
    cursorColor: "#a26018",
    cursorWidth: 2,
    normalize: true,
    dragToSeek: true,
    hideScrollbar: true,
    plugins: [regions],
  });
  state.wavesurfer = wavesurfer;
  state.regions = regions;
  wavesurfer.on("ready", () => {
    if (token !== state.loadToken) return;
    loading.hidden = true;
    addTargetRegion(state.draft.reviewed_hit_time);
    renderState();
  });
  wavesurfer.on("error", (error) => {
    state.message = `音频加载失败：${error?.message ?? error}`;
    state.messageError = true;
    renderState();
  });
  wavesurfer.on("play", () => followVideo());
  wavesurfer.on("pause", () => document.querySelector("#video")?.pause());
  wavesurfer.on("timeupdate", (time) => {
    document.querySelector("#currentTime").textContent = formatTime(time);
    syncVideo(false);
  });
  wavesurfer.on("seeking", () => syncVideo(true));
  wavesurfer.on("interaction", (time) => {
    if (!Number.isFinite(time)) return;
    state.draft.reviewed_hit_time = time;
    addTargetRegion(time);
    state.message = `人工击球点已移到 ${formatTime(time)}；尚未保存。`;
    renderState();
  });
  regions.on("region-updated", (region) => {
    if (region.id !== "review-target") return;
    state.draft.reviewed_hit_time = region.start;
    state.message = `人工击球点已拖到 ${formatTime(region.start)}；尚未保存。`;
    renderState();
  });
}

function addTargetRegion(time) {
  if (state.targetRegion) {
    state.targetRegion.remove();
    state.targetRegion = null;
  }
  const duration = state.wavesurfer?.getDuration() ?? 0;
  if (!Number.isFinite(time) || !state.regions || !duration) return;
  state.targetRegion = state.regions.addRegion({
    id: "review-target",
    start: Math.max(0, Math.min(duration, time)),
    color: "#a26018",
    drag: true,
    resize: false,
    content: "人工点",
  });
}

async function followVideo() {
  const video = document.querySelector("#video");
  if (!video || video.hidden || !video.src) return;
  video.muted = true;
  video.volume = 0;
  syncVideo(true);
  await video.play().catch(() => {});
}

function syncVideo(force) {
  const video = document.querySelector("#video");
  const audio = state.wavesurfer;
  if (!video || video.hidden || !audio || video.readyState < 1) return;
  const audioTime = audio.getCurrentTime();
  if (force || Math.abs(video.currentTime - audioTime) > 0.05) {
    video.currentTime = Math.max(0, Math.min(video.duration || audioTime, audioTime));
  }
  if (audio.isPlaying() && video.paused) video.play().catch(() => {});
  if (!audio.isPlaying() && !video.paused) video.pause();
}

function draftFromReview(sample) {
  const review = sample.review;
  if (!review) {
    const proposal = currentProposal();
    return {
      ...emptyDraft(),
      reviewed_location: /^[1-9]$/.test(sample.mlb_location_raw ?? "")
        ? sample.mlb_location_raw
        : "",
      reviewed_hit_time: proposal,
    };
  }
  return {
    admission_status: review.admission_status,
    exclusion_reason: review.exclusion_reason ?? "",
    observed_trajectory: review.observed_trajectory ?? "",
    reviewed_location: review.reviewed_location ?? "",
    reviewed_hit_time: review.reviewed_hit_time,
    broken_bat: Boolean(review.broken_bat),
    reviewer_id: review.reviewer_id ?? "",
    notes: review.notes ?? "",
  };
}

async function loadSample(notice = "") {
  const queueItem = state.samples[state.index];
  if (!queueItem) return;
  const token = ++state.loadToken;
  state.wavesurfer?.pause();
  const sample = await fetchJson(`/api/sample/${encodeURIComponent(queueItem.source_play_id)}`);
  if (token !== state.loadToken) return;
  state.sample = sample;
  state.audioMode = "original";
  state.draft = draftFromReview(sample);
  state.message = notice || (sample.review
    ? "已载入这条原有审核记录；修改后仍需再次明确保存。"
    : "先听声音和看画面，再决定收录或排除。");
  state.messageError = false;
  setupVideo(sample);
  setupWaveform(sample, token);
  renderState();
}

function filteredSamples() {
  return state.samples.filter((sample) => {
    if (state.filter === "remaining" && sample.review_status) return false;
    if (state.filter === "reviewed" && !sample.review_status) return false;
    if (state.filter === "admitted" && sample.review_status !== "admitted") return false;
    if (state.filter === "excluded" && sample.review_status !== "excluded") return false;
    if (!state.search) return true;
    const haystack = `${sample.source_play_id} ${sample.batter} ${sample.game_date}`.toLowerCase();
    return haystack.includes(state.search);
  });
}

function renderQueue() {
  const filtered = filteredSamples();
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  state.queuePage = Math.min(state.queuePage, pages - 1);
  const page = filtered.slice(state.queuePage * PAGE_SIZE, (state.queuePage + 1) * PAGE_SIZE);
  document.querySelector("#queueSummary").textContent =
    `${filtered.length} 条 · 第 ${state.queuePage + 1}/${pages} 页`;
  document.querySelector("#emptyQueue").hidden = page.length > 0;
  document.querySelector("#queueList").innerHTML = page.map((item) => {
    const classes = [
      "queue-item",
      item.source_play_id === state.sample?.source_play_id ? "current" : "",
      item.review_status ? "reviewed" : "",
      item.review_status === "excluded" ? "excluded" : "",
    ].filter(Boolean).join(" ");
    const status = item.review_status === "admitted"
      ? `已收录 · ${state.trajectoryLabels[item.reviewed_trajectory] ?? item.reviewed_trajectory}`
      : item.review_status === "excluded" ? "已排除" : "未审核";
    return `<button class="${classes}" data-queue-id="${escapeHtml(item.source_play_id)}">
      <strong>${escapeHtml(item.batter || item.source_play_id)}</strong>
      <small>${escapeHtml(item.game_date)} · ${escapeHtml(status)}</small>
      <small>${escapeHtml(item.source_play_id)}</small>
    </button>`;
  }).join("");
}

function renderCandidates() {
  const row = document.querySelector("#candidateRow");
  const keys = ["Q", "W", "E"];
  if (!state.sample?.contact_candidates?.length) {
    row.innerHTML = "<span class='progress'>没有可靠自动候选，可直接点波形设置</span>";
    return;
  }
  row.innerHTML = state.sample.contact_candidates.map((candidate, index) => {
    const active = Number.isFinite(state.draft.reviewed_hit_time)
      && Math.abs(state.draft.reviewed_hit_time - candidate.time_sec) <= 0.001;
    return `<button class="${active ? "active" : ""}" data-candidate-rank="${candidate.rank}">
      <strong>${keys[index]} · 候选 ${candidate.rank} · ${formatTime(candidate.time_sec)}</strong>
      <small>相对分数 ${Number(candidate.score).toFixed(3)}</small>
    </button>`;
  }).join("");
}

function renderState() {
  const sample = state.sample;
  document.body.classList.toggle("saving", state.saving);
  document.querySelectorAll("button, input, select, textarea").forEach((element) => {
    if (state.saving) element.disabled = true;
    else element.disabled = false;
  });
  document.querySelector("#sampleTitle").textContent = sample
    ? `${sample.batter || "未知击球手"} · ${sample.game_date || ""}`
    : "—";
  document.querySelector("#progress").textContent = sample
    ? `${sample.position}/${sample.total} · 已审核 ${state.summary?.reviewed ?? 0}`
    : "—";
  document.querySelector("#mediaState").textContent = sample?.media_ready ? "媒体已准备" : "媒体缺失";
  document.querySelector("#rawTrajectory").textContent =
    state.trajectoryLabels[sample?.mlb_trajectory_raw]
      ?? (sample?.mlb_trajectory_raw === "popup" ? "高飞球（MLB popup）" : sample?.mlb_trajectory_raw)
      ?? "—";
  document.querySelector("#rawLocation").textContent = sample?.mlb_location_raw || "缺失";
  document.querySelector("#inning").textContent = sample
    ? `${sample.half_inning || ""} ${sample.inning || "—"}`
    : "—";
  document.querySelector("#matchReason").textContent = sample?.media_match_reason_zh || "—";
  document.querySelector("#description").textContent = sample?.play_description || "—";
  document.querySelector("#duration").textContent = `总时长：${formatTime(sample?.media_duration_sec)}`;
  document.querySelector("#detector").textContent = `检测器：${sample?.detector_version || "—"}`;
  document.querySelector("#targetTime").textContent =
    `击球点：${formatTime(state.draft.reviewed_hit_time)}`;
  document.querySelector("#savedState").textContent = sample?.review
    ? `已保存：${sample.review.admission_status === "admitted" ? "收录" : "排除"}`
    : "未审核";
  document.querySelectorAll("[data-admission]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.admission === state.draft.admission_status);
  });
  document.querySelector("#excludeFields").classList.toggle(
    "visible", state.draft.admission_status === "excluded",
  );
  document.querySelector("#admitFields").classList.toggle(
    "visible", state.draft.admission_status === "admitted",
  );
  document.querySelector("#exclusionReason").value = state.draft.exclusion_reason;
  document.querySelectorAll("[data-trajectory]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.trajectory === state.draft.observed_trajectory);
  });
  document.querySelectorAll("[data-location]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.location === state.draft.reviewed_location);
  });
  document.querySelector("#brokenBat").checked = state.draft.broken_bat;
  document.querySelector("#reviewerId").value = state.draft.reviewer_id;
  document.querySelector("#notes").value = state.draft.notes;
  const message = document.querySelector("#message");
  message.textContent = state.message;
  message.classList.toggle("error", state.messageError);
  renderCandidates();
  renderQueue();
}

function validateDraft() {
  if (!["admitted", "excluded"].includes(state.draft.admission_status)) {
    return "请选择“合格收录”或“不合格排除”。";
  }
  if (state.draft.admission_status === "excluded") {
    if (!state.draft.exclusion_reason) return "不合格样本必须选择一个明确原因。";
    return "";
  }
  if (!Object.hasOwn(state.trajectoryLabels, state.draft.observed_trajectory)) {
    return "合格样本必须选择人工轨迹。";
  }
  if (!/^[1-9]$/.test(state.draft.reviewed_location) && state.draft.reviewed_location !== "unknown") {
    return "合格样本必须确认 MLB 位置 1–9，或选择 unknown。";
  }
  if (!Number.isFinite(state.draft.reviewed_hit_time)) {
    return "合格样本必须确认一个击球点。";
  }
  return "";
}

async function saveReview() {
  if (!state.sample || state.saving) return;
  const validation = validateDraft();
  if (validation) {
    state.message = validation;
    state.messageError = true;
    renderState();
    return;
  }
  state.saving = true;
  state.message = "正在原子保存本条 CSV 记录……";
  state.messageError = false;
  renderState();
  const sourcePlayId = state.sample.source_play_id;
  try {
    const payload = {
      ...state.draft,
      reviewed_hit_time: state.draft.admission_status === "admitted"
        ? state.draft.reviewed_hit_time
        : "",
      observed_trajectory: state.draft.admission_status === "admitted"
        ? state.draft.observed_trajectory
        : "",
      reviewed_location: state.draft.admission_status === "admitted"
        ? state.draft.reviewed_location
        : "",
      reviewer_id: state.draft.reviewer_id.trim(),
      notes: state.draft.notes.trim(),
    };
    const result = await fetchJson(`/api/review/${encodeURIComponent(sourcePlayId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const item = state.samples[state.index];
    item.review_status = result.review.admission_status;
    item.reviewed_trajectory = result.review.observed_trajectory;
    state.summary = result.summary;
    const next = findNextUnreviewed(state.index);
    if (next === null) {
      await loadSample("已保存；所有队列样本都有记录，仍可从下方队列返回修改。");
    } else {
      state.index = next;
      await loadSample("上一条已保存；已进入下一条未审核样本。");
    }
  } catch (error) {
    state.message = `保存失败：${error.message}`;
    state.messageError = true;
  } finally {
    state.saving = false;
    renderState();
  }
}

function findNextUnreviewed(start) {
  for (let index = start + 1; index < state.samples.length; index += 1) {
    if (!state.samples[index].review_status) return index;
  }
  for (let index = 0; index <= start; index += 1) {
    if (!state.samples[index].review_status) return index;
  }
  return null;
}

async function clearReview() {
  if (!state.sample?.review) {
    state.message = "当前样本没有已保存记录。";
    state.messageError = false;
    renderState();
    return;
  }
  if (!window.confirm("清除本条已保存记录？媒体和候选库存不会改变。")) return;
  const result = await fetchJson(
    `/api/review/${encodeURIComponent(state.sample.source_play_id)}`,
    { method: "DELETE" },
  );
  state.samples[state.index].review_status = "";
  state.samples[state.index].reviewed_trajectory = "";
  state.summary = result.summary;
  await loadSample("本条审核记录已清除，重新变为未审核。");
}

async function goTo(index, notice = "") {
  if (!state.samples.length) return;
  const scrollY = window.scrollY;
  state.index = Math.max(0, Math.min(state.samples.length - 1, index));
  await loadSample(notice);
  requestAnimationFrame(() => window.scrollTo({ top: scrollY, behavior: "instant" }));
}

async function switchAudioMode() {
  if (!state.sample) return;
  if (!state.sample.enhanced_audio_url) {
    state.message = "本条没有击球增强音频；继续使用原始音频。";
    renderState();
    return;
  }
  const current = state.wavesurfer?.getCurrentTime() ?? 0;
  const playing = state.wavesurfer?.isPlaying() ?? false;
  state.audioMode = state.audioMode === "original" ? "enhanced" : "original";
  const token = ++state.loadToken;
  setupWaveform(state.sample, token);
  state.wavesurfer?.once("ready", () => {
    state.wavesurfer.setTime(current);
    if (playing) state.wavesurfer.play();
  });
  state.message = state.audioMode === "enhanced"
    ? "当前仅用于听辨的是“击球增强”；保存的时间轴和原始音频都没有改变。"
    : "已切回原始音频。";
  renderState();
}

async function handleAction(action) {
  if (action === "play") state.wavesurfer?.playPause();
  else if (action === "mode") await switchAudioMode();
  else if (action === "restore") restoreProposal();
  else if (action === "save") await saveReview();
  else if (action === "clear") await clearReview();
  else if (action === "previous") await goTo(state.index - 1);
  else if (action === "next") await goTo(state.index + 1);
  else if (action === "queue-previous") {
    state.queuePage = Math.max(0, state.queuePage - 1);
    renderQueue();
  } else if (action === "queue-next") {
    state.queuePage += 1;
    renderQueue();
  }
}

function isTyping(target) {
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
    if (isTyping(event.target)) return;
    const key = event.key.toLowerCase();
    if (event.key === " ") {
      event.preventDefault();
      handleAction("play");
    } else if (key === "j") handleAction("next");
    else if (key === "k") handleAction("previous");
    else if (key === "a") setAdmission("admitted");
    else if (key === "x") setAdmission("excluded");
    else if (Object.hasOwn(TRAJECTORY_KEYS, key)) setTrajectory(TRAJECTORY_KEYS[key]);
    else if (/^[1-9]$/.test(key)) setLocation(key);
    else if (key === "q") chooseCandidate(1);
    else if (key === "w") chooseCandidate(2);
    else if (key === "e") chooseCandidate(3);
    else if (key === "r") restoreProposal();
  });
}

function showFatal(error) {
  document.querySelector("#app").innerHTML = `
    <div class="boot"><strong>工作台启动失败</strong><span>${escapeHtml(error?.message ?? error)}</span></div>`;
  console.error(error);
}

async function init() {
  renderShell();
  bindKeyboard();
  const payload = await fetchJson("/api/workbench");
  if (!payload.formal_workbench || payload.workbench_kind !== "mlb_candidate_curation") {
    throw new Error("当前服务器不是 MLB 候选数据筛选台");
  }
  state.samples = payload.samples;
  state.summary = payload.summary;
  state.trajectoryLabels = payload.trajectory_labels_zh;
  state.exclusionLabels = payload.exclusion_labels_zh;
  state.resultsPath = payload.results_path;
  const range = payload.assigned_start_date && payload.assigned_end_date
    ? `${payload.assigned_start_date} 至 ${payload.assigned_end_date}`
    : "未记录日期段";
  document.querySelector("#assignment").textContent = `${payload.batch_id} · ${range}`;
  renderChoices();
  if (!state.samples.length) {
    state.message = "当前没有已准备媒体。请先运行候选发现和媒体准备命令。";
    renderState();
    return;
  }
  const firstUnreviewed = state.samples.findIndex((item) => !item.review_status);
  state.index = firstUnreviewed >= 0 ? firstUnreviewed : 0;
  await loadSample(
    state.summary.reviewed
      ? `已恢复 ${state.summary.reviewed} 条审核记录，从第一条未审核样本继续。`
      : "审核结果只会在明确保存时写入独立 CSV。",
  );
}

init().catch(showFatal);
