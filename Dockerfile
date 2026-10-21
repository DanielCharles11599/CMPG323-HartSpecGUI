FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=127.0.0.1 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    DASH_BRIDGE_PORT=8050 \
    HARTSPEC_DASH_PREFIX=/baseline/ \
    SESSIONS_PATH=/tmp/hartspec-sessions \
    FITS_ARCHIVE_PATH=/opt/hartspec/data/fits

WORKDIR /opt/hartspec

RUN apt-get update && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/hartspec/data/fits /tmp/hartspec-sessions

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY clc ./clc
COPY hartspec_gui ./hartspec_gui
COPY data/fits ./data/fits
COPY nginx.conf /etc/nginx/nginx.conf
COPY start.sh ./start.sh
RUN chmod +x ./start.sh

EXPOSE 10000
CMD ["./start.sh"]
