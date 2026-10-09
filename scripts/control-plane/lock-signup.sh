#!/usr/bin/env bash
# Disable open sign-up once the instance admin exists. Further humans join by invite
# (paperclipai invite create ...). Run on the control-plane host.
set -euo pipefail
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"
need jq

CONFIG="$(paperclip_config_path)"
[[ -f "$CONFIG" ]] || die "no instance config at $CONFIG"
FQDN="$(tailnet_fqdn)"
curl -fsS "https://$FQDN:$PAPERCLIP_PORT/api/health" | jq -e '.bootstrapStatus != "bootstrap_pending"' >/dev/null \
  || die "instance has no admin yet; claim it first or you will lock yourself out"

cp -p "$CONFIG" "${CONFIG}.bak.$(date +%Y%m%d%H%M%S)"
tmp="$(mktemp)"
jq '.auth.disableSignUp = true' "$CONFIG" > "$tmp" && mv "$tmp" "$CONFIG"
paperclipai service restart --wait
log "sign-up disabled; invite additional people with: paperclipai invite create --company-id <id> --payload-json '{\"allowedJoinTypes\":\"human\"}'"
