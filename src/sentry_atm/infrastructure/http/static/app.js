/* SENTRY 관제 보조 콘솔.
 *
 * 화면은 세 가지를 서버에서 받는다.
 *
 *   배경 형상  /api/v1/reference/geometry   한 번. 공역·활주로·픽스·지형.
 *   시나리오   /api/v1/reference/scenario   한 번. 13단계와 전체 길이.
 *   현재 상태  /api/v1/golden-demo/session  매 틱. 항적·예외·충돌·권고.
 *
 * 시계는 화면이 돌린다. `ADVANCE` 로 초를 밀고 그 응답이 곧 새 상태다 — 별도로
 * 폴링하지 않는다. 밀고 나서 따로 읽으면 두 요청 사이에 시각이 어긋나고, 항적과
 * 예외가 다른 순간을 가리키게 된다.
 *
 * 좌표는 국지 x/y(NM)를 그대로 쓴다. 서버가 위경도를 국지 좌표로 바꿔 주므로
 * 화면에서 투영을 다시 할 이유가 없다. 배경 형상만 위경도로 오는데, 그것은
 * 한 번 받을 때 같은 접평면으로 바꾼다 — 서버와 같은 WGS84 곡률반경을 쓴다.
 */

"use strict";

const API = "/api/v1/golden-demo/session";
const GEOMETRY = "/api/v1/reference/geometry";
const SCENARIO = "/api/v1/reference/scenario";
const ADVISORY = "/api/v1/advisory";

/* RKTU 공항 기준점과 WGS84 곡률반경 — 서버 `geo.coordinate` 와 같은 값이다.
 * 평균 반지름으로 근사하면 30 NM 링에서 서버가 계산한 항적 위치와 배경이
 * 0.2 % 어긋나고, 그 어긋남은 화면에서 항적이 활주로를 비껴가는 것으로 보인다. */
const ARP_LAT = 36 + 42 / 60 + 59 / 3600;
const ARP_LON = 127 + 29 / 60 + 57 / 3600;
const WGS84_A = 6378137.0;
const WGS84_F = 1 / 298.257223563;
const M_PER_NM = 1852.0;

function curvatureRadiiNm(latDeg) {
  const lat = (latDeg * Math.PI) / 180;
  const e2 = WGS84_F * (2 - WGS84_F);
  const w = 1 - e2 * Math.sin(lat) ** 2;
  return [
    (WGS84_A * (1 - e2)) / Math.pow(w, 1.5) / M_PER_NM,
    WGS84_A / Math.sqrt(w) / M_PER_NM,
  ];
}

const [MERIDIONAL_NM, PRIME_VERTICAL_NM] = curvatureRadiiNm(ARP_LAT);
const COS_ARP = Math.cos((ARP_LAT * Math.PI) / 180);

/** 위경도 → RKTU 중심 국지 x/y (NM). 서버의 접평면과 같은 식이다. */
function toLocal(lat, lon) {
  return [
    ((((lon - ARP_LON + 540) % 360) - 180) * Math.PI / 180) * PRIME_VERTICAL_NM * COS_ARP,
    ((lat - ARP_LAT) * Math.PI / 180) * MERIDIONAL_NM,
  ];
}

const SVG_NS = "http://www.w3.org/2000/svg";
const RATES = [1, 2, 4, 8, 16];
const RANGES = [15, 25, 40, 60];

/* 항적 꼬리 — 지나온 자리를 몇 개 남긴다. 레이더 화면이 과거 위치를 남기는
 * 이유는 방향과 속도 변화를 한 눈에 읽기 위해서다. 현재 위치와 속도벡터만
 * 있으면 선회 중인지 직진 중인지 알 수 없다. */
const TRAIL_POINTS = 8;
const TICK_MS = 400;

/* 어떤 계층을 켜 둘 것인가. 지형과 링은 배경이라 기본으로 켜고, 픽스 이름은
 * 항적이 많을 때 겹치므로 끌 수 있게 둔다. */
const LAYERS = [
  ["terrain", "지형", true],
  ["airspace", "공역", true],
  ["rings", "거리링", true],
  ["holds", "체공장주", true],
  ["fixes", "픽스", true],
  ["tags", "데이터블록", true],
];

const $ = (id) => document.getElementById(id);

const state = {
  geometry: null,
  scenario: null,
  session: null,
  advisory: null,
  playing: false,
  rate: 4,
  selected: null,
  layers: Object.fromEntries(LAYERS.map(([k, , on]) => [k, on])),
  started: false,
  busy: false,
  trails: new Map(),
  view: { cx: 0, cy: 0, halfNm: 25 },
};

/* ------------------------------------------------------------------ 서버 */

async function post(command, extra = {}) {
  const response = await fetch(`${API}/commands`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, ...extra }),
  });
  if (!response.ok) throw new Error(`${command} → HTTP ${response.status}`);
  return response.json();
}

async function get(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} → HTTP ${response.status}`);
  return response.json();
}

function setLink(ok) {
  $("link").className = `link-dot ${ok ? "live" : "dead"}`;
}

/** 시계를 seconds 만큼 민다. 응답이 곧 새 상태다. */
async function advance(seconds) {
  if (state.busy) return;
  state.busy = true;
  try {
    if (!state.started) {
      state.session = await post("START");
      state.started = true;
    }
    const step = Math.max(1, Math.round(seconds));
    state.session = await post("ADVANCE", { seconds: step });
    state.advisory = await get(ADVISORY).catch(() => null);
    setLink(true);
    render();
  } catch (error) {
    setLink(false);
    stop();
    console.error(error);
  } finally {
    state.busy = false;
  }
}

/** 처음으로 되돌린 뒤 지정한 시각까지 한 번에 민다. */
async function seek(offsetSeconds) {
  if (state.busy) return;
  state.busy = true;
  const wasPlaying = state.playing;
  stop();
  state.trails.clear();
  try {
    await post("RESET");
    state.session = await post("START");
    state.started = true;
    const target = Math.round(offsetSeconds);
    if (target >= 1) {
      state.session = await post("ADVANCE", { seconds: target });
    }
    state.advisory = await get(ADVISORY).catch(() => null);
    setLink(true);
    render();
  } catch (error) {
    setLink(false);
    console.error(error);
  } finally {
    state.busy = false;
    if (wasPlaying) start();
  }
}

/* ------------------------------------------------------------------ 재생 */

let timer = null;

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

const elapsed = () => state.session?.elapsed_seconds ?? 0;
const duration = () => state.scenario?.duration_seconds ?? 1;

function hhmmss(seconds) {
  const whole = Math.max(0, Math.round(seconds));
  const h = String(Math.floor(whole / 3600)).padStart(2, "0");
  const m = String(Math.floor((whole % 3600) / 60)).padStart(2, "0");
  const s = String(whole % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

/* ------------------------------------------------------------------ 스코프 */

function fitView() {
  const scope = $("scope");
  const w = scope.clientWidth || 900;
  const h = scope.clientHeight || 600;
  const svg = $("svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  state.view.w = w;
  state.view.h = h;
  // 짧은 변에 지름이 들어가도록 잡는다. 긴 변에 맞추면 세로가 잘린다.
  state.view.scale = Math.min(w, h) / (2 * state.view.halfNm);
  $("scale").textContent = `${state.view.halfNm.toFixed(0)} NM 반경`;
}

/** 국지 x/y(NM) → 화면 픽셀. 북쪽이 위이므로 y 를 뒤집는다. */
function px(x, y) {
  const { w, h, scale, cx, cy } = state.view;
  return [w / 2 + (x - cx) * scale, h / 2 - (y - cy) * scale];
}

function node(tag, attrs, parent) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) element.setAttribute(key, value);
  }
  if (parent) parent.appendChild(element);
  return element;
}

function pathFromGeodetic(points) {
  return points
    .map((point, index) => {
      const [x, y] = toLocal(point[0], point[1]);
      const [sx, sy] = px(x, y);
      return `${index ? "L" : "M"}${sx.toFixed(1)} ${sy.toFixed(1)}`;
    })
    .join(" ");
}

function clear(id) {
  const group = $(id);
  while (group.firstChild) group.removeChild(group.firstChild);
  return group;
}

function drawBackground() {
  const geometry = state.geometry;
  if (!geometry) return;

  // --- 지형 ---
  const terrain = clear("g-terrain");
  if (state.layers.terrain && state.view.halfNm >= 40 && geometry.terrain) {
    for (const [name, layer] of Object.entries(geometry.terrain)) {
      // 해안선은 열린 선이고 육지는 닫힌 면이다. 해안선을 면으로 채우면 선이
      // 감싸는 바다 쪽이 육지 색으로 칠해진다.
      const closed = name !== "coastline";
      for (const ring of Array.isArray(layer) ? layer : []) {
        if (!Array.isArray(ring) || ring.length < 2) continue;
        node(
          "path",
          {
            d: pathFromGeodetic(ring) + (closed ? " Z" : ""),
            class: closed ? "terrain-land" : "terrain-coast",
          },
          terrain,
        );
      }
    }
  }

  // --- 공역 ---
  const airspace = clear("g-airspace");
  if (state.layers.airspace) {
    for (const zone of geometry.restricted || []) {
      node("path", { d: `${pathFromGeodetic(zone.points)} Z`, class: "restricted" }, airspace);
      label(airspace, zone.centre, zone.id);
    }
    const activeArea = state.scenario?.operating_area_id;
    for (const zone of geometry.moa || []) {
      node(
        "path",
        {
          d: `${pathFromGeodetic(zone.points)} Z`,
          class: `moa${zone.id === activeArea ? " live" : ""}`,
        },
        airspace,
      );
      label(airspace, centroid(zone.points), zone.id);
    }
    for (const zone of geometry.neighbour_ctr || []) {
      node("path", { d: `${pathFromGeodetic(zone.points)} Z`, class: "sector-2" }, airspace);
      label(airspace, zone.centre, zone.id);
    }
    if (geometry.t17?.length) {
      node("path", { d: `${pathFromGeodetic(geometry.t17)} Z`, class: "sector" }, airspace);
    }
    if (geometry.t19?.length) {
      node("path", { d: `${pathFromGeodetic(geometry.t19)} Z`, class: "sector-2" }, airspace);
    }
  }

  // --- 거리 링 ---
  const rings = clear("g-rings");
  if (state.layers.rings) {
    for (const ring of geometry.rings || []) {
      node("path", { d: `${pathFromGeodetic(ring.points)} Z`, class: "ring" }, rings);
      const [x, y] = toLocal(...geometry.centre);
      const [sx, sy] = px(x, y - ring.radius_nm);
      node("text", { x: sx + 3, y: sy - 3, class: "ring-label" }, rings).textContent =
        `${ring.radius_nm}`;
    }
  }

  // --- 활주로와 최종접근 연장선 ---
  const runway = clear("g-runway");
  if (geometry.runway) {
    const [ax, ay] = toLocal(...geometry.runway.thr24r);
    const [bx, by] = toLocal(...geometry.runway.thr06l);
    const [p1x, p1y] = px(ax, ay);
    const [p2x, p2y] = px(bx, by);
    node("line", { x1: p1x, y1: p1y, x2: p2x, y2: p2y, class: "runway-line" }, runway);
  }
  if (geometry.centreline?.length === 2) {
    node("path", { d: pathFromGeodetic(geometry.centreline), class: "centreline" }, runway);
  }

  // --- 공고 체공 장주 ---
  const holds = clear("g-holds");
  if (state.layers.holds) {
    const inUse = new Set((state.advisory?.holdings || []).map((hold) => hold.fix));
    for (const hold of geometry.holds || []) {
      node(
        "path",
        {
          d: `${pathFromGeodetic(hold.points)} Z`,
          class: `hold${inUse.has(hold.fix) ? " live" : ""}`,
        },
        holds,
      );
    }
  }

  // --- 픽스 ---
  const fixes = clear("g-fixes");
  if (state.layers.fixes) {
    for (const fix of geometry.fixes || []) {
      const [x, y] = toLocal(fix.lat, fix.lon);
      const [sx, sy] = px(x, y);
      node(
        "path",
        { d: `M${sx} ${sy - 3.2} L${sx + 3.2} ${sy} L${sx} ${sy + 3.2} L${sx - 3.2} ${sy} Z`, class: "fix" },
        fixes,
      );
      node("text", { x: sx + 5, y: sy + 3, class: "fix-label" }, fixes).textContent = fix.name;
    }
  }
}

function centroid(points) {
  const sum = points.reduce((acc, p) => [acc[0] + p[0], acc[1] + p[1]], [0, 0]);
  return [sum[0] / points.length, sum[1] / points.length];
}

function label(parent, centre, text) {
  if (!centre) return;
  const [x, y] = toLocal(centre[0], centre[1]);
  const [sx, sy] = px(x, y);
  node("text", { x: sx, y: sy, class: "zone-label", "text-anchor": "middle" }, parent).textContent =
    text;
}

/* 서버가 쓰는 심각도 어휘. 화면에서 다시 등급을 매기지 않는다 — 자기 기준으로
 * 색을 칠하기 시작하면 예외 큐와 스코프가 서로 다른 말을 하게 되고, 어느 쪽이
 * 판정인지 알 수 없어진다. */
const SEVERITY = {
  EMERGENCY: { ko: "비상", rank: 4, css: "emerg" },
  HIGH: { ko: "위험", rank: 3, css: "danger" },
  MEDIUM: { ko: "주의", rank: 2, css: "caution" },
  LOW: { ko: "낮음", rank: 1, css: "normal" },
};

const NORMAL = { ko: "정상", rank: 0, css: "normal" };

const severityOf = (name) => SEVERITY[name] || NORMAL;

const queueItems = () => state.session?.exception_queue?.items || [];

/** 이 항공기에 걸린 가장 높은 심각도. 큐에 없으면 정상이다. */
function levelOf(aircraftId) {
  let worst = NORMAL;
  for (const item of queueItems()) {
    if (!(item.subject_aircraft_ids || []).includes(aircraftId)) continue;
    const severity = severityOf(item.severity);
    if (severity.rank > worst.rank) worst = severity;
  }
  return worst;
}

/* 사유 코드는 서버가 대문자 영문으로 낸다. 화면에 그대로 두면 관제사가 읽을 수
 * 없고, 없는 코드를 임의로 번역해 두면 서버가 코드를 늘렸을 때 조용히 빠진다.
 * 모르는 코드는 코드 그대로 보여 준다 — 빠지는 것보다 낫다. */
const REASON_KO = {
  EMERGENCY_DECLARED: "비상 선언",
  AIRCRAFT_CONDITION: "기체 상태",
  PREDICTED_SEPARATION_LOSS: "분리 상실 예측",
  HORIZONTAL_THRESHOLD_BREACH: "수평 최저치 미달",
  VERTICAL_THRESHOLD_BREACH: "수직 최저치 미달",
  SHORT_TCPA: "근접까지 시간 부족",
  ENTRY_CONFORMANCE_DEVIATION: "진입 편차",
};

const reasonKo = (code) => REASON_KO[code] || code;

function drawTraffic() {
  const links = clear("g-links");
  const traffic = clear("g-traffic");
  const states = state.session?.traffic || [];
  const byId = new Map(states.map((item) => [item.aircraft_id, item]));

  // --- 충돌 쌍 ---
  const conflict = state.session?.primary_conflict;
  const pair = conflict?.aircraft_ids || [];
  if (pair.length === 2) {
    const a = byId.get(pair[0]);
    const b = byId.get(pair[1]);
    if (a && b) {
      const [ax, ay] = px(a.x_nm, a.y_nm);
      const [bx, by] = px(b.x_nm, b.y_nm);
      const css = severityOf(conflict.risk_level).css;
      node("line", { x1: ax, y1: ay, x2: bx, y2: by, class: `link ${css}` }, links);
      // 최저치를 함께 적는다. 거리만 보이면 그 값이 가까운 것인지 알 수 없다.
      const separation = conflict.horizontal_separation_nm;
      const threshold = conflict.horizontal_threshold_nm;
      if (Number.isFinite(separation)) {
        node(
          "text",
          {
            x: (ax + bx) / 2,
            y: (ay + by) / 2 - 5,
            class: "link-label",
            fill: `var(--${css})`,
            "text-anchor": "middle",
          },
          links,
        ).textContent = `${separation.toFixed(1)} / ${Number(threshold ?? 3).toFixed(0)} NM`;
      }
    }
  }

  // --- 꼬리 ---
  for (const aircraft of states) {
    const trail = state.trails.get(aircraft.aircraft_id) || [];
    if (trail.length < 2) continue;
    trail.slice(0, -1).forEach((point, index) => {
      const [tx, ty] = px(point.x, point.y);
      node(
        "circle",
        {
          cx: tx,
          cy: ty,
          r: 1.4,
          class: "ac-trail",
          // 오래된 자리일수록 흐리다. 그래야 어느 쪽으로 가고 있는지 읽힌다.
          opacity: (0.12 + 0.5 * (index / Math.max(1, trail.length - 1))).toFixed(2),
        },
        traffic,
      );
    });
  }

  // --- 항적 ---
  for (const aircraft of states) {
    const level = levelOf(aircraft.aircraft_id).css;
    const emergency = aircraft.emergency_status === "DECLARED";
    const [sx, sy] = px(aircraft.x_nm, aircraft.y_nm);

    const group = node(
      "g",
      {
        class: "ac",
        "data-level": level,
        "data-emerg": emergency ? "1" : "0",
        "data-sel": state.selected === aircraft.aircraft_id ? "1" : "0",
      },
      traffic,
    );
    group.addEventListener("click", () => {
      state.selected = state.selected === aircraft.aircraft_id ? null : aircraft.aircraft_id;
      render();
    });

    if (state.selected === aircraft.aircraft_id) {
      node("circle", { cx: sx, cy: sy, r: 13, class: "ac-halo" }, group);
    }

    // 속도 벡터 — 1분 뒤 위치까지.
    const heading = ((aircraft.heading_deg || 0) * Math.PI) / 180;
    const reach = ((aircraft.ground_speed_kt || 0) / 60) * state.view.scale;
    node(
      "line",
      {
        x1: sx,
        y1: sy,
        x2: sx + Math.sin(heading) * reach,
        y2: sy - Math.cos(heading) * reach,
        class: "ac-vec",
      },
      group,
    );

    // 군용은 삼각형, 민항은 사각형. 화면에서 둘을 색이 아니라 모양으로 가른다 —
    // 색은 위험도에 쓰고 있으므로 소속까지 색으로 나누면 둘이 섞인다.
    const military = /^ROKAF/.test(aircraft.aircraft_id);
    if (military) {
      node(
        "path",
        { d: `M${sx} ${sy - 5} L${sx + 4.5} ${sy + 3.5} L${sx - 4.5} ${sy + 3.5} Z`, class: "ac-body" },
        group,
      );
    } else {
      node("rect", { x: sx - 4, y: sy - 4, width: 8, height: 8, class: "ac-body" }, group);
    }

    if (!state.layers.tags) continue;

    node("line", { x1: sx + 5, y1: sy - 5, x2: sx + 11, y2: sy - 11, class: "ac-lead" }, group);
    const text = node("text", { x: sx + 13, y: sy - 12, class: "ac-tag" }, group);
    const callsign = node("tspan", { class: "cs" }, text);
    callsign.textContent = aircraft.aircraft_id;
    const line2 = node("tspan", { x: sx + 13, dy: 10 }, text);
    line2.textContent = `${Math.round(aircraft.altitude_ft / 100)
      .toString()
      .padStart(3, "0")} ${Math.round(aircraft.ground_speed_kt)}`;
    const line3 = node("tspan", { x: sx + 13, dy: 10 }, text);
    const vertical =
      aircraft.vertical_speed_fpm > 200 ? "↑" : aircraft.vertical_speed_fpm < -200 ? "↓" : "→";
    line3.textContent = `${aircraft.aircraft_type} ${vertical}`;
  }
}

/* 지금 단계에서 이어지는 명령.
 *
 * 골든 데모는 보정된 대본이라 상신·승인이 정해진 시점에만 성립한다. 화면에
 * 모든 명령 단추를 늘어놓으면 관제사는 어느 것이 지금 가능한지 알 수 없고,
 * 눌러 본 뒤 거부당하는 것으로 배우게 된다. 지금 성립하는 것 하나만 낸다. */
const COMMAND_BY_STAGE = {
  READY: { command: "START", label: "감시 시작" },
  MONITORING: { command: "ADVANCE_TO_CONFLICT", label: "충돌 시점으로" },
  CONFLICT_DETECTED: { command: "GENERATE_RECOMMENDATION", label: "회피안 상신" },
  DECISION_ACCEPTED: { command: "APPLY_APPROVED_MANEUVER", label: "승인 기동 적용" },
  MODIFICATION_REVALIDATED: {
    command: "APPLY_VALIDATED_MODIFIED_MANEUVER",
    label: "수정 기동 적용",
  },
};

/* 수정안이 검증에서 막힌 상태. 여기서는 적용을 내지 않는다 — 막힌 안을 적용할
 * 수 있게 두면 검증이 형식이 된다. */
COMMAND_BY_STAGE.BLOCKED_MODIFICATION = null;

function drawNextCommand() {
  const button = $("next");
  const stage = state.session?.stage;
  const next = COMMAND_BY_STAGE[stage];
  if (!next) {
    button.hidden = true;
    return;
  }
  button.hidden = false;
  button.textContent = next.label;
  button.disabled = state.busy;
  button.onclick = () => decide(next.command);
}

/* ------------------------------------------------------------------ 우측 레일 */

function drawQueue() {
  const items = queueItems();
  const list = $("qlist");
  list.textContent = "";
  $("qcount").textContent = String(items.length);
  const worst = items.reduce((rank, item) => Math.max(rank, severityOf(item.severity).rank), 0);
  $("qcount").className = `count${worst >= 3 ? " hot" : worst ? " warm" : ""}`;
  $("qempty").hidden = items.length > 0;

  // 심각한 것이 위로. 관제사는 위에서부터 읽는다.
  const ordered = [...items].sort(
    (a, b) =>
      severityOf(b.severity).rank - severityOf(a.severity).rank ||
      (b.score ?? 0) - (a.score ?? 0),
  );

  for (const entry of ordered) {
    const severity = severityOf(entry.severity);
    const subjects = entry.subject_aircraft_ids || [];
    const row = document.createElement("li");
    row.className = "qitem";
    row.dataset.level = severity.ko;
    if (subjects.includes(state.selected)) row.dataset.sel = "1";

    const head = document.createElement("div");
    head.className = "qrow";
    const callsign = document.createElement("span");
    callsign.className = "qcs";
    callsign.textContent = subjects.join(" · ") || "—";
    const badge = document.createElement("span");
    badge.className = "qlevel";
    badge.textContent = severity.ko;
    head.append(callsign, badge);

    const why = document.createElement("p");
    why.className = "qwhy";
    why.textContent = (entry.reason_codes || []).map(reasonKo).join(", ") || "판단 필요";

    const meta = document.createElement("div");
    meta.className = "qmeta";
    if (Number.isFinite(entry.tcpa_seconds)) {
      const cell = document.createElement("span");
      cell.textContent = `근접까지 ${Math.round(entry.tcpa_seconds)}초`;
      meta.appendChild(cell);
    }
    if (Number.isFinite(entry.horizontal_separation_ratio)) {
      const cell = document.createElement("span");
      // 비율은 최저치 대비다 — 1.0 이 최저치이고 그 아래가 미달이다. 거리만
      // 적으면 그 값이 가까운 것인지 화면에서 알 수 없다.
      cell.textContent = `수평 ${Math.round(entry.horizontal_separation_ratio * 100)}%`;
      meta.appendChild(cell);
    }
    const score = document.createElement("span");
    score.textContent = `점수 ${Math.round(entry.score ?? 0)}`;
    meta.appendChild(score);

    row.append(head, why, meta);
    row.addEventListener("click", () => {
      const first = subjects[0] || null;
      state.selected = state.selected === first ? null : first;
      render();
    });
    list.appendChild(row);
  }
}

function drawDetail() {
  const card = $("detail-card");
  const aircraft = (state.session?.traffic || []).find(
    (item) => item.aircraft_id === state.selected,
  );
  if (!aircraft) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  const box = $("detail");
  box.textContent = "";

  const head = document.createElement("div");
  head.className = "dhead";
  const callsign = document.createElement("span");
  callsign.className = "dcs";
  callsign.textContent = aircraft.aircraft_id;
  const type = document.createElement("span");
  type.className = "dtype";
  type.textContent = `${aircraft.aircraft_type} · ${aircraft.category}`;
  head.append(callsign, type);
  box.appendChild(head);

  const rows = [
    ["고도", `${Math.round(aircraft.altitude_ft).toLocaleString()} ft`],
    ["대지속도", `${Math.round(aircraft.ground_speed_kt)} kt`],
    ["침로", `${Math.round(aircraft.heading_deg).toString().padStart(3, "0")}°`],
    ["수직속도", `${Math.round(aircraft.vertical_speed_fpm).toLocaleString()} fpm`],
    ["비행단계", aircraft.flight_phase],
    ["위험도", levelOf(aircraft.aircraft_id).ko],
  ];
  const unit = (state.advisory?.control_units || []).find(
    (item) => item.aircraft_id === aircraft.aircraft_id,
  );
  if (unit) rows.push(["관제기관", unit.unit + (unit.lateral ? " (측방)" : "")]);
  if (aircraft.emergency_status === "DECLARED") {
    rows.push(["비상", aircraft.emergency_type || "선언됨"]);
  }
  for (const [key, value] of rows) {
    const row = document.createElement("div");
    row.className = "drow";
    const k = document.createElement("span");
    k.className = "dk";
    k.textContent = key;
    const v = document.createElement("span");
    v.className = "dv";
    v.textContent = value;
    row.append(k, v);
    box.appendChild(row);
  }
}

function renderConflictExplainability(session) {
  const box = $("why");
  box.textContent = "";
  const conflict = session?.primary_conflict;
  if (!conflict) return;

  // 왜 이것이 예외인가 — 값과 최저치를 나란히 둔다. 값만 보이면 그것이 가까운
  // 것인지 알 수 없고, 근거 없는 경고는 관제사가 무시하게 된다.
  const rows = [
    [
      "수평 분리",
      `${Number(conflict.horizontal_separation_nm).toFixed(2)} / ${Number(
        conflict.horizontal_threshold_nm,
      ).toFixed(1)} NM`,
      conflict.horizontal_separation_nm < conflict.horizontal_threshold_nm,
    ],
    [
      "수직 분리",
      `${Math.round(conflict.vertical_separation_ft)} / ${Math.round(
        conflict.vertical_threshold_ft,
      )} ft`,
      conflict.vertical_separation_ft < conflict.vertical_threshold_ft,
    ],
    ["최근접까지", `${Math.round(conflict.tcpa_seconds)}초`, conflict.tcpa_seconds < 180],
    ["위험도", severityOf(conflict.risk_level).ko, severityOf(conflict.risk_level).rank >= 3],
  ];
  for (const [key, value, bad] of rows) {
    const row = document.createElement("div");
    row.className = "why-row";
    const k = document.createElement("span");
    k.className = "why-k";
    k.textContent = key;
    const v = document.createElement("span");
    v.className = `why-v${bad ? " bad" : ""}`;
    v.textContent = value;
    row.append(k, v);
    box.appendChild(row);
  }

  for (const code of conflict.risk_reason_codes || []) {
    const row = document.createElement("div");
    row.className = "why-row";
    const k = document.createElement("span");
    k.className = "why-k";
    k.textContent = reasonKo(code);
    row.appendChild(k);
    box.appendChild(row);
  }
}

function drawRecommendation() {
  const card = $("rec-card");
  const session = state.session;
  const recommendation = session?.recommendation;
  if (!recommendation) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  const box = $("rec");
  box.textContent = "";

  const primary = primaryRecommendation(session);
  const maneuver = primary?.maneuver;
  const line = document.createElement("div");
  line.className = "rec-line";
  line.textContent = primary
    ? [
        primary.target_aircraft_id,
        maneuver?.maneuver_type,
        Number.isFinite(maneuver?.target_altitude_ft)
          ? `${Math.round(maneuver.target_altitude_ft).toLocaleString()} ft`
          : null,
        Number.isFinite(maneuver?.target_heading_deg)
          ? `침로 ${Math.round(maneuver.target_heading_deg)}°`
          : null,
      ]
        .filter(Boolean)
        .join(" ")
    : "권고 있음";
  box.appendChild(line);

  const why = document.createElement("p");
  why.className = "rec-why";
  why.textContent = primary?.explanation || "";
  if (why.textContent) box.appendChild(why);

  renderCandidateComparisons(session.candidate_comparisons || []);

  renderConflictExplainability(session);

  // 고도 칸은 권고 값으로 채워 둔다. 빈 칸이면 관제사가 무엇을 기준으로
  // 고치는 것인지 알 수 없다.
  const altitude = $("alt");
  if (!altitude.value && Number.isFinite(maneuver?.target_altitude_ft)) {
    altitude.value = String(Math.round(maneuver.target_altitude_ft));
  }
  // 검증을 통과했을 때만 적용을 연다. 항상 열어 두면 검증이 형식이 된다.
  $("apply-mod").hidden = session?.stage !== "MODIFICATION_REVALIDATED";
}

/* 관제사 판단. 어느 것도 화면에서 결과를 만들지 않는다 — 서버가 검증하고
 * 적용하며, 화면은 그 결과를 받아 그린다. */

function say(text, kind = "") {
  for (const id of ["msg", "next-msg"]) {
    const message = $(id);
    message.textContent = text;
    message.className = `form-msg${kind ? " " + kind : ""}`;
  }
}

async function decide(command, extra = {}) {
  if (state.busy) return;
  state.busy = true;
  stop();
  try {
    state.session = await post(command, extra);
    state.advisory = await get(ADVISORY).catch(() => null);
    setLink(true);
    say(`${command} 완료 — 단계 ${state.session.stage}`, "good");
    render();
  } catch (error) {
    setLink(true);
    // 거부당한 이유를 그대로 보여 준다. 삼키면 관제사가 무엇이 막혔는지 모른다.
    say(String(error.message || error), "bad");
  } finally {
    state.busy = false;
  }
}

function wireDecision() {
  // 승인 → 적용. 승인만으로는 항공기가 움직이지 않는다. 두 단계를 합치면
  // "승인했으나 아직 적용하지 않은" 상태가 감사 기록에서 사라진다.
  $("accept").addEventListener("click", async () => {
    await decide("ACCEPT_RECOMMENDATION");
    if (state.session?.stage === "DECISION_ACCEPTED") {
      await decide("APPLY_APPROVED_MANEUVER");
    }
  });

  $("reject").addEventListener("click", () => {
    const rationale = $("why-text").value.trim();
    if (!rationale) return say("거부에는 사유가 필요하다.", "bad");
    decide("REJECT_RECOMMENDATION", { rationale });
  });

  // 수정 → 재검증. 관제사가 고친 안도 검증을 거친다 — 사람이 고쳤다는 이유로
  // 검증을 건너뛰면 상신된 안보다 위험한 것이 그대로 나갈 수 있다.
  $("modify").addEventListener("click", async () => {
    const rationale = $("why-text").value.trim();
    const altitude = Number($("alt").value);
    if (!rationale) return say("수정에는 사유가 필요하다.", "bad");
    if (!Number.isFinite(altitude)) return say("고도를 숫자로 넣어야 한다.", "bad");
    await decide("MODIFY_RECOMMENDATION", {
      rationale,
      modified_maneuver: modifiedManeuver(altitude),
    });
    if (state.session?.stage === "DECISION_MODIFIED") {
      await decide("REVALIDATE_MODIFIED_MANEUVER");
    }
  });

  $("apply-mod").addEventListener("click", () =>
    decide("APPLY_VALIDATED_MODIFIED_MANEUVER"),
  );
}

/* 수정안은 권고안을 바탕으로 고도만 바꾼 것이다. 나머지 항목을 화면이 새로
 * 지어내면 서버가 검증하는 대상이 관제사가 본 것과 달라진다. */
function modifiedManeuver(altitudeFt) {
  const base = primaryRecommendation(state.session)?.maneuver || {};
  return { ...base, target_altitude_ft: altitudeFt };
}

/** 상신된 안 하나. 목록에서 primary 로 지목된 것이며, 순위 1위와 같지 않을 수 있다. */
function primaryRecommendation(session) {
  const set = session?.recommendation;
  if (!set) return null;
  const list = set.recommendations || [];
  return (
    list.find((item) => item.recommendation_id === set.primary_recommendation_id) ||
    list[0] ||
    null
  );
}

/* 후보 비교 — 왜 이것이 뽑혔는가.
 *
 * 상신된 안만 보여 주면 관제사는 다른 선택지가 있었는지 알 수 없고, 그러면
 * 화면을 믿거나 무시하는 두 가지밖에 남지 않는다. 탈락한 후보와 그 이유를
 * 함께 두는 것이 판단을 사람에게 남기는 방법이다. */
function renderCandidateComparisons(candidates) {
  const box = $("candidates");
  box.textContent = "";
  if (!candidates.length) return;

  box.appendChild(subhead("후보 비교"));
  for (const candidate of candidates) {
    const row = document.createElement("div");
    row.className = "cand";
    row.dataset.verdict = candidate.verdict;
    if (candidate.recommended) row.dataset.pick = "1";

    const head = document.createElement("div");
    head.className = "cand-head";
    const id = document.createElement("span");
    id.className = "cand-id";
    id.textContent = candidate.candidate_id;
    const verdict = document.createElement("span");
    verdict.className = "cand-verdict";
    verdict.textContent = candidate.verdict === "SAFE" ? "안전" : "부적합";
    head.append(id, verdict);

    const what = document.createElement("div");
    what.className = "cand-what";
    what.textContent = [
      candidate.maneuver_type,
      Number.isFinite(candidate.target_altitude_ft)
        ? `${Math.round(candidate.target_altitude_ft).toLocaleString()} ft`
        : null,
      Number.isFinite(candidate.target_heading_deg)
        ? `침로 ${Math.round(candidate.target_heading_deg)}°`
        : null,
    ]
      .filter(Boolean)
      .join(" · ");

    const meta = document.createElement("div");
    meta.className = "qmeta";
    if (Number.isFinite(candidate.primary_horizontal_separation_nm)) {
      const cell = document.createElement("span");
      cell.textContent = `${candidate.primary_horizontal_separation_nm.toFixed(1)} NM`;
      meta.appendChild(cell);
    }
    if (Number.isFinite(candidate.primary_vertical_separation_ft)) {
      const cell = document.createElement("span");
      cell.textContent = `${Math.round(candidate.primary_vertical_separation_ft)} ft`;
      meta.appendChild(cell);
    }
    if (Number.isFinite(candidate.operational_cost_score)) {
      const cell = document.createElement("span");
      cell.textContent = `비용 ${candidate.operational_cost_score}`;
      meta.appendChild(cell);
    }
    if (!candidate.performance_feasible) {
      const cell = document.createElement("span");
      cell.textContent = "성능 초과";
      meta.appendChild(cell);
    }
    for (const violation of candidate.rule_violation_ids || []) {
      const cell = document.createElement("span");
      cell.textContent = violation;
      meta.appendChild(cell);
    }

    row.append(head, what, meta);
    box.appendChild(row);
  }
}

/* 진입 편차 — 계획과 실제의 차이. 예외 큐에 오르기 전 단계이며, 이것만으로는
 * 충돌이 아니다. 그래서 위험도 색을 쓰지 않는다. */
function renderDeviation(deviation) {
  const card = $("dev-card");
  if (!deviation) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  const box = $("dev");
  box.textContent = "";

  const head = document.createElement("div");
  head.className = "dhead";
  const callsign = document.createElement("span");
  callsign.className = "dcs";
  callsign.textContent = deviation.aircraft_id;
  const point = document.createElement("span");
  point.className = "dtype";
  point.textContent = deviation.expected_entry_point || "";
  head.append(callsign, point);
  box.appendChild(head);

  // 계획과 실제를 나란히 둔다. 차이만 적으면 무엇에서 벗어난 것인지 모른다.
  const rows = [
    [
      "고도",
      `${Math.round(deviation.actual_altitude_ft).toLocaleString()} / 계획 ${Math.round(
        deviation.expected_altitude_ft,
      ).toLocaleString()} ft`,
    ],
    [
      "침로",
      `${Math.round(deviation.actual_heading_deg)}° / 계획 ${Math.round(
        deviation.expected_heading_deg,
      )}°`,
    ],
    ["측방 편차", `${Number(deviation.lateral_deviation_nm).toFixed(1)} NM`],
    ["시간 편차", `${Math.round(deviation.time_deviation_seconds)}초`],
  ];
  for (const [key, value] of rows) {
    const row = document.createElement("div");
    row.className = "drow";
    const k = document.createElement("span");
    k.className = "dk";
    k.textContent = key;
    const v = document.createElement("span");
    v.className = "dv";
    v.textContent = value;
    row.append(k, v);
    box.appendChild(row);
  }
}

function drawAdvisory() {
  const card = $("adv-card");
  const advisory = state.advisory;
  const slots = advisory?.runway_slots || [];
  const holds = advisory?.holdings || [];
  const route = advisory?.recovery_route;
  if (!slots.length && !holds.length && !route) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  const box = $("adv");
  box.textContent = "";

  if (slots.length) {
    box.appendChild(subhead("활주로 순서"));
    const list = document.createElement("ol");
    list.className = "slots";
    for (const slot of slots) {
      const row = document.createElement("li");
      if (slot.aircraft_id === advisory.emergency_aircraft_id) row.dataset.emerg = "1";

      const line = document.createElement("div");
      line.className = "slot-line";
      const callsign = document.createElement("span");
      callsign.className = "slot-cs";
      callsign.textContent = slot.aircraft_id;
      const distance = document.createElement("span");
      distance.className = "slot-d";
      distance.textContent = `${slot.distance_to_threshold_nm.toFixed(1)} NM`;
      line.append(callsign, distance);
      row.appendChild(line);

      if (slot.required_gap_seconds > 0) {
        const gap = document.createElement("div");
        gap.className = "slot-gap";
        gap.textContent = `${Math.round(slot.required_gap_seconds)}초 · ${slot.binding}`;
        row.appendChild(gap);
      }
      if (slot.clauses.length) {
        const clauses = document.createElement("div");
        clauses.className = "clauses";
        for (const clause of slot.clauses) {
          const chip = document.createElement("span");
          chip.className = "clause";
          chip.textContent = clause;
          clauses.appendChild(chip);
        }
        row.appendChild(clauses);
      }
      list.appendChild(row);
    }
    box.appendChild(list);
  }

  for (const hold of holds) {
    box.appendChild(subhead("체공 지시"));
    const line = document.createElement("div");
    line.className = "rec-line";
    line.textContent = hold.phraseology;
    box.appendChild(line);
  }

  if (route) {
    box.appendChild(subhead("복귀 경로"));
    const line = document.createElement("div");
    line.className = "rec-line";
    line.textContent = route.clearance;
    box.appendChild(line);
    const meta = document.createElement("p");
    meta.className = "rec-why";
    meta.textContent = `${route.total_nm.toFixed(1)} NM · 우회 ${route.detour_nm.toFixed(1)} NM`;
    box.appendChild(meta);
  }
}

function subhead(text) {
  const element = document.createElement("h3");
  element.className = "subhead";
  element.textContent = text;
  return element;
}

function drawStep() {
  const steps = state.scenario?.steps || [];
  const now = elapsed();
  let current = null;
  for (const step of steps) if (step.t_s <= now) current = step;

  $("stepnow").textContent = current ? `${current.n}. ${current.name}` : "대기 중";
  $("stepdetail").textContent = current?.detail || "";
  const clauses = $("stepclauses");
  clauses.textContent = "";
  for (const clause of current?.clauses || []) {
    const chip = document.createElement("span");
    chip.className = "clause";
    chip.textContent = clause;
    clauses.appendChild(chip);
  }
  for (const button of $("steps").children) {
    button.setAttribute("aria-current", current && +button.dataset.n === current.n ? "true" : "false");
  }
}

/* ------------------------------------------------------------------ 그리기 */

/** 지금 위치를 꼬리에 넣는다. 같은 시각을 두 번 넣지 않는다. */
function recordTrails() {
  const now = elapsed();
  for (const aircraft of state.session?.traffic || []) {
    const trail = state.trails.get(aircraft.aircraft_id) || [];
    const last = trail[trail.length - 1];
    if (last && last.t >= now) continue;
    trail.push({ t: now, x: aircraft.x_nm, y: aircraft.y_nm });
    if (trail.length > TRAIL_POINTS) trail.shift();
    state.trails.set(aircraft.aircraft_id, trail);
  }
  // 화면에서 사라진 항공기의 꼬리는 지운다. 남겨 두면 착륙한 항공기의 자취가
  // 계속 떠 있게 되고, 그것은 없는 교통이다.
  const present = new Set((state.session?.traffic || []).map((a) => a.aircraft_id));
  for (const id of [...state.trails.keys()]) {
    if (!present.has(id)) state.trails.delete(id);
  }
}

function render() {
  const session = state.session;
  $("clock").textContent = hhmmss(elapsed());
  $("duration").textContent = hhmmss(duration());
  $("stage").textContent = session?.stage || "READY";
  $("stage").className = `chip${
    session?.stage === "CONFLICT_DETECTED"
      ? " hot"
      : session?.active_exception_count
        ? " warm"
        : ""
  }`;
  $("scenario").textContent = session?.scenario_id || state.scenario?.scenario_id || "—";

  const fraction = Math.min(1, elapsed() / duration());
  $("fill").style.width = `${fraction * 100}%`;
  $("head").style.left = `${fraction * 100}%`;

  recordTrails();
  drawBackground();
  drawTraffic();
  drawQueue();
  drawNextCommand();
  renderDeviation(session?.deviation);
  drawDetail();
  drawRecommendation();
  drawAdvisory();
  drawStep();
}

/* ------------------------------------------------------------------ 조작 */

function buildControls() {
  const layers = $("layers");
  for (const [key, label] of LAYERS) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.setAttribute("aria-pressed", String(state.layers[key]));
    button.addEventListener("click", () => {
      state.layers[key] = !state.layers[key];
      button.setAttribute("aria-pressed", String(state.layers[key]));
      render();
    });
    layers.appendChild(button);
  }

  const ranges = $("ranges");
  for (const nm of RANGES) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${nm}`;
    button.setAttribute("aria-pressed", String(nm === state.view.halfNm));
    button.addEventListener("click", () => {
      state.view.halfNm = nm;
      for (const other of ranges.children) {
        other.setAttribute("aria-pressed", String(other === button));
      }
      fitView();
      render();
    });
    ranges.appendChild(button);
  }

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

  wireDecision();
  $("play").addEventListener("click", () => (state.playing ? stop() : start()));
  $("reset").addEventListener("click", () => seek(0));

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
  });

  window.addEventListener("resize", () => {
    fitView();
    render();
  });
}

function buildSteps() {
  const bar = $("steps");
  bar.textContent = "";
  const cues = $("cues");
  cues.textContent = "";
  // 관제사의 판단이 필요한 지점만 눈금을 굵게 한다.
  const key = new Set([7, 9, 10, 11]);

  for (const step of state.scenario?.steps || []) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.n = String(step.n);
    button.textContent = `${step.n}. ${step.name}`;
    button.title = step.detail || "";
    button.addEventListener("click", () => seek(step.t_s));
    bar.appendChild(button);

    const tick = document.createElement("i");
    tick.style.left = `${(step.t_s / duration()) * 100}%`;
    if (key.has(step.n)) tick.className = "key";
    cues.appendChild(tick);
  }
}

/* ------------------------------------------------------------------ 시작 */

async function boot() {
  buildControls();
  fitView();
  try {
    const [geometry, scenario] = await Promise.all([get(GEOMETRY), get(SCENARIO)]);
    state.geometry = geometry;
    state.scenario = scenario;
    if (geometry.centre) {
      const [cx, cy] = toLocal(geometry.centre[0], geometry.centre[1]);
      state.view.cx = cx;
      state.view.cy = cy;
    }
    buildSteps();
    state.session = await get(API);
    state.advisory = await get(ADVISORY).catch(() => null);
    setLink(true);
  } catch (error) {
    setLink(false);
    console.error(error);
  }
  fitView();
  render();
}

boot();
