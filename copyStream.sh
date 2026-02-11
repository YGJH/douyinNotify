#!/usr/bin/zsh
ffmpeg -y -nostdin -rw_timeout 20000000 \
-user_agent "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36" \
-headers "Referer: https://live.douyin.com/" \
-use_wallclock_as_timestamps 1 \
-fflags +genpts \
-i "$1" \
-c copy \
-f matroska "$2.mkv"
