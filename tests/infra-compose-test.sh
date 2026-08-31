#!/usr/bin/env bash

set -eu

project_root="$(cd "$(dirname "$0")/.." && pwd)"

ruby - "$project_root/infra/compose.yaml" "$project_root/infra/compose.kis-paper.yaml" "$project_root/infra/compose.kis-live-calendar.yaml" "$project_root/infra/Caddyfile" "$project_root/.dockerignore" <<'RUBY'
require "yaml"

compose = YAML.safe_load(File.read(ARGV.fetch(0)), aliases: true)
paper_compose = YAML.safe_load(File.read(ARGV.fetch(1)), aliases: true)
live_calendar_compose = YAML.safe_load(File.read(ARGV.fetch(2)), aliases: true)
postgres = compose.fetch("services").fetch("postgres")
valkey = compose.fetch("services").fetch("valkey")
scheduler = compose.fetch("services").fetch("calendar-scheduler")
volume_targets = postgres.fetch("volumes").map { |volume| volume.split(":", 2).fetch(1) }

unless volume_targets.include?("/var/lib/postgresql")
  abort "PostgreSQL 18 data volume must target /var/lib/postgresql"
end
unless valkey.fetch("ports") == ["127.0.0.1:6379:6379"]
  abort "Valkey host port must bind to 127.0.0.1 only"
end
unless scheduler.fetch("profiles") == ["calendar-scheduler"]
  abort "Market calendar scheduler must be disabled outside its explicit Compose profile"
end
unless scheduler.fetch("command").first(2) == ["taskiq", "scheduler"]
  abort "Market calendar scheduler must run through Taskiq"
end
unless scheduler.fetch("environment").fetch("AUTO_STOCK_KRX_CALENDAR_SCHEDULE_ENABLED") == "true"
  abort "The scheduler profile must explicitly enable KRX calendar collection"
end
unless scheduler.fetch("secrets", []).empty?
  abort "The scheduler process must not receive KIS credentials"
end
scheduler_count = compose.fetch("services").values.count do |service|
  service.fetch("command", []).first(2) == ["taskiq", "scheduler"]
end
unless scheduler_count == 1
  abort "Compose must define exactly one Taskiq scheduler service"
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

if live_calendar_compose.fetch("services").key?("worker")
  abort "KIS live calendar override must not touch the shared worker: it also collects paper market data and investor flows, so live credentials there break the paper/live separation"
end

live_worker = live_calendar_compose.fetch("services").fetch("calendar-confirm-worker")
unless live_worker.fetch("command").last.end_with?(":confirm_broker")
  abort "KIS live calendar worker must consume its own queue, or it steals paper tasks"
end
live_worker_environment = live_worker.fetch("environment")
unless live_worker_environment.fetch("AUTO_STOCK_KIS_ENVIRONMENT") == "live"
  abort "KIS live calendar worker must force the live environment"
end
unless live_worker_environment.fetch("AUTO_STOCK_KIS_CALENDAR_SCHEDULE_ENABLED") == "true"
  abort "KIS live calendar worker must explicitly enable scheduled confirmation"
end
unless live_worker.fetch("secrets").sort == %w[kis_live_app_key kis_live_app_secret]
  abort "KIS live calendar worker must mount only the live KIS credentials"
end
unless live_worker.fetch("restart") == "unless-stopped"
  abort "KIS live calendar worker must restart unless explicitly stopped"
end

live_scheduler = live_calendar_compose.fetch("services").fetch("calendar-confirm-scheduler")
unless live_scheduler.fetch("command").last.end_with?(":confirm_scheduler")
  abort "KIS live calendar scheduler must publish to the dedicated confirmation queue"
end
live_scheduler_environment = live_scheduler.fetch("environment")
unless live_scheduler_environment.fetch("AUTO_STOCK_KIS_ENVIRONMENT") == "live"
  abort "KIS live calendar scheduler must register tasks for the live environment"
end
unless live_scheduler_environment.fetch("AUTO_STOCK_KIS_CALENDAR_SCHEDULE_ENABLED") == "true"
  abort "KIS live calendar scheduler must explicitly enable scheduled confirmation"
end
unless live_scheduler.fetch("secrets", []).empty?
  abort "KIS live credentials must never be mounted into the scheduler"
end
unless live_scheduler.fetch("restart") == "unless-stopped"
  abort "KIS live calendar scheduler must restart unless explicitly stopped"
end

caddyfile = File.read(ARGV.fetch(3))
%w[default-src script-src style-src connect-src img-src object-src].each do |directive|
  abort "Caddy CSP must define #{directive}" unless caddyfile.include?("#{directive} ")
end

docker_ignores = File.read(ARGV.fetch(4)).lines.map(&:strip)
unless docker_ignores.include?(".secrets")
  abort "Docker build context must exclude the local secret directory"
end
RUBY

echo "Infrastructure Compose contract passed."
