FROM python:3.12-slim

WORKDIR /app

# Runtime libraries only (no research/dev extras). fastapi + uvicorn serve the
# read-only portal from the same image.
RUN pip install --no-cache-dir pandas numpy ccxt requests python-dotenv \
    yfinance fastapi uvicorn

COPY bot/ ./bot/
COPY portal/ ./portal/
COPY run.py ./

# trading.db + trader.log go here; mount a volume at this path so they persist.
ENV TRADER_DATA_DIR=/app/var
RUN mkdir -p /app/var

# DEMO by default — never default to a live account in an image.
ENV IG_DEMO=true

# Paper-live (real data, fake money) is the safe default. Switch the compose
# `command` to ["--live", "--timeframe", "1d"] only after the demo phase.
ENTRYPOINT ["python", "run.py"]
CMD ["--paperlive"]
