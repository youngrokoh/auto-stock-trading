#!/usr/bin/env bash

set -eu

project_root="$(cd "$(dirname "$0")/.." && pwd)"
fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT

mkdir -p "$fixture_root/docs/governance" "$fixture_root/docs/spec" "$fixture_root/src/orders"

printf '%s\n' \
  '# Fixture docs' \
  '' \
  '- [Order specification](spec/orders.md)' \
  > "$fixture_root/docs/README.md"

printf '%s\n' \
  '# Order specification' \
  '' \
  '- 상태: 승인' \
  > "$fixture_root/docs/spec/orders.md"

printf '%s\n' \
  '{' \
  '  "version": 1,' \
  '  "rules": [' \
  '    {' \
  '      "name": "order-domain",' \
  '      "code": ["src/orders/**"],' \
  '      "docs": ["docs/spec/orders.md"]' \
  '    }' \
  '  ]' \
  '}' \
  > "$fixture_root/docs/governance/change-map.yaml"

python3 "$project_root/scripts/docs_guard.py" links --repo-root "$fixture_root"
python3 "$project_root/scripts/docs_guard.py" generate --repo-root "$fixture_root"
python3 "$project_root/scripts/docs_guard.py" generate --repo-root "$fixture_root" --check

if python3 "$project_root/scripts/docs_guard.py" drift \
  --repo-root "$fixture_root" \
  --changed-file "src/orders/service.py"; then
  echo "Expected documentation drift to be rejected." >&2
  exit 1
fi

python3 "$project_root/scripts/docs_guard.py" drift \
  --repo-root "$fixture_root" \
  --changed-file "src/orders/service.py" \
  --changed-file "docs/spec/orders.md"

python3 "$project_root/scripts/docs_guard.py" drift \
  --repo-root "$fixture_root" \
  --changed-file "src/orders/service.py" \
  --waiver "internal refactor; documented behavior is unchanged"

printf '%s\n' \
  '{' \
  '  "version": 1,' \
  '  "rules": [' \
  '    {' \
  '      "name": "order-domain",' \
  '      "code": ["src/orders/**"],' \
  '      "docs": ["docs/spec/missing.md"]' \
  '    }' \
  '  ]' \
  '}' \
  > "$fixture_root/docs/governance/change-map.yaml"

if python3 "$project_root/scripts/docs_guard.py" check --repo-root "$fixture_root"; then
  echo "Expected a missing mapped document to be rejected." >&2
  exit 1
fi

echo "Documentation guard E2E scenarios passed."
