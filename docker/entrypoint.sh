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

# cron 不会把容器的环境变量传给作业（作业里只剩 HOME、LOGNAME、PATH、PWD、SHELL），
# 因此需要把应用用到的变量以 NAME=value 的形式写进 crontab，否则定时任务会缺少
# DOUYIN_COOKIE / TASK_CONFIG / ARTIFACTS_DIR / PLAYWRIGHT_BROWSERS_PATH 而必然失败。
# PLAYWRIGHT_BROWSERS_PATH 在镜像里是 ENV（/ms-playwright），默认值必须与 Dockerfile 保持一致。
ENV_NAMES="TZ TASK_CONFIG ARTIFACTS_DIR DOUYIN_COOKIE DOUYIN_STORAGE_STATE HEADLESS TRACE BROWSER_PATH PLAYWRIGHT_BROWSERS_PATH DINGTALK_WEBHOOK DINGTALK_SECRET WEBHOOK_URL WEBHOOK_HEADERS WEBHOOK_TEMPLATE"

: > /etc/cron.d/douyin-auto-fire
{
  printf '%s\n' 'SHELL=/bin/sh'
  printf '%s\n' 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
  for name in $ENV_NAMES; do
    eval "value=\${$name:-}"
    [ -n "$value" ] || continue
    # 单引号包裹值，内部单引号按 ' -> '\'' 转义，避免含空格/引号的值（如 Webhook 模板）被截断
    quoted=$(printf '%s' "$value" | sed "s/'/'\\\\''/g")
    # cron 会把作业行里的 % 当作换行，转义掉以免值被截断
    quoted=$(printf '%s' "$quoted" | sed 's/%/\\%/g')
    printf "%s='%s'\n" "$name" "$quoted"
  done
  printf '%s\n' "${CRON_SCHEDULE} root cd /app && /usr/local/bin/python run.py >> /proc/1/fd/1 2>> /proc/1/fd/2"
} >> /etc/cron.d/douyin-auto-fire

chmod 0644 /etc/cron.d/douyin-auto-fire

printf '[docker] cron schedule: %s\n' "$CRON_SCHEDULE"
printf '[docker] timezone: %s\n' "${TZ:-Asia/Shanghai}"

exec cron -f
