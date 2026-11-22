"""Capture the public Bitstamp BTC/USD OHLC observations used in the revision."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


START = date(2017, 12, 31)
END = date(2025, 12, 31)
ENDPOINT = "https://www.bitstamp.net/api/v2/ohlc/btcusd/"
OUTPUT = Path(__file__).resolve().parent / "raw/bitstamp-btcusd-daily.json"


def timestamp(day):
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())


def capture():
    if OUTPUT.exists():
        raise SystemExit(f"Capture already exists at {OUTPUT}.")
    start = START
    pages, rows = [], {}
    while start <= END:
        end = min(start + timedelta(days=729), END)
        query = urlencode({"step": 86400, "limit": 1000, "start": timestamp(start),
                           "end": timestamp(end + timedelta(days=1)), "exclude_current_candle": "true"})
        url = ENDPOINT + "?" + query
        request = Request(url, headers={"User-Agent": "Fulcrum-Research/1.1"})
        with urlopen(request, timeout=25) as response:
            payload = json.load(response)
        bars = payload["data"]["ohlc"]
        pages.append({"url": url, "rows_received": len(bars)})
        for bar in bars:
            key = int(bar["timestamp"])
            if not timestamp(START) <= key <= timestamp(END):
                continue
            entry = {field: bar[field] for field in ("timestamp", "open", "high", "low", "close", "volume")}
            if key in rows and rows[key] != entry:
                raise ValueError(f"Bitstamp returned incompatible bars for {key}.")
            rows[key] = entry
        start = end + timedelta(days=1)
    expected = range(timestamp(START), timestamp(END) + 86400, 86400)
    if sorted(rows) != list(expected):
        raise ValueError(f"Expected {len(expected)} complete daily bars, received {len(rows)}.")
    record = {"source": ENDPOINT, "captured_utc": datetime.now(UTC).isoformat(),
              "requests": pages, "bars": [rows[key] for key in sorted(rows)]}
    with OUTPUT.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, indent=2)
        file.write("\n")
    print(f"Retained {len(rows)} complete BTC/USD bars in {OUTPUT.name}.")


if __name__ == "__main__":
    capture()
