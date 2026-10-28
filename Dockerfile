FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching. Live trading needs only the runtime
# libraries, not the research/dev extras — install them explicitly.
RUN pip install --no-cache-dir pandas numpy ccxt requests python-dotenv

COPY bot/ ./bot/
COPY run.py ./

# State snapshots + logs go here; mount a volume at this path so they persist.
ENV TRADER_DATA_DIR=/app/var
RUN mkdir -p /app/var

# DEMO by default — never default to a live account in an image.
ENV IG_DEMO=true

ENTRYPOINT ["python", "run.py", "--live"]
CMD ["--timeframe", "1h"]
