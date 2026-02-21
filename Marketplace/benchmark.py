"""
PA2 Performance Benchmark
Measures average response time and throughput for 3 scenarios:
  Scenario 1:   1 concurrent seller  +   1 concurrent buyer
  Scenario 2:  10 concurrent sellers +  10 concurrent buyers
  Scenario 3: 100 concurrent sellers + 100 concurrent buyers

Each scenario runs 10 independent runs.
Each client performs 1000 API calls per run.
"""

import requests
import threading
import time
import statistics
import argparse
import uuid
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Configuration ────────────────────────────────────────────────────────────
SELLER_URL = "http://136.116.235.76:5003"
BUYER_URL  = "http://34.172.181.121:5004"

CALLS_PER_RUN = 1000
NUM_RUNS      = 10

SCENARIOS = [
    {"name": "Scenario 1",  "sellers": 1,   "buyers": 1},
    {"name": "Scenario 2",  "sellers": 10,  "buyers": 10},
    {"name": "Scenario 3",  "sellers": 100, "buyers": 100},
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def uid():
    return uuid.uuid4().hex[:8]


def timed_call(fn):
    """Call fn() and return (result, elapsed_seconds)."""
    t0 = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - t0


# ── Seller workload ───────────────────────────────────────────────────────────
def run_seller(seller_url, calls_per_run):
    """
    One seller session: create account, login, then cycle through
    RegisterItem / DisplayItems / ChangePrice / UpdateQuantity / GetRating
    until calls_per_run API calls have been made, then logout.
    Returns list of response times (seconds) for every call.
    """
    session = requests.Session()
    latencies = []
    username = f"s_{uid()}"
    password = "bench"
    registered_item = None   # [category, item_id]

    def call(method, path, **kwargs):
        url = seller_url + path
        t0 = time.perf_counter()
        try:
            resp = session.request(method, url, timeout=15, **kwargs)
            latencies.append(time.perf_counter() - t0)
            return resp.json()
        except Exception:
            return {}

    # CreateAccount + Login (2 calls)
    call("POST", "/seller/account",
         json={"username": username, "password": password, "name": "Bench Seller"})
    resp = call("POST", "/seller/login",
                json={"username": username, "password": password})
    if resp.get("status") != "success":
        return latencies
    session.headers["X-Session-ID"] = resp["session_id"]
    seller_id = resp["seller_id"]

    # Main loop: fill up to calls_per_run
    i = 0
    max_iters = calls_per_run * 3
    while len(latencies) < calls_per_run and i < max_iters:
        op = i % 5
        i += 1

        if op == 0 or registered_item is None:
            r = call("POST", "/seller/items", json={
                "name": f"item_{uid()}", "category": 1,
                "keywords": ["bench"], "condition": "New",
                "price": 9.99, "quantity": 100
            })
            if r.get("status") == "success":
                registered_item = r["item_id"]

        elif op == 1:
            call("GET", "/seller/items")

        elif op == 2 and registered_item:
            cat, iid = registered_item
            call("PUT", f"/seller/items/{cat}/{iid}/price",
                 json={"price": 10.99})

        elif op == 3 and registered_item:
            cat, iid = registered_item
            call("PUT", f"/seller/items/{cat}/{iid}/quantity",
                 json={"quantity": 50})

        elif op == 4:
            call("GET", f"/seller/rating/{seller_id}")

    # Logout
    call("POST", "/seller/logout")
    return latencies[:calls_per_run]


# ── Buyer workload ────────────────────────────────────────────────────────────
def run_buyer(buyer_url, calls_per_run):
    """
    One buyer session: create account, login, then cycle through
    SearchItems / GetItem / AddToCart(validate) / SaveCart / GetSellerRating
    until calls_per_run calls have been made, then logout.
    Returns list of response times (seconds).
    """
    session = requests.Session()
    latencies = []
    username = f"b_{uid()}"
    password = "bench"
    found_item = None   # [category, item_id]
    found_seller = None

    def call(method, path, **kwargs):
        url = buyer_url + path
        t0 = time.perf_counter()
        try:
            resp = session.request(method, url, timeout=15, **kwargs)
            latencies.append(time.perf_counter() - t0)
            return resp.json()
        except Exception:
            return {}

    # CreateAccount + Login (2 calls)
    call("POST", "/buyer/account",
         json={"username": username, "password": password, "name": "Bench Buyer"})
    resp = call("POST", "/buyer/login",
                json={"username": username, "password": password})
    if resp.get("status") != "success":
        return latencies
    session.headers["X-Session-ID"] = resp["session_id"]

    # Main loop
    i = 0
    max_iters = calls_per_run * 3
    while len(latencies) < calls_per_run and i < max_iters:
        op = i % 5
        i += 1

        if op == 0:
            r = call("GET", "/buyer/items", params={"keywords": "bench"})
            if r.get("status") == "success" and r.get("items"):
                item = r["items"][0]
                found_item   = item["item_id"]
                found_seller = item["seller_id"]

        elif op == 1 and found_item:
            cat, iid = found_item
            call("GET", f"/buyer/items/{cat}/{iid}")

        elif op == 2 and found_item:
            call("POST", "/buyer/cart/validate",
                 json={"item_id": found_item, "quantity": 1})

        elif op == 3:
            call("PUT", "/buyer/cart",
                 json={"cart": ([{"item_id": found_item, "quantity": 1}]
                                if found_item else [])})

        elif op == 4 and found_seller:
            call("GET", f"/buyer/seller/{found_seller}/rating")

        else:
            # fallback: search
            call("GET", "/buyer/items")

    # Logout
    call("POST", "/buyer/logout")
    return latencies[:calls_per_run]


# ── Single run ────────────────────────────────────────────────────────────────
def run_scenario_once(num_sellers, num_buyers):
    """
    Spawn num_sellers seller threads and num_buyers buyer threads concurrently.
    Returns (all_latencies, elapsed_wall_seconds).
    """
    all_latencies = []
    lock = threading.Lock()

    def seller_task():
        try:
            lats = run_seller(SELLER_URL, CALLS_PER_RUN)
            with lock:
                all_latencies.extend(lats)
        except Exception:
            pass

    def buyer_task():
        try:
            lats = run_buyer(BUYER_URL, CALLS_PER_RUN)
            with lock:
                all_latencies.extend(lats)
        except Exception:
            pass

    threads = []
    for _ in range(num_sellers):
        threads.append(threading.Thread(target=seller_task))
    for _ in range(num_buyers):
        threads.append(threading.Thread(target=buyer_task))

    t_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t_start

    return all_latencies, elapsed


# ── Benchmark ─────────────────────────────────────────────────────────────────
def benchmark_scenario(scenario):
    name        = scenario["name"]
    num_sellers = scenario["sellers"]
    num_buyers  = scenario["buyers"]

    print(f"\n{'='*60}")
    print(f"  {name}: {num_sellers} seller(s) + {num_buyers} buyer(s)")
    print(f"  {CALLS_PER_RUN} calls/client × {NUM_RUNS} runs")
    print(f"{'='*60}")

    run_latencies   = []   # avg response time per run (ms)
    run_throughputs = []   # throughput per run (ops/sec)

    for run_idx in range(1, NUM_RUNS + 1):
        lats, elapsed = run_scenario_once(num_sellers, num_buyers)
        if not lats:
            print(f"  Run {run_idx:2d}: no data")
            continue

        avg_lat_ms  = statistics.mean(lats) * 1000
        total_calls = len(lats)
        throughput  = total_calls / elapsed

        run_latencies.append(avg_lat_ms)
        run_throughputs.append(throughput)

        print(f"  Run {run_idx:2d}: "
              f"avg_latency={avg_lat_ms:7.2f} ms  "
              f"throughput={throughput:8.1f} ops/s  "
              f"total_calls={total_calls}")

    if run_latencies:
        print(f"\n  --- {name} Summary ---")
        print(f"  Avg response time : {statistics.mean(run_latencies):.2f} ms "
              f"(stdev {statistics.stdev(run_latencies) if len(run_latencies)>1 else 0:.2f})")
        print(f"  Avg throughput    : {statistics.mean(run_throughputs):.1f} ops/s "
              f"(stdev {statistics.stdev(run_throughputs) if len(run_throughputs)>1 else 0:.1f})")

    return {
        "scenario": name,
        "sellers": num_sellers,
        "buyers": num_buyers,
        "avg_response_time_ms": statistics.mean(run_latencies) if run_latencies else None,
        "avg_throughput_ops_per_s": statistics.mean(run_throughputs) if run_throughputs else None,
        "runs": list(zip(run_latencies, run_throughputs))
    }


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PA2 Performance Benchmark")
    parser.add_argument("--seller-url", default=SELLER_URL)
    parser.add_argument("--buyer-url",  default=BUYER_URL)
    parser.add_argument("--scenarios",  nargs="+", type=int,
                        default=[1, 2, 3],
                        help="Which scenarios to run (1, 2, 3)")
    parser.add_argument("--calls", type=int, default=CALLS_PER_RUN,
                        help="API calls per client per run")
    parser.add_argument("--runs",  type=int, default=NUM_RUNS,
                        help="Number of runs per scenario")
    parser.add_argument("--output", default="benchmark_results.json",
                        help="JSON file to save results")
    args = parser.parse_args()

    SELLER_URL    = args.seller_url
    BUYER_URL     = args.buyer_url
    CALLS_PER_RUN = args.calls
    NUM_RUNS      = args.runs

    print("PA2 Performance Benchmark")
    print(f"Seller server : {SELLER_URL}")
    print(f"Buyer server  : {BUYER_URL}")
    print(f"Calls/client  : {CALLS_PER_RUN}")
    print(f"Runs/scenario : {NUM_RUNS}")

    results = []
    for idx in args.scenarios:
        result = benchmark_scenario(SCENARIOS[idx - 1])
        results.append(result)
        # Save after each scenario so results are not lost if later ones take too long
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n[Saved to {args.output}]")

    # Final summary table
    print("\n" + "="*60)
    print("FINAL SUMMARY")
    print("="*60)
    print(f"{'Scenario':<15} {'Sellers':>8} {'Buyers':>8} "
          f"{'Avg RT (ms)':>14} {'Avg TP (ops/s)':>16}")
    print("-"*60)
    for r in results:
        if r["avg_response_time_ms"] is not None:
            print(f"{r['scenario']:<15} {r['sellers']:>8} {r['buyers']:>8} "
                  f"{r['avg_response_time_ms']:>14.2f} "
                  f"{r['avg_throughput_ops_per_s']:>16.1f}")
