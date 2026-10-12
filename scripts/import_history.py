"""Fetch a documented public daily BTC price series; no invented market data."""
import csv
import hashlib
import io
import json
import urllib.request
from pathlib import Path

# Pinned GitHub revision is supplied via --revision to make updates explicit.
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--revision', required=True)
args = parser.parse_args()
url = f'https://raw.githubusercontent.com/coinmetrics/data/{args.revision}/csv/btc.csv'
with urllib.request.urlopen(url, timeout=60) as response:
    raw = response.read()
rows = [(r['time'], r['PriceUSD']) for r in csv.DictReader(io.StringIO(raw.decode())) if r['time'] >= '2022-01-01' and r['PriceUSD']]
out = Path(__file__).resolve().parents[1] / 'data'
with (out/'btc_daily.csv').open('w') as f:
    writer = csv.writer(f)
    writer.writerow(['date', 'price'])
    writer.writerows(rows)
(out/'history_source.json').write_text(json.dumps(dict(provider='Coin Metrics community data', url=url,
    upstream_sha256=hashlib.sha256(raw).hexdigest(), dataset_sha256=hashlib.sha256((out/'btc_daily.csv').read_bytes()).hexdigest(),
    field='PriceUSD', first=rows[0][0], last=rows[-1][0], observations=len(rows),
    note='Дневные справочные цены, не OHLC или цены исполнения Coinbase. CC BY 4.0, атрибуция Coin Metrics.',
    license='https://creativecommons.org/licenses/by/4.0/'), ensure_ascii=False, indent=2)+'\n')
print(f'Imported {len(rows)} actual daily observations: {rows[0][0]} — {rows[-1][0]}')
