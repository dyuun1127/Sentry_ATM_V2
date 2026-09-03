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
    command: "",
    code: "DECIDE · T+90",
    label: "관제사 판단 입력",
  },
  DECISION_ACCEPTED: {
    command: "APPLY_APPROVED_MANEUVER",
    code: "APPLY · T+90",
    label: "승인 기동 적용",
  },
  DECISION_MODIFIED: {
    command: "REVALIDATE_MODIFIED_MANEUVER",
    code: "REVALIDATE · T+90",
    label: "수정 기동 격리 검증",
  },
  MODIFICATION_REVALIDATED: {
    command: "RESET",
    code: "RESET · T+00",
    label: "검증 결과 보존 후 새 Run",
  },
  DECISION_REJECTED: {
    command: "RESET",
    code: "RESET · T+00",
    label: "거절 기록 후 새 Run 시작",
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
  deviationPanel: document.querySelector("[data-deviation-panel]"),
  deviationAircraft: document.querySelector("[data-deviation-aircraft]"),
  deviationEntry: document.querySelector("[data-deviation-entry]"),
  deviationActualAltitude: document.querySelector("[data-deviation-actual-altitude]"),
  deviationExpectedAltitude: document.querySelector("[data-deviation-expected-altitude]"),
  deviationVertical: document.querySelector("[data-deviation-vertical]"),
  deviationActualHeading: document.querySelector("[data-deviation-actual-heading]"),
  deviationExpectedHeading: document.querySelector("[data-deviation-expected-heading]"),
  deviationHeading: document.querySelector("[data-deviation-heading]"),
  deviationLateral: document.querySelector("[data-deviation-lateral]"),
  deviationTime: document.querySelector("[data-deviation-time]"),
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
  decisionAuditDetail: document.querySelector("[data-decision-audit-detail]"),
  decisionAuditSummary: document.querySelector("[data-decision-audit-summary]"),
  decisionRationale: document.querySelector("[data-decision-rationale]"),
  modifiedRevalidation: document.querySelector("[data-modified-revalidation]"),
  modifiedVerdict: document.querySelector("[data-modified-verdict]"),
  modifiedSeparation: document.querySelector("[data-modified-separation]"),
  modifiedApplyGate: document.querySelector("[data-modified-apply-gate]"),
  modifiedEvidence: document.querySelector("[data-modified-evidence]"),
  decisionActions: document.querySelector("[data-decision-actions]"),
  decisionActionButtons: [...document.querySelectorAll("[data-decision-action]")],
  decisionForm: document.querySelector("[data-decision-form]"),
  decisionFormTitle: document.querySelector("[data-decision-form-title]"),
  decisionCancel: document.querySelector("[data-decision-cancel]"),
  modifiedFields: document.querySelector("[data-modified-fields]"),
  modifiedType: document.querySelector("[data-modified-type]"),
  modifiedValueLabel: document.querySelector("[data-modified-value-label]"),
  modifiedValue: document.querySelector("[data-modified-value]"),
  modifiedUnit: document.querySelector("[data-modified-unit]"),
  decisionRationaleInput: document.querySelector("[data-decision-rationale-input]"),
  decisionSubmit: document.querySelector("[data-decision-submit]"),
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
  candidatePanel: document.querySelector("[data-candidate-panel]"),
  candidateBody: document.querySelector("[data-candidate-body]"),
  toast: document.querySelector("[data-toast]"),
};

let currentSession = null;
let requestBusy = false;
let decisionMode = null;

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

function formatSignedNumber(value, digits = 0) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "—";
  }
  return `${numeric > 0 ? "+" : ""}${formatNumber(numeric, digits)}`;
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

function renderDeviation(deviation) {
  elements.deviationPanel.hidden = !deviation;
  if (!deviation) {
    return;
  }
  elements.deviationAircraft.textContent = deviation.aircraft_id ?? "—";
  elements.deviationEntry.textContent = deviation.expected_entry_point ?? "—";
  elements.deviationActualAltitude.textContent = formatNumber(deviation.actual_altitude_ft);
  elements.deviationExpectedAltitude.textContent = formatNumber(deviation.expected_altitude_ft);
  elements.deviationVertical.textContent = formatSignedNumber(deviation.vertical_deviation_ft);
  elements.deviationActualHeading.textContent = formatNumber(deviation.actual_heading_deg);
  elements.deviationExpectedHeading.textContent = formatNumber(deviation.expected_heading_deg);
  elements.deviationHeading.textContent = formatSignedNumber(deviation.heading_deviation_deg);
  elements.deviationLateral.textContent = formatNumber(deviation.lateral_deviation_nm, 1);
  elements.deviationTime.textContent = formatSignedNumber(deviation.time_deviation_seconds);
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

function comparisonManeuverText(candidate) {
  return maneuverText({
    maneuver_type: candidate.maneuver_type,
    target_altitude_ft: candidate.target_altitude_ft,
    target_heading_deg: candidate.target_heading_deg,
    target_ground_speed_kt: candidate.target_ground_speed_kt,
    delay_seconds: candidate.delay_seconds,
    target_sequence_position: candidate.target_sequence_position,
  });
}

function candidateConstraintText(candidate) {
  const evidence = [];
  for (const pair of candidate.secondary_conflict_aircraft_ids ?? []) {
    evidence.push(`SECONDARY ${pair.join("/")}`);
  }
  for (const ruleId of candidate.rule_violation_ids ?? []) {
    evidence.push(`RULE ${ruleId}`);
  }
  if (!candidate.performance_feasible) {
    evidence.push("PERFORMANCE LIMIT");
  }
  if (evidence.length === 0) {
    return candidate.primary_conflict_status === "SAFE" ? "NONE" : "PRIMARY REMAINS";
  }
  return evidence.join(" · ");
}

function renderCandidateComparisons(candidates) {
  const items = Array.isArray(candidates) ? candidates : [];
  elements.candidatePanel.hidden = items.length === 0;
  elements.candidateBody.replaceChildren();
  for (const candidate of items) {
    const row = document.createElement("tr");
    row.classList.toggle("is-recommended", Boolean(candidate.recommended));

    const idCell = document.createElement("td");
    const id = document.createElement("strong");
    id.textContent = candidate.candidate_id ?? "—";
    idCell.append(id);
    if (candidate.recommended) {
      const badge = document.createElement("span");
      badge.className = "recommended-badge";
      badge.textContent = "RECOMMENDED";
      idCell.append(badge);
    }

    const verdictCell = document.createElement("td");
    const verdict = document.createElement("span");
    verdict.className = `candidate-verdict ${String(candidate.verdict).toLowerCase()}`;
    verdict.textContent = candidate.verdict ?? "UNKNOWN";
    verdictCell.append(verdict);

    row.append(
      idCell,
      cell(candidate.target_aircraft_id ?? "—"),
      cell(comparisonManeuverText(candidate)),
      cell(
        `H ${formatNumber(candidate.primary_horizontal_separation_nm, 2)} NM · V ${formatNumber(
          candidate.primary_vertical_separation_ft,
        )} FT`,
      ),
      cell(candidateConstraintText(candidate), "candidate-constraint"),
      cell(formatNumber(candidate.operational_cost_score), "candidate-cost"),
      verdictCell,
    );
    elements.candidateBody.append(row);
  }
}

const MANEUVER_INPUT = {
  ALTITUDE: { label: "TARGET ALTITUDE", unit: "FT", value: 8800, min: 0, max: null, step: 100 },
  HEADING: { label: "TARGET HEADING", unit: "DEG", value: 190, min: 0, max: 359, step: 1 },
  SPEED: { label: "TARGET SPEED", unit: "KT", value: 230, min: 1, max: null, step: 1 },
  ENTRY_DELAY: { label: "ENTRY DELAY", unit: "SEC", value: 30, min: 1, max: null, step: 1 },
  SEQUENCE_CHANGE: { label: "SEQUENCE", unit: "POS", value: 2, min: 1, max: null, step: 1 },
};

function updateManeuverInput() {
  const config = MANEUVER_INPUT[elements.modifiedType.value] ?? MANEUVER_INPUT.ALTITUDE;
  elements.modifiedValueLabel.textContent = config.label;
  elements.modifiedUnit.textContent = config.unit;
  elements.modifiedValue.value = String(config.value);
  elements.modifiedValue.min = String(config.min);
  elements.modifiedValue.step = String(config.step);
  if (config.max === null) {
    elements.modifiedValue.removeAttribute("max");
  } else {
    elements.modifiedValue.max = String(config.max);
  }
}

function setDecisionMode(mode) {
  decisionMode = mode;
  elements.decisionForm.hidden = !mode;
  if (!mode) {
    elements.decisionForm.reset();
    elements.modifiedType.value = "ALTITUDE";
    updateManeuverInput();
    return;
  }
  const modifying = mode === "MODIFY";
  elements.modifiedFields.hidden = !modifying;
  elements.decisionFormTitle.textContent = modifying ? "추천 기동 수정" : "추천안 거절";
  elements.decisionSubmit.textContent = modifying ? "수정 결정 기록" : "거절 결정 기록";
  elements.decisionRationaleInput.placeholder = modifying
    ? "추천 기동을 변경하는 이유를 입력하세요."
    : "추천안을 거절하는 이유를 입력하세요.";
  elements.decisionRationaleInput.focus();
}

function buildModifiedManeuver() {
  const maneuverType = elements.modifiedType.value;
  const numericValue = Number(elements.modifiedValue.value);
  const maneuver = {
    maneuver_type: maneuverType,
    target_heading_deg: null,
    target_altitude_ft: null,
    target_ground_speed_kt: null,
    delay_seconds: null,
    target_sequence_position: null,
  };
  const fieldByType = {
    HEADING: "target_heading_deg",
    ALTITUDE: "target_altitude_ft",
    SPEED: "target_ground_speed_kt",
    ENTRY_DELAY: "delay_seconds",
    SEQUENCE_CHANGE: "target_sequence_position",
  };
  maneuver[fieldByType[maneuverType]] = maneuverType === "SEQUENCE_CHANGE"
    ? Math.trunc(numericValue)
    : numericValue;
  return maneuver;
}

function renderDecisionWorkflow(session, latestDecision) {
  const awaitingDecision = session.stage === "RECOMMENDATION_AVAILABLE";
  elements.decisionActions.hidden = !awaitingDecision;
  elements.decisionAuditDetail.hidden = !latestDecision;
  const modifiedValidation = session.modified_revalidation;
  elements.modifiedRevalidation.hidden = !modifiedValidation;
  if (!awaitingDecision && decisionMode) {
    setDecisionMode(null);
  }
  if (!latestDecision) {
    return;
  }
  const modified = latestDecision.modified_maneuver;
  const outcome = latestDecision.decision_type === "MODIFY"
    ? `${maneuverText(modified)} · REVALIDATION REQUIRED`
    : latestDecision.decision_type === "REJECT"
      ? "NO MANEUVER AUTHORIZED"
      : "ORIGINAL CANDIDATE AUTHORIZED";
  elements.decisionAuditSummary.textContent = outcome;
  elements.decisionRationale.textContent = latestDecision.rationale ?? "No rationale required.";
  if (!modifiedValidation) {
    return;
  }
  elements.modifiedVerdict.textContent = modifiedValidation.verdict ?? "UNKNOWN";
  elements.modifiedSeparation.textContent = `H ${formatNumber(
    modifiedValidation.primary_horizontal_separation_nm,
    2,
  )} NM · V ${formatNumber(modifiedValidation.primary_vertical_separation_ft)} FT`;
  elements.modifiedApplyGate.textContent = modifiedValidation.safe_to_apply
    ? "SAFE · NOT YET APPLIED"
    : "BLOCKED";
  const constraints = [];
  for (const pair of modifiedValidation.secondary_conflict_aircraft_ids ?? []) {
    constraints.push(`SECONDARY ${pair.join("/")}`);
  }
  for (const ruleId of modifiedValidation.rule_violation_ids ?? []) {
    constraints.push(`RULE ${ruleId}`);
  }
  if (!modifiedValidation.performance_feasible) {
    constraints.push("PERFORMANCE LIMIT");
  }
  elements.modifiedEvidence.textContent = constraints.length > 0
    ? constraints.join(" · ")
    : (modifiedValidation.reason_codes ?? []).join(" · ");
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
    renderDecisionWorkflow(session, null);
    return;
  }

  const conflict = primary.safety?.primary_conflict;
  const latestDecision = session.controller_decision?.entries?.at(-1);
  const revalidation = session.revalidation;
  const modifiedValidation = session.modified_revalidation;
  elements.decisionStatus.textContent = revalidation?.resolved
    ? "POST-ACTION SAFE"
    : modifiedValidation
      ? modifiedValidation.safe_to_apply
        ? "MODIFIED · SAFE TO APPLY"
        : "MODIFIED · VALIDATION FAILED"
    : latestDecision?.decision_type === "MODIFY"
      ? "MODIFIED · REVALIDATION REQUIRED"
      : latestDecision?.decision_type === "REJECT"
        ? "REJECTED BY CONTROLLER"
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
  renderDecisionWorkflow(session, latestDecision);
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
  const modifiedValidation = session.modified_revalidation;
  const after = session.revalidation ?? modifiedValidation ?? candidateConflict;
  const afterIsSafe = session.revalidation
    ? session.revalidation.resolved
    : modifiedValidation
      ? modifiedValidation.safe_to_apply
      : Boolean(candidateConflict);
  elements.afterCard.classList.toggle(
    "is-safe",
    Boolean(after && afterIsSafe),
  );
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
  } else if (modifiedValidation) {
    elements.afterLabel.textContent = "AFTER · MODIFIED REVALIDATION";
    elements.afterOutcome.textContent = modifiedValidation.safe_to_apply
      ? "SAFE · NOT YET APPLIED"
      : modifiedValidation.verdict;
    elements.afterSeparation.textContent = `H ${formatNumber(
      modifiedValidation.primary_horizontal_separation_nm,
      2,
    )} NM · V ${formatNumber(modifiedValidation.primary_vertical_separation_ft)} FT`;
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
  elements.resetCommand.hidden = stage === "READY" || config?.command === "RESET";
  elements.primaryCommand.disabled = requestBusy || !config;
  elements.resetCommand.disabled = requestBusy;
}

function setRequestBusy(value) {
  requestBusy = value;
  document.body.dataset.requestBusy = String(value);
  elements.refresh.disabled = value;
  elements.primaryCommand.disabled = value || !elements.primaryCommand.dataset.command;
  elements.resetCommand.disabled = value;
  elements.decisionSubmit.disabled = value;
  for (const button of elements.decisionActionButtons) {
    button.disabled = value;
  }
  elements.primaryCommand.setAttribute("aria-busy", String(value));
  if (currentSession) {
    updateCommandControl(currentSession.stage);
  }
}

function renderStage(stage) {
  const normalized = {
    DEVIATION_DETECTED: "MONITORING",
    DECISION_MODIFIED: "DECISION_ACCEPTED",
    MODIFICATION_REVALIDATED: "DECISION_ACCEPTED",
    DECISION_REJECTED: "DECISION_ACCEPTED",
  }[stage] ?? stage;
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
  renderDeviation(session.deviation);
  renderStage(String(session.stage ?? "READY"));
  renderExceptionQueue(session.exception_queue);
  renderDecisionSupport(session);
  renderConflictExplainability(session);
  renderCandidateComparisons(session.candidate_comparisons);
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

async function executeCommand(command, fields = {}) {
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
      body: JSON.stringify({ command, ...fields }),
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
for (const button of elements.decisionActionButtons) {
  button.addEventListener("click", () => {
    const action = button.dataset.decisionAction;
    if (action === "ACCEPT") {
      executeCommand("ACCEPT_RECOMMENDATION");
    } else {
      setDecisionMode(action);
    }
  });
}
elements.modifiedType.addEventListener("change", updateManeuverInput);
elements.decisionCancel.addEventListener("click", () => setDecisionMode(null));
elements.decisionForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!decisionMode || !elements.decisionForm.reportValidity()) {
    return;
  }
  const rationale = elements.decisionRationaleInput.value.trim();
  if (decisionMode === "MODIFY") {
    executeCommand("MODIFY_RECOMMENDATION", {
      rationale,
      modified_maneuver: buildModifiedManeuver(),
    });
  } else {
    executeCommand("REJECT_RECOMMENDATION", { rationale });
  }
});
elements.resetCommand.addEventListener("click", () => executeCommand("RESET"));
updateManeuverInput();
loadSession();
