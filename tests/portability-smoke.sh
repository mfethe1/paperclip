#!/bin/sh
# Run every shell script under a given bash (default /bin/bash, which on macOS is
# 3.2.57) with stubbed external commands, and fail on shell-level breakage:
# syntax errors, "unbound variable" (empty arrays under set -u on bash 3.2),
# bad substitutions, or our own functions not being found.
#
# Usage: BASH_BIN=/bin/bash NODE24=/path/to/node24 tests/portability-smoke.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASH_BIN="${BASH_BIN:-/bin/bash}"
NODE24="${NODE24:-$(command -v node)}"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/home/.local/bin"

cat > "$T/bin/tailscale" <<'EOF'
#!/bin/sh
case "$1 $2" in
  "status --json") echo '{"BackendState":"Running","CertDomains":["box.example.ts.net"],"MagicDNSSuffix":"example.ts.net","Self":{"DNSName":"box.example.ts.net.","Online":true},"Peer":{}}' ;;
  "serve status") echo '{}' ;;
  "ip -4") echo 100.64.0.1 ;;
esac
exit 0
EOF
cat > "$T/bin/launchctl" <<'EOF'
#!/bin/sh
exit 0
EOF
cat > "$T/bin/paperclipai" <<'EOF'
#!/bin/sh
case "$1" in
  --version) echo "2026.1005.0 (managed npm pinned; payload stub)" ;;
esac
exit 0
EOF
chmod +x "$T/bin/"*
# A managed launcher in the exact format Paperclip writes, for repin_managed_shim.
printf '%s\n' '#!/bin/sh' '# paperclipai managed install shim v1' 'set -eu' \
  "exec '$NODE24' '$T/home/.paperclip/cli/current/node_modules/paperclipai/dist/index.js' \"\$@\"" \
  > "$T/home/.local/bin/paperclipai"
chmod +x "$T/home/.local/bin/paperclipai"
cat > "$T/hosts.json" <<'EOF'
{"tailnet_suffix":"example.ts.net","control_plane":{"host":"box","url":"http://127.0.0.1:9"},
 "hosts":{"box":{"dns":"box","always_on":true,"gateways":{"hermes":"http://127.0.0.1:9"}},
          "other":{"dns":"other","always_on":false,"gateways":{}}}}
EOF

fail=0
check() {
  name="$1"; shift
  out="$(cd "$ROOT" && env HOME="$T/home" PATH="$T/bin:$PATH" PAPERCLIP_NODE="$NODE24" "$@" 2>&1)"
  rc=$?
  if printf '%s\n' "$out" | grep -E "unbound variable|syntax error|bad substitution|bad array subscript|(find_node24|ensure_node24|repin_managed_shim|http_code|serve_https|paperclip_cli_version): command not found" >/dev/null; then
    echo "FAIL $name (rc=$rc)"; printf '%s\n' "$out" | sed 's/^/    /' | tail -20; fail=1
  else
    echo "ok   $name (rc=$rc)"
  fi
}

"$BASH_BIN" --version | head -1
for f in "$ROOT"/scripts/*.sh "$ROOT"/scripts/*/*.sh; do
  "$BASH_BIN" -n "$f" || { echo "FAIL syntax $f"; fail=1; }
done
echo "ok   syntax check (bash -n) on all scripts"

check "common.sh functions" "$BASH_BIN" -c '
  source scripts/lib/common.sh
  find_node24 >/dev/null
  [ "$(http_code http://127.0.0.1:9 2)" = "000" ] || { echo "http_code wrong"; exit 1; }
  [ "$(paperclip_cli_version)" = "2026.1005.0" ] || { echo "version parse wrong"; exit 1; }
  repin_managed_shim "$PAPERCLIP_NODE"
  grep -q "^export PATH=" "$HOME/.local/bin/paperclipai" || { echo "repin wrote no PATH"; exit 1; }
  echo done'
check "install.sh --dry-run" "$BASH_BIN" scripts/control-plane/install.sh --dry-run
check "preflight.sh" "$BASH_BIN" scripts/control-plane/preflight.sh
check "fleet-check.sh" "$BASH_BIN" scripts/fleet-check.sh --inventory "$T/hosts.json"
check "diagnose.sh (unreachable board)" "$BASH_BIN" scripts/diagnose.sh --board-url http://127.0.0.1:9
check "inventory-local-work.sh" env MAXDEPTH=2 "$BASH_BIN" scripts/migrate/inventory-local-work.sh "$T/home"
check "expose-gateway.sh (no gateway)" "$BASH_BIN" scripts/node/expose-gateway.sh hermes --dry-run
check "join-hermes.sh (usage)" "$BASH_BIN" scripts/node/join-hermes.sh request --paperclip http://127.0.0.1:9
check "export-company.sh (usage)" "$BASH_BIN" scripts/export-company.sh
check "discover-projects.sh --help" "$BASH_BIN" scripts/migrate/discover-projects.sh --help
check "lock-signup.sh (no instance)" "$BASH_BIN" scripts/control-plane/lock-signup.sh
# Redaction must work with the platform's sed (BSD on macOS: no \b, etc.).
sed -n '/^redact() {/,/^}/p' "$ROOT/scripts/diagnose.sh" > "$T/redact.sh"
red="$(printf '%s\n' 'ip 100.66.54.22 /Users/alice/x box.tail1a2b3c.ts.net 127.0.0.1 v2026.1005.0 Bearer abc.def 0123abcd-0000-4000-8000-0123456789ab' \
  | "$BASH_BIN" -c ". '$T/redact.sh'; redact")"
case "$red" in
  *"<ip>"*"<home>/x"*"<host>"*"127.0.0.1"*"v2026.1005.0"*"Bearer <redacted>"*"<uuid>"*) echo "ok   redact() with this platform's sed" ;;
  *) echo "FAIL redact() output: $red"; fail=1 ;;
esac
rm -rf "$ROOT/migration/out"
exit "$fail"
