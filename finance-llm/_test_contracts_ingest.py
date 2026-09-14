import urllib.request, json, argparse

parser = argparse.ArgumentParser()
parser.add_argument("--year", type=int, default=2025)
parser.add_argument("--max_records", type=int, default=500)
parser.add_argument("--chunk_size", type=int, default=100)
args = parser.parse_args()

req = urllib.request.Request(
    'http://127.0.0.1:8003/contracts/ingest',
    data=json.dumps({"year": args.year, "max_records": args.max_records, "chunk_size": args.chunk_size}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST'
)
r = urllib.request.urlopen(req)
print(r.status, json.dumps(json.loads(r.read()), indent=2, ensure_ascii=False))
