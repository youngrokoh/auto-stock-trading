#!/usr/bin/env bash

set -eu

project_root="$(cd "$(dirname "$0")/.." && pwd)"

ruby - "$project_root/infra/compose.yaml" "$project_root/infra/Caddyfile" <<'RUBY'
require "yaml"

compose = YAML.safe_load(File.read(ARGV.fetch(0)), aliases: true)
postgres = compose.fetch("services").fetch("postgres")
volume_targets = postgres.fetch("volumes").map { |volume| volume.split(":", 2).fetch(1) }

unless volume_targets.include?("/var/lib/postgresql")
  abort "PostgreSQL 18 data volume must target /var/lib/postgresql"
end

caddyfile = File.read(ARGV.fetch(1))
%w[default-src script-src style-src connect-src img-src object-src].each do |directive|
  abort "Caddy CSP must define #{directive}" unless caddyfile.include?("#{directive} ")
end
RUBY

echo "Infrastructure Compose contract passed."
