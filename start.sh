
#!/bin/sh
set -eu

streamlit run hartspec_gui/Home.py \
  --server.address=127.0.0.1 \
  --server.port=8501 \
  --server.headless=true \
  --browser.gatherUsageStats=false &
STREAMLIT_PID=$!

cleanup() {
  kill "$STREAMLIT_PID" "$NGINX_PID" 2>/dev/null || true
}
NGINX_PID=""
trap cleanup INT TERM EXIT

# Wait up to 60 seconds for Streamlit to become healthy.
i=0
until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2)" >/dev/null 2>&1; do
  if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
    echo "Streamlit exited before becoming healthy." >&2
    exit 1
  fi
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "Streamlit did not become healthy within 60 seconds." >&2
    exit 1
  fi
  sleep 2
done

nginx -g 'daemon off;' &
NGINX_PID=$!

while kill -0 "$STREAMLIT_PID" 2>/dev/null && kill -0 "$NGINX_PID" 2>/dev/null; do
  sleep 2
done
exit 1
