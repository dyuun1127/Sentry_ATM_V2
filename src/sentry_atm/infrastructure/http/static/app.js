"use strict";

const SESSION_ENDPOINT = "/api/v1/golden-demo/session";
const STAGE_ORDER = [
  "READY",
  "MONITORING",
  "CONFLICT_DETECTED",
  "RECOMMENDATION_AVAILABLE",
  "DECISION_ACCEPTED",
  "CONFLICT_RESOLVED",
];

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
  trafficBody: document.querySelector("[data-traffic-body]"),
  stageItems: [...document.querySelectorAll("[data-stage-key]")],
  sessionId: document.querySelector("[data-session-id]"),
  refresh: document.querySelector("[data-refresh]"),
  toast: document.querySelector("[data-toast]"),
};

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

function renderAircraftMap(traffic) {
  elements.aircraftLayer.replaceChildren();
  for (const aircraft of traffic) {
    const track = document.createElement("div");
    track.className = `aircraft-track${isMilitary(aircraft) ? " military" : ""}`;
    const x = Math.max(-25, Math.min(25, Number(aircraft.x_nm)));
    const y = Math.max(-25, Math.min(25, Number(aircraft.y_nm)));
    track.style.left = `${50 + x * 1.6}%`;
    track.style.top = `${50 - y * 1.6}%`;

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
}

function showError(message) {
  elements.toast.textContent = message;
  elements.toast.hidden = false;
}

async function loadSession() {
  elements.refresh.disabled = true;
  setConnection("loading", "연결 중");
  elements.toast.hidden = true;
  try {
    const response = await fetch(SESSION_ENDPOINT, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    renderSession(await response.json());
    setConnection("online", "API ONLINE");
  } catch (error) {
    setConnection("error", "API OFFLINE");
    showError(`세션 데이터를 불러오지 못했습니다: ${error.message}`);
  } finally {
    elements.refresh.disabled = false;
  }
}

elements.refresh.addEventListener("click", loadSession);
loadSession();
