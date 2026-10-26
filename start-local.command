#!/usr/bin/env bash
# macOS Finder 双击入口；也可在终端执行 ./start-local.sh。
cd "$(dirname "$0")" || exit 1
./start-local.sh
result=$?
printf '\n按回车关闭此窗口…'
read -r _
exit "$result"
