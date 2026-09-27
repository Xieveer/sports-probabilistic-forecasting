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

data_cycle_run_with_heartbeat() {
  "$@" &
  local stage_pid=$!
  local heartbeat_ticks=0
  while true; do
    if ! jobs -p | grep -qx "${stage_pid}"; then
      local stage_status=0
      if wait "${stage_pid}"; then
        stage_status=0
      else
        stage_status=$?
        data_cycle_mark_recovery_required
      fi
      return "${stage_status}"
    fi

    sleep 1
    heartbeat_ticks=$((heartbeat_ticks + 1))
    if (( heartbeat_ticks >= 30 )); then
      heartbeat_ticks=0
      if ! control heartbeat --run-id "${SF_WORKER_RUN_ID}"; then
        echo "Data Cycle heartbeat failed; stopping the active stage" >&2
        data_cycle_mark_recovery_required
        kill -TERM "${stage_pid}" 2>/dev/null || true
        wait "${stage_pid}" 2>/dev/null || true
        return 1
      fi
    fi
  done
}
