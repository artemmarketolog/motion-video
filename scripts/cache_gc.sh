#!/usr/bin/env bash
# Чистит кэш кусков у роликов студии, которые не трогали 2 суток (запускать cron раз в день, см. README).
# Удаляются только восстановимые данные (.cache/segments, video, audio, probe, tmp): следующий build перерендерит их сам.
# output/, work/, исходники и TTS-кэш не трогаются.
set -u
ROOT=${1:-${MOTION_VIDEO_STUDIO:-$HOME/video-studio}/projects}
for d in "$ROOT"/*/.cache; do
  [ -d "$d" ] || continue
  p=${d%/.cache}
  [ -e "$d/build.lock" ] && fuser "$d/build.lock" >/dev/null 2>&1 && continue
  [ -n "$(find "$p" -mmin -2880 -not -path '*/node_modules/*' -print -quit)" ] && continue
  rm -rf "$d/segments" "$d/video" "$d/audio" "$d/probe" "$d/tmp"
done
