# PA3 Performance Report — Replicated Marketplace
CSCI/ECEN 5673: Distributed Systems, Spring 2026

## Test Environment

- **Cloud Provider**: Google Cloud Platform (GCP)
- **VM Type**: e2-micro (0.25 vCPU shared, 1 GB RAM) x 4
- **Region**: us-central1-a
- **Total Processes**: 19 across 4 VMs (5 Customer DB, 5 Product DB, 4 Seller Servers, 4 Buyer Servers, 1 Financial Service)
- **Benchmark Parameters**: 100 API calls per client per run, 5 runs per configuration

## Methodology

Each benchmark configuration combines one **concurrency level** with one **failure scenario**:

**Concurrency Level:**
- Scenario 1: 1 seller + 1 buyer (2 concurrent clients)

**Failure Scenarios:**
- No Failure — all replicas running normally
- Frontend Fail — kill one seller server (port 5013) + one buyer server (port 5014) mid-test
- Follower Fail — kill one product DB Raft follower mid-test
- Leader Fail — kill the product DB Raft leader mid-test

Operations cycle in round-robin: register_item, get_items, change_price, change_quantity, get_rating (seller); search, get_item, validate_cart, save_cart, get_rating (buyer). Failure is injected ~30% into each run via SSH `pkill`.

---

## Results: Scenario 1 (1 Seller + 1 Buyer)

| Failure Scenario | Throughput (ops/s) | Avg Read (ms) | Avg Write (ms) |
|---|---|---|---|
| No Failure | 8.3 | 128 | 319 |
| Frontend Fail | 8.0 | 136 | 346 |
| Follower Fail | 2.7 | 482 | 909 |
| Leader Fail | 2.2 | 614 | 1073 |

### Per-Function Response Times (No Failure baseline)

| Function | Avg (ms) | Stdev (ms) | Type |
|---|---|---|---|
| seller.login | 127.8 | 12.7 | Read (Atomic Broadcast DB) |
| seller.get_seller_items | 127.1 | 1.3 | Read (Raft DB) |
| seller.get_seller_rating | 126.4 | 2.9 | Read (Raft DB) |
| seller.create_account | 140.3 | 17.1 | Write (Atomic Broadcast) |
| seller.register_item | 328.6 | 13.8 | Write (Raft) |
| seller.change_price | 320.4 | 11.5 | Write (Raft) |
| seller.change_quantity | 309.7 | 3.7 | Write (Raft) |
| seller.logout | 150.8 | 11.9 | Write (Atomic Broadcast) |
| buyer.login | 129.3 | 12.1 | Read (Atomic Broadcast DB) |
| buyer.search_items | 131.5 | 8.0 | Read (Raft DB) |
| buyer.get_item | 127.1 | 1.0 | Read (Raft DB) |
| buyer.get_seller_rating | 129.0 | 1.1 | Read (Raft DB) |
| buyer.validate_cart | 128.0 | 1.9 | Read (Raft DB) |
| buyer.create_account | 159.0 | 70.5 | Write (Atomic Broadcast) |
| buyer.save_cart | 325.9 | 10.0 | Write (Raft) |
| buyer.logout | 149.0 | 10.1 | Write (Atomic Broadcast) |

*Full per-function results for all 4 configurations are in `benchmark_pa3_results.json`.*

---

## Analysis

### 1. Replication Overhead (Read vs Write)

Write operations are **2.5x slower** than reads due to consensus protocols:

- **Read operations** (~128ms): Served directly from local in-memory state (Raft) or local SQLite (Atomic Broadcast). Latency is dominated by internet RTT between client and server.
- **Raft writes** (~320ms): register_item, change_price, change_quantity, save_cart. Each write goes through: leader append → replicate to majority (3/5 nodes) → commit → respond. The Raft consensus adds ~190ms over baseline RTT.
- **Atomic Broadcast writes** (~150ms): create_account, login session creation, logout. Lower overhead than Raft because the UDP-based broadcast protocol has less per-message overhead than PySyncObj's TCP-based Raft.

### 2. Fault Tolerance Impact

| Failure Type | Throughput Impact | Mechanism |
|---|---|---|
| Frontend Fail | -4% (8.3 → 8.0 ops/s) | Client StubPool retries on next replica; transparent failover |
| Follower Fail | -68% (8.3 → 2.7 ops/s) | Raft cluster loses one node; gRPC stub pool retries hit the killed replica before failover, adding ~10s timeout per failed attempt |
| Leader Fail | -74% (8.3 → 2.2 ops/s) | Raft re-election stall (~1-2s) plus gRPC failover delays; all writes block until new leader elected |

**Key findings:**
- **Frontend failures** are nearly invisible to clients. The `StubPool` (gRPC) and client-side retry logic mask failures within a single request timeout. Throughput drops only 4%.
- **Follower failures** cause significant throughput degradation because the gRPC stub pool includes the killed replica's address. Each failed attempt incurs a 10-second timeout before retrying the next replica. Latencies jump from ~128ms to ~482ms for reads and ~319ms to ~909ms for writes.
- **Leader failures** are the most disruptive. Raft re-election takes 0.4-1.4 seconds (configured timeout range), and write operations stall until a new leader is elected. Combined with gRPC failover overhead, throughput drops 74%. However, the system remains fully functional — no data loss, no crashes, and all 16 operations continue to work.

### 3. PA2 vs PA3 Comparison (Scenario 1)

| Metric | PA2 (single DB) | PA3 (replicated) | Overhead |
|---|---|---|---|
| Read latency | ~70ms | ~128ms | +83% (Raft/broadcast overhead) |
| Write latency | ~90ms | ~319ms | +254% (consensus cost) |
| Throughput | 17.1 ops/s | 8.3 ops/s | -51% |

The throughput reduction comes from writes needing majority agreement across 5 replicas. Reads are slower than PA2 due to additional gRPC stub pool routing and the overhead of maintaining consensus state. This is the fundamental trade-off: **fault tolerance requires consensus, and consensus costs latency**.

### 4. Atomic Broadcast vs Raft Performance

| Protocol | Avg Write Latency | Transport |
|---|---|---|
| Atomic Broadcast (Customer DB) | ~150ms | UDP, custom |
| Raft (Product DB) | ~320ms | TCP, PySyncObj |

Atomic Broadcast writes are ~2x faster than Raft writes because:
1. **UDP vs TCP**: UDP avoids connection overhead and TCP slow-start
2. **Simpler protocol**: Broadcast → Sequence → ACK vs Raft's more complex log replication
3. **No leader bottleneck**: The rotating sequencer distributes load across nodes, while Raft funnels all writes through a single leader

However, Raft provides stronger guarantees (total order + exactly-once delivery + crash recovery from persistent log), which justifies the additional overhead.

---

## Conclusion

The replicated marketplace successfully handles all four failure scenarios with graceful degradation. Frontend failures are nearly invisible to clients (4% throughput drop), while database failures cause more significant but recoverable degradation (68-74% throughput drop due to gRPC failover timeouts). The system never crashes, loses data, or deadlocks under any failure scenario — all 16 API operations continue to function. The primary cost of replication is a 51% throughput reduction compared to PA2's single-database design, with write latency increasing 2.5x due to consensus overhead. On production hardware with more CPU headroom and optimized gRPC timeout settings, the failover penalty would be substantially smaller.
