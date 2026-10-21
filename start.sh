#!/bin/sh
set -eu

# Nginx exposes one public Render port and routes /baseline/* to the Dash editor.
nginx -g 'daemon off;' &
NGINX_PID=$!

streamlit run hartspec_gui/Home.py \
  --server.address=127.0.0.1 \
  --server.port=8501 \
  --server.headless=true \
  --browser.gatherUsageStats=false &
STREAMLIT_PID=$!

cleanup() {
  kill "$STREAMLIT_PID" "$NGINX_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# Keep the service alive while both child processes run.
while kill -0 "$NGINX_PID" 2>/dev/null && kill -0 "$STREAMLIT_PID" 2>/dev/null; do
  sleep 2
done
exit 1
