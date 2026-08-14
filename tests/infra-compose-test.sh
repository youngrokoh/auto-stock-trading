#!/usr/bin/env bash

set -eu

project_root="$(cd "$(dirname "$0")/.." && pwd)"

ruby - "$project_root/infra/compose.yaml" "$project_root/infra/compose.kis-paper.yaml" "$project_root/infra/Caddyfile" "$project_root/.dockerignore" <<'RUBY'
require "yaml"

compose = YAML.safe_load(File.read(ARGV.fetch(0)), aliases: true)
paper_compose = YAML.safe_load(File.read(ARGV.fetch(1)), aliases: true)
postgres = compose.fetch("services").fetch("postgres")
volume_targets = postgres.fetch("volumes").map { |volume| volume.split(":", 2).fetch(1) }

unless volume_targets.include?("/var/lib/postgresql")
  abort "PostgreSQL 18 data volume must target /var/lib/postgresql"
end

paper_worker = paper_compose.fetch("services").fetch("worker")
paper_environment = paper_worker.fetch("environment")
unless paper_environment.fetch("AUTO_STOCK_KIS_ENVIRONMENT") == "paper"
  abort "KIS Compose override must force the paper environment"
end
unless paper_environment.key?("AUTO_STOCK_KIS_APP_KEY_FILE") && paper_environment.key?("AUTO_STOCK_KIS_APP_SECRET_FILE")
  abort "KIS Compose override must use secret file settings"
end
unless paper_worker.fetch("secrets").sort == %w[kis_app_key kis_app_secret]
  abort "KIS Compose override must mount both KIS credentials as Docker secrets"
end

caddyfile = File.read(ARGV.fetch(2))
%w[default-src script-src style-src connect-src img-src object-src].each do |directive|
  abort "Caddy CSP must define #{directive}" unless caddyfile.include?("#{directive} ")
end

docker_ignores = File.read(ARGV.fetch(3)).lines.map(&:strip)
unless docker_ignores.include?(".secrets")
  abort "Docker build context must exclude the local secret directory"
end
RUBY

echo "Infrastructure Compose contract passed."
