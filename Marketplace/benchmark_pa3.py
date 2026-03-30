"""
PA3 Performance Benchmark

Measures average response time (per client function) and throughput
across 4 failure scenarios and 3 concurrency levels = 12 configurations.

Failure scenarios:
  1. no_failure        — all replicas running normally
  2. frontend_fail     — one seller server + one buyer server replica killed mid-test
  3. follower_fail     — one product DB replica (non-leader) killed mid-test
  4. leader_fail       — product DB leader killed mid-test

Concurrency scenarios:
  Scenario 1:   1 seller  +   1 buyer
  Scenario 2:  10 sellers +  10 buyers
  Scenario 3: 100 sellers + 100 buyers

Each client makes CALLS_PER_RUN API calls per run, averaged over NUM_RUNS.
"""

import requests
import threading
import time
import statistics
import argparse
import uuid
import json
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Defaults ─────────────────────────────────────────────────────────────────
CALLS_PER_RUN = 1000
NUM_RUNS      = 10

# Seller and buyer server URLs (multiple for failover)
SELLER_URLS = ["http://localhost:5003"]
BUYER_URLS  = ["http://localhost:5004"]

CONCURRENCY_SCENARIOS = [
    {"name": "Scenario 1",  "sellers": 1,   "buyers": 1},
    {"name": "Scenario 2",  "sellers": 10,  "buyers": 10},
    {"name": "Scenario 3",  "sellers": 100, "buyers": 100},
]

FAILURE_SCENARIOS = [
    {"name": "no_failure",     "description": "All replicas running normally"},
    {"name": "frontend_fail",  "description": "One seller + one buyer server replica fail"},
    {"name": "follower_fail",  "description": "One product DB replica (non-leader) fails"},
    {"name": "leader_fail",    "description": "Product DB leader fails"},
]

# SSH-based failure injection commands (configured per deployment)
# Set via --gcp-project and --gcp-zone, or overridden manually
GCP_PROJECT = ""
GCP_ZONE = ""

# Process kill targets for each failure scenario (configured at runtime)
FAILURE_TARGETS = {
    "frontend_fail": {
        "description": "Kill one seller-server and one buyer-server process",
        "commands": [],  # populated at runtime
    },
    "follower_fail": {
        "description": "Kill one non-leader product DB replica",
        "commands": [],
    },
    "leader_fail": {
        "description": "Kill the product DB Raft leader",
        "commands": [],
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────────
def uid():
    return uuid.uuid4().hex[:8]


def pick_url(urls, idx=0):
    """Round-robin URL selection."""
    return urls[idx % len(urls)]


def ssh_kill(vm_name, process_pattern):
    """Kill a process on a GCP VM via SSH."""
    if not GCP_PROJECT or not GCP_ZONE:
        print(f"  [SKIP] Cannot kill '{process_pattern}' on {vm_name} — GCP not configured")
        return False
    cmd = (
        f"gcloud compute ssh {vm_name} "
        f"--project={GCP_PROJECT} --zone={GCP_ZONE} "
        f"--command='pkill -f \"{process_pattern}\"'"
    )
    print(f"  [KILL] {vm_name}: pkill -f '{process_pattern}'")
    try:
        subprocess.run(cmd, shell=True, timeout=15, capture_output=True)
        return True
    except Exception as e:
        print(f"  [ERROR] Kill failed: {e}")
        return False


def inject_failure(failure_name):
    """Execute failure injection for the given scenario."""
    if failure_name == "no_failure":
        return
    targets = FAILURE_TARGETS.get(failure_name, {})
    commands = targets.get("commands", [])
    if not commands:
        print(f"  [WARN] No kill commands configured for '{failure_name}'")
        return
    for vm_name, pattern in commands:
        ssh_kill(vm_name, pattern)
    time.sleep(3)  # allow failover / leader election to settle


# ── Seller workload ──────────────────────────────────────────────────────────
def run_seller(seller_urls, calls_per_run, client_idx=0):
    """
    One seller session: create account, login, cycle through operations.
    Returns dict of {operation_name: [latencies]}.
    """
    session = requests.Session()
    latencies = defaultdict(list)
    username = f"s_{uid()}"
    password = "bench"
    registered_item = None
    total_calls = 0
    url_idx = client_idx % len(seller_urls)

    def call(op_name, method, path, **kwargs):
        nonlocal total_calls, url_idx
        for attempt in range(len(seller_urls)):
            base = seller_urls[(url_idx + attempt) % len(seller_urls)]
            url = base + path
            t0 = time.perf_counter()
            try:
                resp = session.request(method, url, timeout=10, **kwargs)
                elapsed = time.perf_counter() - t0
                latencies[op_name].append(elapsed)
                total_calls += 1
                url_idx = (url_idx + attempt) % len(seller_urls)
                return resp.json()
            except (requests.ConnectionError, requests.Timeout):
                continue
            except Exception:
                return {}
        return {}

    # CreateAccount + Login
    call("create_account", "POST", "/seller/account",
         json={"username": username, "password": password, "name": "Bench Seller"})
    resp = call("login", "POST", "/seller/login",
                json={"username": username, "password": password})
    if resp.get("status") != "success":
        return dict(latencies)
    session.headers["X-Session-ID"] = resp["session_id"]
    seller_id = resp["seller_id"]

    i = 0
    max_iters = calls_per_run * 3
    while total_calls < calls_per_run and i < max_iters:
        op = i % 5
        i += 1

        if op == 0 or registered_item is None:
            r = call("register_item", "POST", "/seller/items", json={
                "name": f"item_{uid()}", "category": 1,
                "keywords": ["bench"], "condition": "New",
                "price": 9.99, "quantity": 100
            })
            if r.get("status") == "success":
                registered_item = r["item_id"]

        elif op == 1:
            call("get_seller_items", "GET", "/seller/items")

        elif op == 2 and registered_item:
            cat, iid = registered_item
            call("change_price", "PUT", f"/seller/items/{cat}/{iid}/price",
                 json={"price": 10.99})

        elif op == 3 and registered_item:
            cat, iid = registered_item
            call("change_quantity", "PUT", f"/seller/items/{cat}/{iid}/quantity",
                 json={"quantity": 50})

        elif op == 4:
            call("get_seller_rating", "GET", f"/seller/rating/{seller_id}")

    call("logout", "POST", "/seller/logout")
    return dict(latencies)


# ── Buyer workload ───────────────────────────────────────────────────────────
def run_buyer(buyer_urls, calls_per_run, client_idx=0):
    """
    One buyer session: create account, login, cycle through operations.
    Returns dict of {operation_name: [latencies]}.
    """
    session = requests.Session()
    latencies = defaultdict(list)
    username = f"b_{uid()}"
    password = "bench"
    found_item = None
    found_seller = None
    total_calls = 0
    url_idx = client_idx % len(buyer_urls)

    def call(op_name, method, path, **kwargs):
        nonlocal total_calls, url_idx
        for attempt in range(len(buyer_urls)):
            base = buyer_urls[(url_idx + attempt) % len(buyer_urls)]
            url = base + path
            t0 = time.perf_counter()
            try:
                resp = session.request(method, url, timeout=10, **kwargs)
                elapsed = time.perf_counter() - t0
                latencies[op_name].append(elapsed)
                total_calls += 1
                url_idx = (url_idx + attempt) % len(buyer_urls)
                return resp.json()
            except (requests.ConnectionError, requests.Timeout):
                continue
            except Exception:
                return {}
        return {}

    # CreateAccount + Login
    call("create_account", "POST", "/buyer/account",
         json={"username": username, "password": password, "name": "Bench Buyer"})
    resp = call("login", "POST", "/buyer/login",
                json={"username": username, "password": password})
    if resp.get("status") != "success":
        return dict(latencies)
    session.headers["X-Session-ID"] = resp["session_id"]

    i = 0
    max_iters = calls_per_run * 3
    while total_calls < calls_per_run and i < max_iters:
        op = i % 5
        i += 1

        if op == 0:
            r = call("search_items", "GET", "/buyer/items", params={"keywords": "bench"})
            if r.get("status") == "success" and r.get("items"):
                item = r["items"][0]
                found_item = item["item_id"]
                found_seller = item["seller_id"]

        elif op == 1 and found_item:
            cat, iid = found_item
            call("get_item", "GET", f"/buyer/items/{cat}/{iid}")

        elif op == 2 and found_item:
            call("validate_cart", "POST", "/buyer/cart/validate",
                 json={"item_id": found_item, "quantity": 1})

        elif op == 3:
            call("save_cart", "PUT", "/buyer/cart",
                 json={"cart": ([{"item_id": found_item, "quantity": 1}]
                                if found_item else [])})

        elif op == 4 and found_seller:
            call("get_seller_rating", "GET", f"/buyer/seller/{found_seller}/rating")

        else:
            call("search_items", "GET", "/buyer/items")

    call("logout", "POST", "/buyer/logout")
    return dict(latencies)


# ── Single run ───────────────────────────────────────────────────────────────
def run_once(num_sellers, num_buyers, failure_name="no_failure", inject_at_pct=30):
    """
    Spawn seller + buyer threads. Optionally inject failure mid-test.
    Returns (per_function_latencies: dict, elapsed_wall_seconds: float).
    """
    all_latencies = defaultdict(list)
    lock = threading.Lock()
    failure_injected = threading.Event()

    def seller_task(idx):
        lats = run_seller(SELLER_URLS, CALLS_PER_RUN, client_idx=idx)
        with lock:
            for op, times in lats.items():
                all_latencies[f"seller.{op}"].extend(times)

    def buyer_task(idx):
        lats = run_buyer(BUYER_URLS, CALLS_PER_RUN, client_idx=idx)
        with lock:
            for op, times in lats.items():
                all_latencies[f"buyer.{op}"].extend(times)

    threads = []
    for i in range(num_sellers):
        threads.append(threading.Thread(target=seller_task, args=(i,)))
    for i in range(num_buyers):
        threads.append(threading.Thread(target=buyer_task, args=(i,)))

    t_start = time.perf_counter()
    for t in threads:
        t.start()

    # Inject failure at inject_at_pct% through the test
    if failure_name != "no_failure":
        def delayed_inject():
            # Wait for roughly inject_at_pct% of expected duration
            # Estimate: each client does ~100 calls/sec baseline
            estimated_secs = CALLS_PER_RUN / 100.0
            wait = estimated_secs * inject_at_pct / 100.0
            time.sleep(max(wait, 2.0))
            inject_failure(failure_name)
            failure_injected.set()

        inject_thread = threading.Thread(target=delayed_inject, daemon=True)
        inject_thread.start()

    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t_start

    return dict(all_latencies), elapsed


# ── Benchmark one configuration ─────────────────────────────────────────────
def benchmark_config(concurrency, failure):
    """Run one (concurrency x failure) configuration across NUM_RUNS."""
    c_name = concurrency["name"]
    f_name = failure["name"]
    num_sellers = concurrency["sellers"]
    num_buyers = concurrency["buyers"]

    print(f"\n{'='*70}")
    print(f"  {c_name} | {f_name}: {num_sellers} seller(s) + {num_buyers} buyer(s)")
    print(f"  {failure['description']}")
    print(f"  {CALLS_PER_RUN} calls/client x {NUM_RUNS} runs")
    print(f"{'='*70}")

    # Accumulate per-function latencies across runs
    all_runs_latencies = defaultdict(list)  # fn_name -> [avg_ms per run]
    run_throughputs = []

    for run_idx in range(1, NUM_RUNS + 1):
        per_fn, elapsed = run_once(num_sellers, num_buyers, failure_name=f_name)

        total_calls = sum(len(v) for v in per_fn.values())
        if total_calls == 0:
            print(f"  Run {run_idx:2d}: no data")
            continue

        throughput = total_calls / elapsed
        run_throughputs.append(throughput)

        # Per-function average for this run
        run_fn_avgs = {}
        for fn, times in per_fn.items():
            avg_ms = statistics.mean(times) * 1000
            run_fn_avgs[fn] = avg_ms
            all_runs_latencies[fn].append(avg_ms)

        overall_avg = statistics.mean(
            t * 1000 for times in per_fn.values() for t in times
        )

        print(f"  Run {run_idx:2d}: avg_latency={overall_avg:7.2f} ms  "
              f"throughput={throughput:8.1f} ops/s  calls={total_calls}")

    # Summary
    result = {
        "concurrency": c_name,
        "failure": f_name,
        "sellers": num_sellers,
        "buyers": num_buyers,
        "per_function": {},
        "avg_throughput_ops_per_s": None,
    }

    if run_throughputs:
        result["avg_throughput_ops_per_s"] = statistics.mean(run_throughputs)

    print(f"\n  --- Per-function average response times ---")
    for fn in sorted(all_runs_latencies.keys()):
        avgs = all_runs_latencies[fn]
        mean_ms = statistics.mean(avgs)
        result["per_function"][fn] = {
            "avg_ms": round(mean_ms, 3),
            "stdev_ms": round(statistics.stdev(avgs), 3) if len(avgs) > 1 else 0,
        }
        print(f"  {fn:<30s}  {mean_ms:8.2f} ms")

    if result["avg_throughput_ops_per_s"]:
        print(f"\n  Avg throughput: {result['avg_throughput_ops_per_s']:.1f} ops/s")

    return result


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PA3 Performance Benchmark")
    parser.add_argument("--seller-urls", type=str,
                        default=",".join(SELLER_URLS),
                        help="Comma-separated seller server URLs")
    parser.add_argument("--buyer-urls", type=str,
                        default=",".join(BUYER_URLS),
                        help="Comma-separated buyer server URLs")
    parser.add_argument("--calls", type=int, default=CALLS_PER_RUN,
                        help="API calls per client per run")
    parser.add_argument("--runs", type=int, default=NUM_RUNS,
                        help="Number of runs per scenario")
    parser.add_argument("--scenarios", nargs="+", type=int, default=[1, 2, 3],
                        help="Which concurrency scenarios to run (1, 2, 3)")
    parser.add_argument("--failures", nargs="+", type=str,
                        default=["no_failure"],
                        help="Failure scenarios: no_failure, frontend_fail, "
                             "follower_fail, leader_fail")
    parser.add_argument("--gcp-project", type=str, default="",
                        help="GCP project ID for failure injection")
    parser.add_argument("--gcp-zone", type=str, default="",
                        help="GCP zone for failure injection")
    parser.add_argument("--kill-frontend-seller", type=str, default="",
                        help="VM:pattern for killing a seller server, e.g. 'vm-3:seller_server.*5013'")
    parser.add_argument("--kill-frontend-buyer", type=str, default="",
                        help="VM:pattern for killing a buyer server")
    parser.add_argument("--kill-follower", type=str, default="",
                        help="VM:pattern for killing a product DB follower")
    parser.add_argument("--kill-leader", type=str, default="",
                        help="VM:pattern for killing the product DB leader")
    parser.add_argument("--output", default="benchmark_pa3_results.json",
                        help="JSON file to save results")
    args = parser.parse_args()

    SELLER_URLS = [u.strip() for u in args.seller_urls.split(",")]
    BUYER_URLS = [u.strip() for u in args.buyer_urls.split(",")]
    CALLS_PER_RUN = args.calls
    NUM_RUNS = args.runs
    GCP_PROJECT = args.gcp_project
    GCP_ZONE = args.gcp_zone

    # Configure failure targets
    def parse_kill_target(s):
        if not s:
            return []
        parts = s.split(":")
        return [(parts[0], parts[1])]

    FAILURE_TARGETS["frontend_fail"]["commands"] = (
        parse_kill_target(args.kill_frontend_seller) +
        parse_kill_target(args.kill_frontend_buyer)
    )
    FAILURE_TARGETS["follower_fail"]["commands"] = parse_kill_target(args.kill_follower)
    FAILURE_TARGETS["leader_fail"]["commands"] = parse_kill_target(args.kill_leader)

    # Map failure names
    failure_map = {f["name"]: f for f in FAILURE_SCENARIOS}
    selected_failures = []
    for fn in args.failures:
        if fn in failure_map:
            selected_failures.append(failure_map[fn])
        else:
            print(f"Unknown failure scenario: {fn}")

    print("PA3 Performance Benchmark")
    print(f"Seller servers : {SELLER_URLS}")
    print(f"Buyer servers  : {BUYER_URLS}")
    print(f"Calls/client   : {CALLS_PER_RUN}")
    print(f"Runs/scenario  : {NUM_RUNS}")
    print(f"Failures       : {[f['name'] for f in selected_failures]}")

    results = []
    for c_idx in args.scenarios:
        concurrency = CONCURRENCY_SCENARIOS[c_idx - 1]
        for failure in selected_failures:
            result = benchmark_config(concurrency, failure)
            results.append(result)

            with open(args.output, "w") as f:
                json.dump(results, f, indent=2)
            print(f"\n  [Saved to {args.output}]")

    # Final summary table
    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    print(f"{'Concurrency':<15} {'Failure':<18} {'Sellers':>8} {'Buyers':>8} "
          f"{'Avg TP (ops/s)':>16}")
    print("-" * 80)
    for r in results:
        tp = r.get("avg_throughput_ops_per_s")
        tp_str = f"{tp:>16.1f}" if tp else "           N/A"
        print(f"{r['concurrency']:<15} {r['failure']:<18} "
              f"{r['sellers']:>8} {r['buyers']:>8} {tp_str}")

    print(f"\nDetailed per-function results saved to: {args.output}")
