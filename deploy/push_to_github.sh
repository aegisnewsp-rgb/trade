#!/bin/bash
# push.sh — Push to GitHub
# Usage: ./push.sh [github-token]

cd "$(dirname "$0\")/..\"
git remote set-url origin https://x-access-token:${1:-}.@github.com/aegisnewsp-rgb/trade.git
git push origin main 2>&1
