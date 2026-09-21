#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
target="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}/skills/ledgerly-receipt"

install -d -m 700 "$target/scripts"
install -m 600 "$repo_root/integrations/openclaw/ledgerly-receipt/SKILL.md" "$target/SKILL.md"
install -m 700 "$repo_root/integrations/openclaw/ledgerly-receipt/scripts/submit_receipt.py" "$target/scripts/submit_receipt.py"

echo "Installed ledgerly-receipt skill at $target"
echo "Next: merge openclaw.example.json5, set the Gateway environment, then run openclaw skills list."

