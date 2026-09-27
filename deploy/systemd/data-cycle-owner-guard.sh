#!/usr/bin/env bash
# Общий signal/EXIT guard для executor owner и detached Compose stages.

data_cycle_claim_attempted=0
data_cycle_recovery_required=0

data_cycle_mark_claim_attempted() {
  data_cycle_claim_attempted=1
}

data_cycle_mark_recovery_required() {
  data_cycle_recovery_required=1
}

data_cycle_should_defer_terminal_failure() {
  # После claim detached stage мог пережить клиента; освобождает слот host recovery.
  (( data_cycle_recovery_required != 0 || data_cycle_claim_attempted != 0 ))
}

data_cycle_handle_signal() {
  local exit_status="$1"
  if (( data_cycle_claim_attempted != 0 )); then
    data_cycle_mark_recovery_required
  fi
  exit "${exit_status}"
}

data_cycle_heartbeat_loop() {
  local stage_pid="$1"
  local heartbeat_ticks=0
  while kill -0 "${stage_pid}" 2>/dev/null; do
    sleep 1
    if ! kill -0 "${stage_pid}" 2>/dev/null; then
      return 0
    fi
    heartbeat_ticks=$((heartbeat_ticks + 1))
    if (( heartbeat_ticks >= 30 )); then
      heartbeat_ticks=0
      if ! control heartbeat --run-id "${SF_WORKER_RUN_ID}"; then
        echo "Data Cycle heartbeat failed; stopping the active stage" >&2
        kill -TERM "${stage_pid}" 2>/dev/null || true
        return 75
      fi
    fi
  done
  return 0
}

data_cycle_run_with_heartbeat() {
  "$@" &
  local stage_pid=$!
  data_cycle_heartbeat_loop "${stage_pid}" &
  local heartbeat_pid=$!
  local stage_status=0
  local heartbeat_status=0

  if wait "${stage_pid}"; then
    stage_status=0
  else
    stage_status=$?
    data_cycle_mark_recovery_required
  fi

  kill -TERM "${heartbeat_pid}" 2>/dev/null || true
  if wait "${heartbeat_pid}"; then
    heartbeat_status=0
  else
    heartbeat_status=$?
  fi
  if (( heartbeat_status == 75 )); then
    data_cycle_mark_recovery_required
    return 1
  fi
  return "${stage_status}"
}
