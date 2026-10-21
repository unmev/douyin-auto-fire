#!/bin/sh
set -eu

CRON_SCHEDULE="${CRON_SCHEDULE:-30 0 * * *}"
RUN_ON_START="${RUN_ON_START:-false}"

mkdir -p /app/artifacts /data

if [ "$RUN_ON_START" = "true" ]; then
  echo "[docker] running task once on container start"
  cd /app
  python run.py || true
fi

# cron 启动的作业不会继承容器自身的环境变量，容器里通过 compose 传入的
# DOUYIN_COOKIE / TASK_CONFIG / ARTIFACTS_DIR / HEADLESS 等在定时任务里都会丢失，
# 导致任务必然失败。这里把容器环境写成 shell 脚本，并让 crontab 在执行前加载它。
python /app/docker/setup_cron.py --schedule "$CRON_SCHEDULE"

printf '[docker] cron schedule: %s\n' "$CRON_SCHEDULE"
printf '[docker] timezone: %s\n' "${TZ:-Asia/Shanghai}"

exec cron -f
