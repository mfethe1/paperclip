#!/usr/bin/env bash
# Probe the fleet from this tailnet node and print a markdown table.
#
#   - control plane: health, pinned version, authenticated mode, rejects anonymous API calls
#   - every host in fleet/hosts.json: online per Tailscale, last seen
#   - every published gateway: reachable over HTTPS; Hermes rejects anonymous calls
#
# Exit status 1 if any check fails. Run it from a second node too: hairpin NAT can
# make a host's own URLs look down from itself.
#
# Usage: scripts/fleet-check.sh [--inventory fleet/hosts.json]
set -euo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "$0")/lib/common.sh"

INV="$REPO_ROOT/fleet/hosts.json"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --inventory) INV="$2"; shift 2 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ -f "$INV" ]] || die "no inventory at $INV (copy fleet/hosts.example.json to fleet/hosts.json and fill it in)"
need jq
need curl
TS="$(tailscale_bin)"

suffix="$(jq -r '.tailnet_suffix' "$INV")"
status_json="$("$TS" status --json 2>/dev/null || echo '{}')"
failures=0
rows=()

add() { # check host result detail
  rows+=("| $1 | $2 | $3 | $4 |")
  [[ "$3" == "ok" || "$3" == "warn" ]] || failures=$((failures + 1))
}


# Control plane
cp_host="$(jq -r '.control_plane.host' "$INV")"
cp_dns="$(jq -r --arg h "$cp_host" '.hosts[$h].dns' "$INV")"
cp_port="$(jq -r '.control_plane.port // 3100' "$INV")"
board="$(jq -r '.control_plane.url // empty' "$INV")"
[[ -n "$board" ]] || board="https://${cp_dns}.${suffix}:${cp_port}"
health="$(curl -s -m 10 "$board/api/health" 2>/dev/null || true)"
if jq -e '.status == "ok"' >/dev/null 2>&1 <<<"$health"; then
  ver="$(jq -r '.version' <<<"$health")"
  mode="$(jq -r '.deploymentMode' <<<"$health")"
  if [[ "$ver" == "null" ]]; then add "paperclip health" "$cp_host" ok "ok (version hidden from anonymous callers)"
  elif [[ "$ver" == "$PAPERCLIP_VERSION" ]]; then add "paperclip health" "$cp_host" ok "v$ver"
  else add "paperclip health" "$cp_host" warn "running v$ver, repo pins v$PAPERCLIP_VERSION"; fi
  if [[ "$mode" == "authenticated" ]]; then add "paperclip auth mode" "$cp_host" ok "$mode/$(jq -r '.deploymentExposure' <<<"$health")"
  else add "paperclip auth mode" "$cp_host" FAIL "mode is $mode; tailnet access requires authenticated"; fi
  anon="$(http_code "$board/api/companies")"
  if [[ "$anon" == "200" ]]; then add "paperclip rejects anonymous" "$cp_host" FAIL "/api/companies answered 200 without credentials"
  else add "paperclip rejects anonymous" "$cp_host" ok "HTTP $anon"; fi
  backup="$(jq -r '.databaseBackup.status // "unknown"' <<<"$health")"
  if [[ "$backup" == "ok" ]]; then add "paperclip db backups" "$cp_host" ok "recent backup present"
  elif [[ "$(jq -r '.databaseBackup.enabled // false' <<<"$health")" != "true" ]]; then
    add "paperclip db backups" "$cp_host" FAIL "automatic backups disabled"
  else add "paperclip db backups" "$cp_host" warn "$(jq -r '[.databaseBackup.warnings[]?.message] | join("; ") | if . == "" then "status '"$backup"'" else . end' <<<"$health")"; fi
  if jq -e '.bootstrapStatus == "bootstrap_pending"' >/dev/null 2>&1 <<<"$health"; then
    add "paperclip admin claimed" "$cp_host" FAIL "bootstrap_pending: claim the instance"
  fi
else
  add "paperclip health" "$cp_host" FAIL "no healthy response from $board/api/health"
fi

# Hosts and gateways
for alias in $(jq -r '.hosts | keys[]' "$INV"); do
  dns="$(jq -r --arg h "$alias" '.hosts[$h].dns' "$INV")"
  fqdn="${dns}.${suffix}"
  always_on="$(jq -r --arg h "$alias" '.hosts[$h].always_on // false' "$INV")"
  peer="$(jq -c --arg d "${fqdn}." '
      ([.Self] + ((.Peer // {}) | to_entries | map(.value)))
      | map(select(.DNSName == $d)) | first // empty' <<<"$status_json")"
  if [[ -z "$peer" ]]; then
    add "tailscale node" "$alias" FAIL "$dns not found in tailscale status"
    continue
  fi
  online="$(jq -r 'if .Online == null then true else .Online end' <<<"$peer")"
  seen="$(jq -r '.LastSeen // "now"' <<<"$peer")"
  if [[ "$online" == "true" ]]; then add "tailscale node" "$alias" ok "online"
  elif [[ "$always_on" == "true" ]]; then add "tailscale node" "$alias" FAIL "offline (last seen $seen)"
  else add "tailscale node" "$alias" warn "offline (last seen $seen); not marked always_on"; fi

  for gw in $(jq -r --arg h "$alias" '.hosts[$h].gateways // {} | keys[]' "$INV"); do
    # A gateway is either a Serve port number or a full base URL.
    gport="$(jq -r --arg h "$alias" --arg g "$gw" '.hosts[$h].gateways[$g]' "$INV")"
    if [[ "$gport" == http* ]]; then base="${gport%/}"
    else base="https://${fqdn}"; [[ "$gport" == "443" ]] || base="${base}:${gport}"; fi
    case "$gw" in
      hermes)
        h="$(http_code "$base/health")"
        if [[ "$h" == "200" ]]; then add "hermes gateway" "$alias" ok "health 200"
        else add "hermes gateway" "$alias" FAIL "health HTTP $h at $base"; fi
        a="$(http_code "$base/v1/capabilities")"
        if [[ "$a" == "200" ]]; then add "hermes rejects anonymous" "$alias" FAIL "/v1/capabilities answered 200 without a key"
        elif [[ "$h" == "200" ]]; then add "hermes rejects anonymous" "$alias" ok "HTTP $a"; fi
        ;;
      openclaw)
        o="$(http_code "$base/")"
        if [[ "$o" != "000" ]]; then add "openclaw gateway" "$alias" ok "HTTPS reachable (HTTP $o)"
        else add "openclaw gateway" "$alias" FAIL "no response at $base"; fi
        ;;
      *)
        add "gateway $gw" "$alias" warn "unknown gateway kind; not probed" ;;
    esac
  done
done

echo "| Check | Host | Result | Detail |"
echo "|---|---|---|---|"
printf '%s\n' "${rows[@]}"
echo
echo "Checked from $(hostname -s 2>/dev/null || hostname) at $(date -u +%Y-%m-%dT%H:%M:%SZ); failures: $failures"
[[ "$failures" -eq 0 ]]
