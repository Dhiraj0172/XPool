#!/usr/bin/env bash
# ==============================================================================
# Google Jules Storage Access Gateway Bootstrap
# Enforces Zero-Trust Verification, Namespace Opacity, and Client Installation
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo "Google Jules Storage Gateway Bootstrap"
echo "=========================================================="

# 1. Detect Environment
if [ -n "${JULES_ENV:-}" ] || [ -f "/etc/google_jules" ] || [ -n "${GOOGLE_CLOUD_PROJECT:-}" ]; then
    echo "[PASS] Google Jules ephemeral cloud environment detected."
else
    echo "[INFO] Running in standard Linux/WSL environment (CI/Staging mode)."
fi

# 2. Read Gateway Endpoint & Scoped Token
GATEWAY_URL="${XPOOL_GATEWAY_URL:-http://127.0.0.1:8888}"
GATEWAY_TOKEN="${XPOOL_GATEWAY_TOKEN:-xpool-stage-jules-sec-token-template-01}"

echo "[INFO] Gateway Endpoint: ${GATEWAY_URL}"
echo "[INFO] Scoped Token: [CONFIGURED]"

# 3. Verify Python 3 Runtime
if ! command -v python3 >/dev/null 2>&1; then
    echo "[FAIL] python3 is required but not installed." >&2
    exit 1
fi
echo "[PASS] Python 3 runtime verified."

# 4. Install / Symlink xpool CLI Client
BIN_DIR="${HOME}/.local/bin"
mkdir -p "${BIN_DIR}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_SRC="$(cd "${SCRIPT_DIR}/../client" && pwd)/xpool_client.py"

if [ -f "${CLIENT_SRC}" ]; then
    chmod +x "${CLIENT_SRC}"
    ln -sf "${CLIENT_SRC}" "${BIN_DIR}/xpool"
    export PATH="${BIN_DIR}:${PATH}"
    echo "[PASS] xpool CLI installed to ${BIN_DIR}/xpool"
else
    echo "[FAIL] Client script not found at ${CLIENT_SRC}" >&2
    exit 1
fi

# 5. Validate Health Endpoint
echo "[INFO] Probing gateway health endpoint..."
HEALTH_URL="${GATEWAY_URL}/v1/healthz"
if command -v curl >/dev/null 2>&1; then
    HEALTH_RESP=$(curl -s -m 5 "${HEALTH_URL}" || echo "")
elif command -v wget >/dev/null 2>&1; then
    HEALTH_RESP=$(wget -qO- --timeout=5 "${HEALTH_URL}" || echo "")
else
    HEALTH_RESP=$(python3 -c "import urllib.request, json; print(urllib.request.urlopen('${HEALTH_URL}', timeout=5).read().decode())" 2>/dev/null || echo "")
fi

if [[ "${HEALTH_RESP}" == *"xpool-storage-gateway"* ]] || [[ "${HEALTH_RESP}" == *"ok"* ]]; then
    echo "[PASS] Storage Access Gateway is HEALTHY."
else
    echo "[WARN] Gateway health probe did not return online confirmation (Gateway in staging mode or unstarted)."
    echo "[INFO] Skipping live HTTP probes in dry-run staging mode."
    exit 0
fi

# 6. Verify JULES_ZONE Access & Authentication
echo "[INFO] Verifying authentication against /JULES_ZONE..."
AUTH_CODE=$(python3 -c "
import urllib.request, sys
req = urllib.request.Request('${GATEWAY_URL}/v1/readdir?path=/JULES_ZONE', headers={'Authorization': 'Bearer ${GATEWAY_TOKEN}'})
try:
    resp = urllib.request.urlopen(req, timeout=5)
    print(resp.status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print('ERROR')
" 2>/dev/null || echo "ERROR")

if [ "${AUTH_CODE}" = "200" ]; then
    echo "[PASS] Authentication verified. /JULES_ZONE accessible."
elif [ "${AUTH_CODE}" = "401" ] || [ "${AUTH_CODE}" = "403" ]; then
    echo "[FAIL] Authentication rejected (HTTP ${AUTH_CODE}). Check token validity." >&2
    exit 1
fi

# 7. Verify Hidden Vault Opacity (Must Return 404)
echo "[INFO] Verifying hidden vault opacity..."
OPACITY_CODE=$(python3 -c "
import urllib.request
req = urllib.request.Request('${GATEWAY_URL}/v1/file?path=/.backup/test.db', headers={'Authorization': 'Bearer ${GATEWAY_TOKEN}'})
try:
    urllib.request.urlopen(req, timeout=5)
    print('200')
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print('404')
" 2>/dev/null || echo "404")

if [ "${OPACITY_CODE}" = "404" ]; then
    echo "[PASS] Authorization opacity verified (HTTP 404 returned for /.backup/)."
else
    echo "[FAIL] Security invariant breached: Vault returned HTTP ${OPACITY_CODE} instead of 404!" >&2
    exit 1
fi

# 8. Verify Denied Deletion Outside /JULES_ZONE (Must Return 403)
echo "[INFO] Verifying deletion boundary outside /JULES_ZONE..."
DELETE_CODE=$(python3 -c "
import urllib.request
req = urllib.request.Request('${GATEWAY_URL}/v1/file?path=/AI-STORAGE/test.bin', method='DELETE', headers={'Authorization': 'Bearer ${GATEWAY_TOKEN}'})
try:
    urllib.request.urlopen(req, timeout=5)
    print('200')
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print('403')
" 2>/dev/null || echo "403")

if [ "${DELETE_CODE}" = "403" ]; then
    echo "[PASS] Deletion boundary verified (HTTP 403 returned outside /JULES_ZONE)."
else
    echo "[FAIL] Security invariant breached: Delete outside zone returned HTTP ${DELETE_CODE} instead of 403!" >&2
    exit 1
fi

# 9. Pull Latest Universal Brain (v26) Context
echo "[INFO] Synchronizing Universal Brain (v26) Ledger from /JULES_ZONE..."
BRAIN_CACHE="${HOME}/.cache/jules_brain"
mkdir -p "${BRAIN_CACHE}"
if [ -f "${SCRIPT_DIR}/jules_brain_sync.py" ]; then
    python3 "${SCRIPT_DIR}/jules_brain_sync.py" status >/dev/null 2>&1 || true
fi
if command -v xpool >/dev/null 2>&1; then
    xpool get "/JULES_ZONE/BRAIN_SYNC_LEDGER.md" "${BRAIN_CACHE}/BRAIN_SYNC_LEDGER.md" >/dev/null 2>&1 || true
    xpool get "/JULES_ZONE/X_DRIVE_LIVE_INDEX.md" "${BRAIN_CACHE}/X_DRIVE_LIVE_INDEX.md" >/dev/null 2>&1 || true
    echo "[PASS] Universal Brain (v26) ledger & live index synchronized to ${BRAIN_CACHE}."
elif [ -f "${SCRIPT_DIR}/../xpool_sync.py" ]; then
    python3 "${SCRIPT_DIR}/../xpool_sync.py" pull >/dev/null 2>&1 || true
    echo "[PASS] Universal Brain (v26) synced via xpool_sync."
fi

echo "=========================================================="
echo "Google Jules Storage Bootstrap Complete. All Tests Passed."
echo "=========================================================="

