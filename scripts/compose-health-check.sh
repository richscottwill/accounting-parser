#!/usr/bin/env bash
# compose-health-check.sh — Phase 1 gate (P1.6) acceptance.
#
# Asserts that `docker compose up -d` brings every service to a
# healthy state within a reasonable budget. Used by:
# - Richard to spot-check a fresh reference VM.
# - CI matrix smoke tests once the installer lands (P3.1).
# - Troubleshooting when the firm principal reports "nothing works."
#
# Exits non-zero if any service fails to go healthy within TIMEOUT.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

TIMEOUT="${TIMEOUT_SECONDS:-300}"   # 5 min default; first boot downloads ~1 GB of images
POLL_INTERVAL=5

echo "==> Bringing stack up..."
docker compose up -d

echo "==> Waiting up to ${TIMEOUT}s for services to report healthy..."
deadline=$(( $(date +%s) + TIMEOUT ))

# Every service with a healthcheck. One-shot services (minio-bucket-init)
# are checked separately because they don't have a healthcheck — they
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
    echo "==> TIMEOUT — some services did not report healthy within ${TIMEOUT}s"
    docker compose ps
    exit 1
  fi

  sleep "${POLL_INTERVAL}"
done

echo "==> Probing /healthz through the API container..."
if ! curl -fsS http://localhost:8000/healthz > /dev/null; then
  echo "    /healthz unreachable — the healthcheck passed inside the container"
  echo "    but the host-mapped port is not responding. Check your firewall or"
  echo "    docker network configuration."
  exit 1
fi
echo "    /healthz returned 200."

echo
echo "==> Phase 1 gate PASSED. Stack is fully up."
echo "    App:        http://localhost:8000"
echo "    Authentik:  http://localhost:9400"
echo "    MinIO:      http://localhost:9901  (console)"
