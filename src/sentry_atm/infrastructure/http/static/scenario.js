/* SENTRY 시연 진행 화면 — 시계를 쥔 쪽.
 *
 * 관제 콘솔과 이 화면은 **같은 세션 하나**를 본다. 세션은 서버에 있으므로 둘 다
 * 열어 두면 저절로 같은 시각을 가리킨다.
 *
 * 시계는 이 화면만 움직인다. 양쪽이 다 밀면 한 틱에 두 번 진행되고, 그러면
 * 화면에 보이는 시각과 관제사가 판단한 시각이 갈린다. 콘솔은 판단만 한다 —
 * 승인·수정·거부. 시간은 저절로 흐르는 것이고 판단은 사람이 하는 것이라,
 * 그 나눔이 실제 관제와도 맞는다.
 *
 * **관제사가 판단해야 하는 순간에는 스스로 멈춘다.** 멈추지 않으면 상신된 안이
 * 검증된 시각과 관제사가 승인하는 시각이 벌어지고, 그 사이 교통은 계속 움직인다.
 */

"use strict";

const API = "/api/v1/golden-demo/session";
const ACCESS = "/api/v1/reference/access";
const SCENARIO = "/api/v1/reference/scenario";

const RATES = [1, 2, 4, 8, 16];
const TICK_MS = 400;

/* 관제사의 손이 필요한 단계. 여기에 닿으면 재생을 멈춘다. */
const AWAITS_CONTROLLER = {
  CONFLICT_DETECTED: {
    title: "회피안 상신 대기",
    sub: "관제 콘솔에서 「회피안 상신」을 누르면 이어서 진행합니다.",
  },
  RECOMMENDATION_AVAILABLE: {
    title: "관제사 판단 대기",
    sub: "관제 콘솔에서 승인·수정·거부를 선택하면 이어서 진행합니다.",
  },
  DECISION_ACCEPTED: {
    title: "승인 기동 적용 대기",
    sub: "승인만으로는 항공기가 움직이지 않습니다. 콘솔에서 적용하십시오.",
  },
  DECISION_MODIFIED: {
    title: "수정안 검증 대기",
    sub: "관제사가 고친 안도 검증을 거칩니다. 콘솔에서 진행하십시오.",
  },
  MODIFICATION_REVALIDATED: {
    title: "수정 기동 적용 대기",
    sub: "검증을 통과했습니다. 콘솔에서 적용하십시오.",
  },
};

const $ = (id) => document.getElementById(id);

const state = {
  scenario: null,
  session: null,
  playing: false,
  rate: 4,
  busy: false,
};

/* ------------------------------------------------------------------ 서버 */

async function post(command, extra = {}) {
  const response = await fetch(`${API}/commands`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, ...extra }),
  });
  if (!response.ok) throw new Error(await refusalReason(response));
  return response.json();
}

/* 서버는 거부한 이유를 본문에 담아 보낸다. 그것을 버리고 상태 코드만 보여 주면
 * 화면에 「HTTP 409」만 남고, 관제사는 무엇이 잘못됐는지 알 길이 없다. */
async function refusalReason(response) {
  try {
    const body = await response.json();
    const message = body?.error?.message;
    if (message) return explainRefusal(message);
  } catch {
    // 본문이 JSON 이 아니면 상태 코드로 돌아간다.
  }
  return `서버가 거부했다 (HTTP ${response.status})`;
}

/* 서버 메시지는 영문이다. 자주 나오는 것만 우리말로 바꾸고, **모르는 것은 원문
 * 그대로 보여 준다** — 번역하지 못했다고 삼키면 그 사유가 화면에서 사라진다. */
function explainRefusal(message) {
  const stage = message.match(
    /requires Session stage ([A-Z_]+); current stage is ([A-Z_]+)/,
  );
  if (stage) {
    return `지금은 ${STAGE_KO[stage[1]] || stage[1]} 단계가 아니다 — 현재 ${
      STAGE_KO[stage[2]] || stage[2]
    }`;
  }
  if (message.includes("behind the Clock")) {
    return "화면이 보는 시각이 시계보다 뒤처졌다. 시연 화면에서 「처음으로」 후 다시 진행한다.";
  }
  if (message.includes("contemporaneous")) {
    return "판단한 시점과 지금이 다르다. 그 사이 교통이 움직였으므로 다시 상신해야 한다.";
  }
  if (message.includes("only a SAFE modified")) {
    return "검증을 통과하지 못한 수정안은 적용할 수 없다.";
  }
  return message;
}

const STAGE_KO = {
  READY: "대기",
  MONITORING: "감시",
  DEVIATION_DETECTED: "진입 편차",
  CONFLICT_DETECTED: "충돌 탐지",
  RECOMMENDATION_AVAILABLE: "회피안 상신",
  DECISION_ACCEPTED: "승인",
  DECISION_MODIFIED: "수정",
  DECISION_REJECTED: "거부",
  MODIFICATION_REVALIDATED: "수정 검증 완료",
  BLOCKED_MODIFICATION: "수정 반려",
  CONFLICT_RESOLVED: "해소",
};

async function get(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} → HTTP ${response.status}`);
  return response.json();
}

function setLink(ok) {
  $("link").className = `link-dot ${ok ? "live" : "dead"}`;
}

function say(text, kind = "") {
  const message = $("msg");
  message.textContent = text;
  message.className = `form-msg${kind ? " " + kind : ""}`;
}

/** 세션이 아직 시작 전인가. 판단 근거는 서버가 낸 단계다. */
function needsStart() {
  const stage = state.session?.stage;
  return stage === undefined || stage === null || stage === "READY";
}

const elapsed = () => state.session?.elapsed_seconds ?? 0;
const duration = () => state.scenario?.duration_seconds ?? 1;

/* ------------------------------------------------------------------ 시계 */

async function advance(seconds) {
  if (state.busy) return;
  state.busy = true;
  try {
    if (needsStart()) {
      state.session = await post("START");
    }
    state.session = await post("ADVANCE", { seconds: Math.max(1, Math.round(seconds)) });
    setLink(true);
    state.busy = false;
    render();
    pauseIfControllerNeeded();
  } catch (error) {
    setLink(false);
    stop();
    state.busy = false;
    say(String(error.message || error), "bad");
    render();
  } finally {
    state.busy = false;
  }
}

/** 처음으로 되돌린 뒤 지정한 시각까지 한 번에 민다. */
async function seek(offsetSeconds) {
  if (state.busy) return;
  state.busy = true;
  stop();
  try {
    // 되돌린 뒤이므로 세션은 반드시 READY 다.
    await post("RESET");
    state.session = await post("START");
    // 올림한다. 시계는 초 단위인데 단계 시각은 소수를 갖는다 — 13단계는
    // 3,893.0116 초다. 반올림하면 3,893 이 되어 그 단계에 0.01 초 못 미치고,
    // 화면은 여전히 앞 단계를 가리킨다. 1초 늦게 서는 것이 덜 나쁘다.
    const target = Math.ceil(offsetSeconds);
    if (target >= 1) {
      state.session = await post("ADVANCE", { seconds: target });
    }
    setLink(true);
    state.busy = false;
    say("");
    render();
  } catch (error) {
    setLink(false);
    state.busy = false;
    say(String(error.message || error), "bad");
    render();
  } finally {
    state.busy = false;
  }
}

/* 판단이 필요한 단계에 닿으면 멈춘다. 계속 밀면 상신된 안이 검증된 시각과
 * 승인하는 시각이 벌어진다. */
function pauseIfControllerNeeded() {
  const waiting = AWAITS_CONTROLLER[state.session?.stage];
  if (waiting && state.playing) {
    stop();
    say(`${waiting.title} — 재생을 멈췄습니다.`, "good");
  }
}

/* ------------------------------------------------------------------ 재생 */

let timer = null;
let watcher = null;

function start() {
  if (timer) return;
  state.playing = true;
  $("tri").className = "tri pause";
  $("play").setAttribute("aria-label", "일시정지");
  timer = setInterval(() => {
    if (elapsed() >= duration()) return stop();
    advance((state.rate * TICK_MS) / 1000);
  }, TICK_MS);
}

function stop() {
  if (timer) clearInterval(timer);
  timer = null;
  state.playing = false;
  $("tri").className = "tri";
  $("play").setAttribute("aria-label", "재생");
}

/* 멈춰 있는 동안에도 세션을 읽는다. 관제사가 콘솔에서 판단하면 단계가 바뀌는데,
 * 이 화면이 그것을 모르면 「판단 대기」가 계속 떠 있게 된다. */
function watchWhilePaused() {
  watcher = setInterval(async () => {
    if (state.playing || state.busy) return;
    try {
      const next = await get(API);
      if (next.stage !== state.session?.stage || next.elapsed_seconds !== elapsed()) {
        state.session = next;
        setLink(true);
        render();
      }
    } catch {
      setLink(false);
    }
  }, 1_000);
}

/* ------------------------------------------------------------------ 그리기 */

function hhmmss(seconds) {
  const whole = Math.max(0, Math.round(seconds));
  const h = String(Math.floor(whole / 3600)).padStart(2, "0");
  const m = String(Math.floor((whole % 3600) / 60)).padStart(2, "0");
  const s = String(whole % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

const steps = () => state.scenario?.steps || [];
const acts = () => state.scenario?.acts || [];

/** 지금 시각이 지나온 마지막 단계. 아직 아무것도 안 지났으면 null. */
function currentStep() {
  const now = elapsed();
  let found = null;
  for (const step of steps()) if (step.t_s <= now) found = step;
  return found;
}

/* 조항 이름표. 고시와 AIP 를 다르게 적는다 — 근거의 출처가 다르다. */
function isAip(clause) {
  return /^(AD|ENR|AIP)/.test(clause);
}

function render() {
  $("clock").textContent = hhmmss(elapsed());
  $("duration").textContent = hhmmss(duration());

  const stage = state.session?.stage || "READY";
  const waiting = AWAITS_CONTROLLER[stage];
  $("stage").textContent = stage;
  $("stage").className = `chip${waiting ? " warm" : ""}`;

  const step = currentStep();
  $("step-n").textContent = step ? String(step.n) : "—";
  $("step-name").textContent = step ? step.name : "시연 준비";
  $("step-detail").textContent = step
    ? step.detail || ""
    : "재생을 누르면 09:00 부터 시작합니다.";

  const clauses = $("step-clauses");
  clauses.textContent = "";
  for (const clause of step?.clauses || []) {
    const chip = document.createElement("span");
    chip.className = "clause";
    if (isAip(clause)) chip.dataset.aip = "1";
    chip.textContent = clause;
    clauses.appendChild(chip);
  }

  // 판단 대기
  const awaitBox = $("await");
  awaitBox.hidden = !waiting;
  if (waiting) {
    $("await-title").textContent = waiting.title;
    $("await-sub").textContent = waiting.sub;
  }

  // 막
  for (const button of $("acts").children) {
    const act = acts()[Number(button.dataset.index)];
    const active = act && elapsed() >= act.t0 && elapsed() < act.t1;
    button.setAttribute("aria-current", active ? "true" : "false");
    button.dataset.done = act && elapsed() >= act.t1 ? "1" : "0";
  }

  // 13단계 레일
  for (const item of $("rail").children) {
    const n = Number(item.dataset.n);
    item.setAttribute("aria-current", step && step.n === n ? "true" : "false");
    item.dataset.done = step && n < step.n ? "1" : "0";
  }

  const fraction = Math.min(1, elapsed() / duration());
  $("fill").style.width = `${fraction * 100}%`;
  $("head").style.left = `${fraction * 100}%`;
}

/* ------------------------------------------------------------------ 조작 */

function buildControls() {
  const rates = $("rates");
  for (const rate of RATES) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${rate}×`;
    button.setAttribute("aria-pressed", String(rate === state.rate));
    button.addEventListener("click", () => {
      state.rate = rate;
      for (const other of rates.children) {
        other.setAttribute("aria-pressed", String(other === button));
      }
    });
    rates.appendChild(button);
  }

  $("play").addEventListener("click", () => (state.playing ? stop() : start()));
  $("reset").addEventListener("click", () => seek(0));
  $("prev").addEventListener("click", () => jump(-1));
  $("next-step").addEventListener("click", () => jump(1));

  $("track").addEventListener("click", (event) => {
    const box = event.currentTarget.getBoundingClientRect();
    seek(((event.clientX - box.left) / box.width) * duration());
  });

  window.addEventListener("keydown", (event) => {
    if (event.target instanceof HTMLInputElement) return;
    if (event.code === "Space") {
      event.preventDefault();
      state.playing ? stop() : start();
    }
    if (event.code === "ArrowRight") jump(1);
    if (event.code === "ArrowLeft") jump(-1);
  });
}

/** 앞뒤 단계로. 지금 단계가 없으면 첫 단계로 간다. */
function jump(direction) {
  const all = steps();
  if (!all.length) return;
  const step = currentStep();
  const index = step ? all.findIndex((item) => item.n === step.n) : -1;
  const target = all[Math.max(0, Math.min(all.length - 1, index + direction))];
  if (target) seek(target.t_s);
}

function buildActs() {
  const bar = $("acts");
  bar.textContent = "";
  acts().forEach((act, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.index = String(index);
    const label = document.createElement("span");
    label.className = "act-n";
    label.textContent = `${act.n}막 · ${act.name}`;
    button.append(label, document.createTextNode(act.headline));
    button.title = act.text;
    button.addEventListener("click", () => seek(act.t0));
    bar.appendChild(button);
  });
}

function buildRail() {
  const rail = $("rail");
  rail.textContent = "";
  const cues = $("cues");
  cues.textContent = "";
  // 관제사의 판단이 필요한 지점만 눈금을 굵게 한다.
  const key = new Set([7, 9, 10, 11]);

  for (const step of steps()) {
    const item = document.createElement("li");
    item.dataset.n = String(step.n);
    item.tabIndex = 0;
    item.textContent = `${step.n}. ${step.name}`;
    item.title = step.detail || "";
    item.addEventListener("click", () => seek(step.t_s));
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        seek(step.t_s);
      }
    });
    rail.appendChild(item);

    const tick = document.createElement("i");
    tick.style.left = `${(step.t_s / duration()) * 100}%`;
    if (key.has(step.n)) tick.className = "key";
    cues.appendChild(tick);
  }
}

/* ------------------------------------------------------------------ 시작 */

/* 밖에서 연결한 화면은 시계를 건드리지 못한다. 서버가 막지만, 막힌 단추를
 * 남겨 두면 눌러 보고 아무 일도 일어나지 않는 것처럼 보인다. */
function applyAccess(access) {
  const operator = access ? access.operator !== false : true;
  $("viewer").hidden = operator;
  if (operator) return;
  for (const element of document.querySelectorAll(
    ".play, .rates, .stage-bar button, .ghost",
  )) {
    element.disabled = true;
  }
  $("play").hidden = true;
}

async function boot() {
  buildControls();
  try {
    state.scenario = await get(SCENARIO);
    state.session = await get(API);
    // 시각을 움직이는 것은 발표자뿐이다. 밖에서 본 사람이 재생을 누르면
    // 발표 중인 시계가 함께 움직인다 — 세션이 하나이기 때문이다.
    applyAccess(await get(ACCESS).catch(() => null));
    setLink(true);
  } catch (error) {
    setLink(false);
    say(String(error.message || error), "bad");
  }
  buildActs();
  buildRail();
  render();
  watchWhilePaused();
}

boot();
