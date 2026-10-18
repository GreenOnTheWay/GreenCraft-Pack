#!/usr/bin/env bash
set -euo pipefail
cleanup() {
  docker logs greencraft-server-test > /tmp/greencraft-server.log 2>&1 || true
  docker rm -f greencraft-server-test >/dev/null 2>&1 || true
  if [ -f /tmp/greencraft-http.pid ]; then
    kill "$(cat /tmp/greencraft-http.pid)" 2>/dev/null || true
  fi
}
trap cleanup EXIT
MC=$(python -c 'import json; print(json.load(open("candidate/greencraft-release.json"))["minecraft"])')
FABRIC=$(python -c 'import json; print(json.load(open("candidate/greencraft-release.json"))["fabric"])')
docker pull itzg/minecraft-server:java25
docker run -d --name greencraft-server-test \
  --add-host=host.docker.internal:host-gateway \
  -e EULA=TRUE -e TYPE=FABRIC -e VERSION="$MC" \
  -e FABRIC_LOADER_VERSION="$FABRIC" -e MEMORY=2G \
  -e PACKWIZ_URL="http://host.docker.internal:8000/pack.toml" \
  itzg/minecraft-server:java25
for i in $(seq 1 72); do
  logs=$(docker logs greencraft-server-test 2>&1)
  if echo "$logs" | grep -Eq 'Done \([0-9.,]+s\)!'; then
    sleep 5
    test "$(docker inspect -f '{{.State.Running}}' greencraft-server-test)" = true
    printf '%s\n' "$logs"
    exit 0
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' greencraft-server-test)" != true ]; then
    printf '%s\n' "$logs"
    exit 1
  fi
  sleep 5
done
echo 'Server did not become ready within six minutes' >&2
exit 1
