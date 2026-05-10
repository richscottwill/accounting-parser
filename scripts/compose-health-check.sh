#!/usr/bin/env bash
# compose-health-check.sh - phase-gate acceptance test.
#
# Asserts that `docker compose up -d` brings every service to a
# healthy state within a reasonable budget, and that both the
# liveness probe (/healthz) and the Prometheus scrape endpoint
# (/metrics) are reachable through the host-mapped port.
#
# Used by:
# - Richard to spot-check a fresh reference VM.
# - CI matrix smoke tests once the installer lands (P3.1).
# - Troubleshooting when the firm principal reports "nothing works."
#
# Exits non-zero if any service fails to go healthy within TIMEOUT,
# or if either HTTP probe fails.
#
# Environment:
#   GATE_NAME         - banner label (default "phase"). E.g. "Phase 2".
#   TIMEOUT_SECONDS   - upper bound for services to report healthy
#                       (default 300, covers first-boot image pulls).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

GATE_NAME="${GATE_NAME:-phase}"
TIMEOUT="${TIMEOUT_SECONDS:-300}"   # 5 min default; first boot downloads ~1 GB of images
POLL_INTERVAL=5

echo "==> Bringing stack up..."
docker compose up -d

echo "==> Waiting up to ${TIMEOUT}s for services to report healthy..."
deadline=$(( $(date +%s) + TIMEOUT ))

# Every service with a healthcheck. One-shot services (minio-bucket-init)
# are checked separately because they don't have a healthcheck - they
# exit 0 when done and compose surfaces that via exited_status.
services=(
  postgres
  redis
  localstack
  authentik-postgres
  authentik-redis
  authentik-server
  minio
  clamav
  prometheus
  grafana
  loki
  alertmanager
  app
)

while true; do
  all_healthy=true
  for svc in "${services[@]}"; do
    state=$(docker inspect \
      --format '{{.State.Health.Status}}' \
      "accounting-parser-${svc}" 2>/dev/null \
      || echo "missing")
    case "$state" in
      healthy) continue ;;
      missing) echo "  [${svc}] container missing"; all_healthy=false ;;
      *) echo "  [${svc}] ${state}"; all_healthy=false ;;
    esac
  done

  # One-shot init service: exit 0 = success.
  init_state=$(docker inspect \
    --format '{{.State.Status}}:{{.State.ExitCode}}' \
    accounting-parser-minio-init 2>/dev/null || echo "missing")
  if [[ "$init_state" != "exited:0" ]]; then
    echo "  [minio-bucket-init] ${init_state}"
    all_healthy=false
  fi

  if [[ "$all_healthy" == "true" ]]; then
    echo "==> All services healthy."
    break
  fi

  if (( $(date +%s) > deadline )); then
    echo "==> TIMEOUT - some services did not report healthy within ${TIMEOUT}s"
    docker compose ps
    exit 1
  fi

  sleep "${POLL_INTERVAL}"
done

echo "==> Probing /healthz through the host-mapped port..."
if ! curl -fsS http://localhost:8000/healthz > /dev/null; then
  echo "    /healthz unreachable - the healthcheck passed inside the container"
  echo "    but the host-mapped port is not responding. Check your firewall or"
  echo "    docker network configuration."
  exit 1
fi
echo "    /healthz returned 200."

echo "==> Probing /metrics (Prometheus scrape endpoint)..."
# /metrics must be reachable without auth (allow-listed in middleware)
# and must return a non-empty Prometheus text body.
metrics_body=$(curl -fsS http://localhost:8000/metrics 2>/dev/null || true)
if [[ -z "${metrics_body}" ]]; then
  echo "    /metrics returned empty or failed - check AuthMiddleware allow-list"
  echo "    and that the observability router is wired in api/app.py."
  exit 1
fi
if ! grep -q '^# HELP' <<<"${metrics_body}"; then
  echo "    /metrics body has no '# HELP' headers - adapter not exposing counters."
  exit 1
fi
echo "    /metrics returned a valid Prometheus body."

echo
echo "==> ${GATE_NAME} gate PASSED. Stack is fully up."
echo "    App:         http://localhost:8000"
echo "    Authentik:   http://localhost:9400"
echo "    MinIO:       http://localhost:9901  (console)"
echo "    Prometheus:  http://localhost:9090"
echo "    Grafana:     http://localhost:3000"
echo "    Alertmgr:    http://localhost:9093"
