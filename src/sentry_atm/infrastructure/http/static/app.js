"use strict";

const SESSION_ENDPOINT = "/api/v1/golden-demo/session";
const COMMAND_ENDPOINT = "/api/v1/golden-demo/session/commands";
const STAGE_ORDER = [
  "READY",
  "MONITORING",
  "CONFLICT_DETECTED",
  "RECOMMENDATION_AVAILABLE",
  "DECISION_ACCEPTED",
  "CONFLICT_RESOLVED",
];
const COMMAND_BY_STAGE = {
  READY: { command: "START", code: "START · T+00", label: "감시 시작" },
  MONITORING: {
    command: "ADVANCE_TO_CONFLICT",
    code: "ADVANCE · T+70",
    label: "충돌 시점으로 진행",
  },
  CONFLICT_DETECTED: {
    command: "GENERATE_RECOMMENDATION",
    code: "PREDICT · T+75",
    label: "대응 후보 생성",
  },
  RECOMMENDATION_AVAILABLE: {
    command: "ACCEPT_RECOMMENDATION",
    code: "ACCEPT · T+90",
    label: "추천안 승인 기록",
  },
  DECISION_ACCEPTED: {
    command: "APPLY_APPROVED_MANEUVER",
    code: "APPLY · T+90",
    label: "승인 기동 적용",
  },
  CONFLICT_RESOLVED: {
    command: "RESET",
    code: "RESET · T+00",
    label: "새 Run 시작",
  },
};

const elements = {
  connection: document.querySelector("[data-connection-status]"),
  connectionLabel: document.querySelector("[data-connection-label]"),
  simulationTime: document.querySelector("[data-simulation-time]"),
  runNumber: document.querySelector("[data-run-number]"),
  sessionStage: document.querySelector("[data-session-stage]"),
  trafficCount: document.querySelector("[data-traffic-count]"),
  exceptionCount: document.querySelector("[data-exception-count]"),
  queueCount: document.querySelector("[data-queue-count]"),
  elapsedTime: document.querySelector("[data-elapsed-time]"),
  clockState: document.querySelector("[data-clock-state]"),
  aircraftLayer: document.querySelector("[data-aircraft-layer]"),
  conflictOverlay: document.querySelector("[data-conflict-overlay]"),
  conflictLine: document.querySelector("[data-conflict-line]"),
  conflictPointA: document.querySelector("[data-conflict-point-a]"),
  conflictPointB: document.querySelector("[data-conflict-point-b]"),
  trafficBody: document.querySelector("[data-traffic-body]"),
  stageItems: [...document.querySelectorAll("[data-stage-key]")],
  sessionId: document.querySelector("[data-session-id]"),
  refresh: document.querySelector("[data-refresh]"),
  resetCommand: document.querySelector("[data-reset-command]"),
  primaryCommand: document.querySelector("[data-primary-command]"),
  commandCode: document.querySelector("[data-command-code]"),
  commandLabel: document.querySelector("[data-command-label]"),
  exceptionEmpty: document.querySelector("[data-exception-empty]"),
  exceptionList: document.querySelector("[data-exception-list]"),
  decisionEmpty: document.querySelector("[data-decision-empty]"),
  decisionCard: document.querySelector("[data-decision-card]"),
  decisionStatus: document.querySelector("[data-decision-status]"),
  decisionRank: document.querySelector("[data-decision-rank]"),
  decisionTarget: document.querySelector("[data-decision-target]"),
  decisionManeuver: document.querySelector("[data-decision-maneuver]"),
  safetyVerdict: document.querySelector("[data-safety-verdict]"),
  safetyHorizontal: document.querySelector("[data-safety-horizontal]"),
  safetyVertical: document.querySelector("[data-safety-vertical]"),
  decisionAudit: document.querySelector("[data-decision-audit]"),
  decisionExplanation: document.querySelector("[data-decision-explanation]"),
  revalidation: document.querySelector("[data-revalidation]"),
  revalidationResult: document.querySelector("[data-revalidation-result]"),
  conflictExplainability: document.querySelector("[data-conflict-explainability]"),
  conflictPair: document.querySelector("[data-conflict-pair]"),
  conflictStatus: document.querySelector("[data-conflict-status]"),
  conflictRiskScore: document.querySelector("[data-conflict-risk-score]"),
  conflictRiskLevel: document.querySelector("[data-conflict-risk-level]"),
  conflictTcpa: document.querySelector("[data-conflict-tcpa]"),
  conflictRule: document.querySelector("[data-conflict-rule]"),
  conflictHorizontal: document.querySelector("[data-conflict-horizontal]"),
  conflictHorizontalThreshold: document.querySelector("[data-conflict-horizontal-threshold]"),
  conflictHorizontalRatio: document.querySelector("[data-conflict-horizontal-ratio]"),
  conflictVertical: document.querySelector("[data-conflict-vertical]"),
  conflictVerticalThreshold: document.querySelector("[data-conflict-vertical-threshold]"),
  conflictVerticalRatio: document.querySelector("[data-conflict-vertical-ratio]"),
  conflictReasons: document.querySelector("[data-conflict-reasons]"),
  beforeOutcome: document.querySelector("[data-before-outcome]"),
  beforeSeparation: document.querySelector("[data-before-separation]"),
  afterCard: document.querySelector("[data-after-card]"),
  afterLabel: document.querySelector("[data-after-label]"),
  afterOutcome: document.querySelector("[data-after-outcome]"),
  afterSeparation: document.querySelector("[data-after-separation]"),
  toast: document.querySelector("[data-toast]"),
};

let currentSession = null;
let requestBusy = false;

function setConnection(status, label) {
  elements.connection.dataset.connectionStatus = status;
  elements.connectionLabel.textContent = label;
}

function formatSimulationTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--:--:--";
  }
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatNumber(value, digits = 0) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "—";
  }
  return numeric.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function isMilitary(aircraft) {
  return String(aircraft.aircraft_id).startsWith("MIL-");
}

function mapPosition(aircraft) {
  const x = Math.max(-25, Math.min(25, Number(aircraft.x_nm)));
  const y = Math.max(-25, Math.min(25, Number(aircraft.y_nm)));
  return { left: 50 + x * 1.6, top: 50 - y * 1.6 };
}

function renderConflictOverlay(traffic) {
  const conflictIds = currentSession?.primary_conflict?.aircraft_ids ?? [];
  const focused = conflictIds.map((aircraftId) =>
    traffic.find((aircraft) => aircraft.aircraft_id === aircraftId),
  );
  if (focused.length !== 2 || focused.some((aircraft) => !aircraft)) {
    elements.conflictOverlay.hidden = true;
    return;
  }
  const first = mapPosition(focused[0]);
  const second = mapPosition(focused[1]);
  for (const [name, value] of Object.entries({
    x1: first.left,
    y1: first.top,
    x2: second.left,
    y2: second.top,
  })) {
    elements.conflictLine.setAttribute(name, String(value));
  }
  elements.conflictPointA.setAttribute("cx", String(first.left));
  elements.conflictPointA.setAttribute("cy", String(first.top));
  elements.conflictPointB.setAttribute("cx", String(second.left));
  elements.conflictPointB.setAttribute("cy", String(second.top));
  elements.conflictOverlay.hidden = false;
}

function renderAircraftMap(traffic) {
  elements.aircraftLayer.replaceChildren();
  const conflictIds = currentSession?.primary_conflict?.aircraft_ids ?? [];
  for (const aircraft of traffic) {
    const track = document.createElement("div");
    track.className = `aircraft-track${isMilitary(aircraft) ? " military" : ""}`;
    track.classList.toggle("conflict-focus", conflictIds.includes(aircraft.aircraft_id));
    const position = mapPosition(aircraft);
    track.style.left = `${position.left}%`;
    track.style.top = `${position.top}%`;

    const symbol = document.createElement("span");
    symbol.className = "track-symbol";
    symbol.style.setProperty("--heading", `${Number(aircraft.heading_deg) - 90}deg`);

    const label = document.createElement("span");
    label.className = "track-label";
    const callsign = document.createElement("strong");
    callsign.textContent = aircraft.aircraft_id;
    const detail = document.createElement("span");
    detail.textContent = `${formatNumber(aircraft.altitude_ft)}FT · ${formatNumber(aircraft.ground_speed_kt)}KT`;
    label.append(callsign, detail);
    track.append(symbol, label);
    elements.aircraftLayer.append(track);
  }
  renderConflictOverlay(traffic);
}

function cell(text, className = "") {
  const item = document.createElement("td");
  item.textContent = text;
  if (className) {
    item.className = className;
  }
  return item;
}

function renderTrafficTable(traffic) {
  elements.trafficBody.replaceChildren();
  for (const aircraft of traffic) {
    const row = document.createElement("tr");
    row.append(cell(aircraft.aircraft_id));

    const typeCell = document.createElement("td");
    const type = document.createElement("span");
    type.className = `type-pill${isMilitary(aircraft) ? " military" : ""}`;
    type.textContent = aircraft.aircraft_type;
    typeCell.append(type);
    row.append(typeCell);

    row.append(
      cell(aircraft.flight_phase),
      cell(`${formatNumber(aircraft.altitude_ft)} FT`),
      cell(`${formatNumber(aircraft.ground_speed_kt)} KT`),
      cell(`${formatNumber(aircraft.heading_deg)}°`),
      cell(`${Number(aircraft.vertical_speed_fpm) >= 0 ? "+" : ""}${formatNumber(aircraft.vertical_speed_fpm)} FPM`),
    );
    elements.trafficBody.append(row);
  }
}

function renderExceptionQueue(queue) {
  const items = Array.isArray(queue?.items)
    ? queue.items.filter((item) => item.status !== "RESOLVED")
    : [];
  elements.exceptionEmpty.hidden = items.length > 0;
  elements.exceptionList.hidden = items.length === 0;
  elements.exceptionList.replaceChildren();

  for (const item of items) {
    const card = document.createElement("article");
    card.className = "queue-item";

    const header = document.createElement("div");
    header.className = "queue-item-header";
    const subjects = document.createElement("strong");
    subjects.textContent = (item.subject_aircraft_ids ?? []).join(" / ");
    const severity = document.createElement("span");
    severity.className = `severity-badge ${String(item.severity).toLowerCase()}`;
    severity.textContent = item.severity ?? "ATTENTION";
    header.append(subjects, severity);

    const kind = document.createElement("p");
    kind.className = "queue-kind";
    kind.textContent = String(item.kind ?? "EXCEPTION").replaceAll("_", " ");

    const meta = document.createElement("div");
    meta.className = "queue-item-meta";
    const score = document.createElement("span");
    score.append("SCORE ");
    const scoreValue = document.createElement("b");
    scoreValue.textContent = formatNumber(item.score);
    score.append(scoreValue);
    const timing = document.createElement("span");
    timing.textContent = Number.isFinite(Number(item.tcpa_seconds))
      ? `TCPA ${formatNumber(item.tcpa_seconds)} SEC`
      : String((item.reason_codes ?? ["OPERATIONAL"])[0]).replaceAll("_", " ");
    meta.append(score, timing);

    card.append(header, kind, meta);
    elements.exceptionList.append(card);
  }
}

function maneuverText(maneuver) {
  if (!maneuver) {
    return "MANEUVER UNAVAILABLE";
  }
  const labels = {
    ALTITUDE: `${formatNumber(maneuver.target_altitude_ft)} FT`,
    HEADING: `${formatNumber(maneuver.target_heading_deg)}°`,
    SPEED: `${formatNumber(maneuver.target_ground_speed_kt)} KT`,
    ENTRY_DELAY: `${formatNumber(maneuver.delay_seconds)} SEC`,
    SEQUENCE_CHANGE: `POSITION ${formatNumber(maneuver.target_sequence_position)}`,
  };
  return `${maneuver.maneuver_type} ${labels[maneuver.maneuver_type] ?? ""}`.trim();
}

function renderDecisionSupport(session) {
  const recommendationSet = session.recommendation;
  const recommendations = Array.isArray(recommendationSet?.recommendations)
    ? recommendationSet.recommendations
    : [];
  const primary =
    recommendations.find(
      (item) => item.recommendation_id === recommendationSet?.primary_recommendation_id,
    ) ?? recommendations[0];

  elements.decisionEmpty.hidden = Boolean(primary);
  elements.decisionCard.hidden = !primary;
  if (!primary) {
    return;
  }

  const conflict = primary.safety?.primary_conflict;
  const latestDecision = session.controller_decision?.entries?.at(-1);
  const revalidation = session.revalidation;
  elements.decisionStatus.textContent = revalidation?.resolved
    ? "POST-ACTION SAFE"
    : `${primary.safety?.verdict ?? "UNKNOWN"} CANDIDATE`;
  elements.decisionRank.textContent = `RANK ${String(primary.rank ?? 0).padStart(2, "0")}`;
  elements.decisionTarget.textContent = primary.target_aircraft_id ?? "—";
  elements.decisionManeuver.textContent = maneuverText(primary.maneuver);
  elements.safetyVerdict.textContent = revalidation?.conflict_status ?? primary.safety?.verdict ?? "—";
  elements.safetyHorizontal.textContent = `${formatNumber(
    revalidation?.horizontal_separation_nm ?? conflict?.horizontal_separation_nm,
    2,
  )} NM`;
  elements.safetyVertical.textContent = `${formatNumber(
    revalidation?.vertical_separation_ft ?? conflict?.vertical_separation_ft,
  )} FT`;
  elements.decisionAudit.textContent = latestDecision?.decision_type ?? "PENDING";
  elements.decisionExplanation.textContent = primary.explanation ?? "";
  elements.revalidation.hidden = !revalidation;
  elements.revalidationResult.textContent = revalidation?.resolved ? "RESOLVED" : "RECHECK";
}

function primaryRecommendation(session) {
  const recommendationSet = session.recommendation;
  const recommendations = Array.isArray(recommendationSet?.recommendations)
    ? recommendationSet.recommendations
    : [];
  return (
    recommendations.find(
      (item) => item.recommendation_id === recommendationSet?.primary_recommendation_id,
    ) ?? recommendations[0]
  );
}

function setRatioBar(element, ratio) {
  const normalized = Math.max(0, Math.min(1, Number(ratio) / 1.25));
  element.style.width = `${normalized * 100}%`;
}

function renderConflictExplainability(session) {
  const conflict = session.primary_conflict;
  elements.conflictExplainability.hidden = !conflict;
  if (!conflict) {
    return;
  }

  elements.conflictPair.textContent = (conflict.aircraft_ids ?? []).join(" / ");
  elements.conflictStatus.textContent = conflict.status ?? "UNKNOWN";
  elements.conflictRiskScore.textContent = formatNumber(conflict.risk_score);
  elements.conflictRiskLevel.textContent = conflict.risk_level ?? "—";
  elements.conflictTcpa.textContent = formatNumber(conflict.tcpa_seconds);
  elements.conflictRule.textContent = `${conflict.rule_profile_id} · ${conflict.risk_policy_profile_id}`;
  elements.conflictHorizontal.textContent = formatNumber(conflict.horizontal_separation_nm, 2);
  elements.conflictHorizontalThreshold.textContent = formatNumber(
    conflict.horizontal_threshold_nm,
    2,
  );
  elements.conflictVertical.textContent = formatNumber(conflict.vertical_separation_ft);
  elements.conflictVerticalThreshold.textContent = formatNumber(conflict.vertical_threshold_ft);
  setRatioBar(elements.conflictHorizontalRatio, conflict.horizontal_separation_ratio);
  setRatioBar(elements.conflictVerticalRatio, conflict.vertical_separation_ratio);
  elements.conflictReasons.textContent = (conflict.risk_reason_codes ?? [])
    .map((code) => String(code).replaceAll("_", " "))
    .join(" · ");
  elements.beforeOutcome.textContent = conflict.status === "PREDICTED"
    ? "LOSS OF SEPARATION"
    : conflict.status;
  elements.beforeSeparation.textContent = `H ${formatNumber(
    conflict.horizontal_separation_nm,
    2,
  )} NM · V ${formatNumber(conflict.vertical_separation_ft)} FT · ${conflict.risk_level}`;

  const recommendation = primaryRecommendation(session);
  const candidateConflict = recommendation?.safety?.primary_conflict;
  const after = session.revalidation ?? candidateConflict;
  elements.afterCard.classList.toggle("is-safe", Boolean(after));
  if (session.revalidation) {
    elements.afterLabel.textContent = "AFTER · POST-ACTION REVALIDATION";
    elements.afterOutcome.textContent = session.revalidation.resolved
      ? "SEPARATION RESTORED"
      : session.revalidation.conflict_status;
    elements.afterSeparation.textContent = `H ${formatNumber(
      session.revalidation.horizontal_separation_nm,
      2,
    )} NM · V ${formatNumber(session.revalidation.vertical_separation_ft)} FT · ${
      session.revalidation.risk_level
    }`;
  } else if (candidateConflict) {
    elements.afterLabel.textContent = "AFTER · VALIDATED CANDIDATE";
    elements.afterOutcome.textContent = recommendation.safety?.verdict ?? "VALIDATED";
    elements.afterSeparation.textContent = `H ${formatNumber(
      candidateConflict.horizontal_separation_nm,
      2,
    )} NM · V ${formatNumber(candidateConflict.vertical_separation_ft)} FT`;
  } else {
    elements.afterLabel.textContent = "AFTER · AWAITING ACTION";
    elements.afterOutcome.textContent = "NOT YET VALIDATED";
    elements.afterSeparation.textContent = "추천 후보 생성 대기";
  }
}

function updateCommandControl(stage) {
  const config = COMMAND_BY_STAGE[stage];
  elements.primaryCommand.dataset.command = config?.command ?? "";
  elements.commandCode.textContent = config?.code ?? "NO AUTHORIZED COMMAND";
  elements.commandLabel.textContent = config?.label ?? "현재 단계 확인 필요";
  elements.resetCommand.hidden = stage === "READY" || stage === "CONFLICT_RESOLVED";
  elements.primaryCommand.disabled = requestBusy || !config;
  elements.resetCommand.disabled = requestBusy;
}

function setRequestBusy(value) {
  requestBusy = value;
  document.body.dataset.requestBusy = String(value);
  elements.refresh.disabled = value;
  elements.primaryCommand.disabled = value || !elements.primaryCommand.dataset.command;
  elements.resetCommand.disabled = value;
  elements.primaryCommand.setAttribute("aria-busy", String(value));
  if (currentSession) {
    updateCommandControl(currentSession.stage);
  }
}

function renderStage(stage) {
  const normalized = stage === "DEVIATION_DETECTED" ? "MONITORING" : stage;
  const currentIndex = STAGE_ORDER.indexOf(normalized);
  for (const item of elements.stageItems) {
    const itemIndex = STAGE_ORDER.indexOf(item.dataset.stageKey);
    item.classList.toggle("is-complete", itemIndex >= 0 && itemIndex < currentIndex);
    item.classList.toggle("is-current", itemIndex === currentIndex);
  }
}

function renderSession(session) {
  currentSession = session;
  const traffic = Array.isArray(session.traffic) ? session.traffic : [];
  elements.simulationTime.textContent = formatSimulationTime(session.simulation_time_utc);
  elements.runNumber.textContent = String(session.run_number ?? 0).padStart(2, "0");
  elements.sessionStage.textContent = String(session.stage ?? "UNKNOWN");
  elements.trafficCount.textContent = formatNumber(session.traffic_count);
  elements.exceptionCount.textContent = formatNumber(session.active_exception_count);
  elements.queueCount.textContent = String(session.active_exception_count ?? 0).padStart(2, "0");
  elements.elapsedTime.textContent = formatNumber(session.elapsed_seconds);
  elements.clockState.textContent = String(session.clock_state ?? "UNKNOWN");
  elements.sessionId.textContent = `SESSION ${session.session_id ?? "—"}`;
  renderAircraftMap(traffic);
  renderTrafficTable(traffic);
  renderStage(String(session.stage ?? "READY"));
  renderExceptionQueue(session.exception_queue);
  renderDecisionSupport(session);
  renderConflictExplainability(session);
  updateCommandControl(String(session.stage ?? "READY"));
}

function showToast(message, variant = "error") {
  elements.toast.textContent = message;
  elements.toast.dataset.variant = variant;
  elements.toast.hidden = false;
}

async function requestSession() {
  const response = await fetch(SESSION_ENDPOINT, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

async function loadSession() {
  if (requestBusy) {
    return;
  }
  setRequestBusy(true);
  setConnection("loading", "연결 중");
  elements.toast.hidden = true;
  try {
    renderSession(await requestSession());
    setConnection("online", "API ONLINE");
  } catch (error) {
    setConnection("error", "API OFFLINE");
    showToast(`세션 데이터를 불러오지 못했습니다: ${error.message}`);
  } finally {
    setRequestBusy(false);
  }
}

async function executeCommand(command) {
  if (requestBusy || !command) {
    return;
  }
  setRequestBusy(true);
  setConnection("loading", "COMMAND RUNNING");
  elements.toast.hidden = true;
  try {
    const response = await fetch(COMMAND_ENDPOINT, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ command }),
    });
    const payload = await response.json();
    if (!response.ok) {
      const error = new Error(payload.error?.message ?? `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    renderSession(payload);
    setConnection("online", "API ONLINE");
    showToast(`${command} 명령이 완료되었습니다.`, "success");
  } catch (error) {
    if (error.status === 409) {
      try {
        renderSession(await requestSession());
        setConnection("online", "API ONLINE");
      } catch {
        setConnection("error", "API OFFLINE");
      }
    } else if (!Number.isFinite(error.status)) {
      setConnection("error", "API OFFLINE");
    } else {
      setConnection("online", "API ONLINE");
    }
    showToast(`명령을 실행하지 못했습니다: ${error.message}`);
  } finally {
    setRequestBusy(false);
  }
}

elements.refresh.addEventListener("click", loadSession);
elements.primaryCommand.addEventListener("click", () => {
  executeCommand(elements.primaryCommand.dataset.command);
});
elements.resetCommand.addEventListener("click", () => executeCommand("RESET"));
loadSession();
