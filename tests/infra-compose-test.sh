#!/usr/bin/env bash

set -eu

project_root="$(cd "$(dirname "$0")/.." && pwd)"

ruby - "$project_root/infra/compose.yaml" "$project_root/infra/compose.kis-paper.yaml" "$project_root/infra/compose.kis-live-calendar.yaml" "$project_root/infra/Caddyfile" "$project_root/.dockerignore" "$project_root/infra/compose.etf-nav-schedule.yaml" <<'RUBY'
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
# 상주 서비스는 호스트가 재부팅해도 스스로 돌아와야 한다. 정책이 없으면 한 번 죽은 뒤 아무도
# 되살리지 않고, 그 사이 무인 운영은 조용히 멈춘다(2026-09-02 실측: 재부팅 후 기반 스택이 전부
# 내려간 채로 남았고, 정책이 있던 서비스들은 DB 없이 되살아나 크래시 루프에 빠졌다).
# `migrate`는 한 번 실행하고 끝나야 하므로 정책을 주면 반복 실행된다 — 유일한 예외다.
one_shot_services = ["migrate"]
compose.fetch("services").each do |name, service|
  restart = service["restart"]
  if one_shot_services.include?(name)
    abort "#{name} runs once and must exit: a restart policy would loop it" unless restart.nil?
  elsif restart != "unless-stopped"
    abort "#{name} must set restart: unless-stopped, or a host reboot leaves it down for good"
  end
end

# ETF NAV 예약(ADR-0021 결정 4). 스케줄러에 자격증명이 가면 안 되고, worker의 command를 통째로
# 덮어쓰므로 등록 모듈을 빠뜨리면 그 태스크가 조용히 버려진다(2026-08-31 실측).
etf_nav_compose = YAML.safe_load(File.read(ARGV.fetch(5)), aliases: true)
etf_nav_scheduler = etf_nav_compose.fetch("services").fetch("etf-nav-scheduler")

if etf_nav_scheduler.key?("secrets")
  abort "ETF NAV scheduler must not receive KIS credentials: only the worker performs the sweep"
end

etf_nav_worker = etf_nav_compose.fetch("services").fetch("worker")
required_modules = [
  "auto_stock_trading.worker.market_calendar_schedule",
  "auto_stock_trading.worker.investor_flow_schedule",
  "auto_stock_trading.worker.etf_nav_schedule",
]
missing = required_modules.reject { |mod| etf_nav_worker.fetch("command").include?(mod) }
unless missing.empty?
  abort "ETF NAV override replaces the worker command, so it must register #{missing.join(", ")}"
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
