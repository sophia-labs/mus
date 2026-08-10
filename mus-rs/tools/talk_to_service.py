#!/usr/bin/env python3
"""Have a conversation with the warm engine.

Spawns `mus service`, loads a score, renders it twice, and shows you the
memoization: the first render pays the DSP bill, the second returns the
identical digest instantly. Usage:

    python3 mus-rs/tools/talk_to_service.py aigua/aigua_gecs.mus
"""
import json
import subprocess
import sys
import time
from pathlib import Path

score = Path(sys.argv[1] if len(sys.argv) > 1 else "aigua/smoke.mus")
base = score.parent.resolve()
binary = Path(__file__).resolve().parents[1] / "target/release/mus"

svc = subprocess.Popen([str(binary), "service"], stdin=subprocess.PIPE,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

def call(method, params, rid=[0]):
    rid[0] += 1
    svc.stdin.write(json.dumps({"id": rid[0], "method": method, "params": params}) + "\n")
    svc.stdin.flush()
    t0 = time.perf_counter()
    reply = json.loads(svc.stdout.readline())
    ms = (time.perf_counter() - t0) * 1000
    return reply, ms

pong, ms = call("ping", {})
print(f"ping    {ms:8.1f} ms   {pong['result']['service']} / {pong['result']['engine']}")

loaded, ms = call("load", {"source": score.read_text(), "baseDir": str(base)})
key = loaded["result"]["docKey"]
print(f"load    {ms:8.1f} ms   docKey {key[:16]}…")

r1, ms1 = call("renderScore", {"docKey": key})
print(f"render  {ms1:8.1f} ms   {r1['result']['frames']:,} frames  "
      f"peak {r1['result']['peakDbfs']:.1f} dBFS  digest {r1['result']['renderDigest'][:12]}…")

r2, ms2 = call("renderScore", {"docKey": key})
same = r1["result"]["renderDigest"] == r2["result"]["renderDigest"]
print(f"again   {ms2:8.1f} ms   cache hit, identical digest: {same}  "
      f"({ms1 / max(ms2, 0.001):,.0f}x faster)")

svc.terminate()
