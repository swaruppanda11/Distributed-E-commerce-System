# Performance Evaluation Report

**CSCI/ECEN 5673: Distributed Systems - Programming Assignment 1**
**Author:** Swarup Panda
**Date:** January 2026

---

## Experiment Setup

### Hardware Configuration
- **Machine:** MacBook Pro (Apple Silicon)
- **OS:** macOS
- **All components co-located** on localhost (single machine)

### Software Configuration
- **Language:** Python 3.x
- **Communication:** TCP sockets with JSON message protocol
- **Threading:** Thread-per-connection model

### Server Configuration
| Component | Host | Port |
|-----------|------|------|
| Customer Database | localhost | 5001 |
| Product Database | localhost | 5002 |
| Seller Server | localhost | 5003 |
| Buyer Server | localhost | 5004 |

### Test Parameters
- **Operations per client:** 1000 API calls
- **Iterations per scenario:** 10 runs
- **Metrics averaged** across all runs

### Client Workload Distribution

**Seller Operations (per 1000 calls):**
| Operation | Percentage |
|-----------|------------|
| CreateAccount | 1 call |
| Login | 1 call |
| RegisterItemForSale | ~20% |
| ChangeItemPrice | ~20% |
| UpdateUnitsForSale | ~20% |
| DisplayItemsForSale | ~20% |
| GetSellerRating | ~20% |
| Logout | 1 call |

**Buyer Operations (per 1000 calls):**
| Operation | Percentage |
|-----------|------------|
| CreateAccount | 1 call |
| Login | 1 call |
| SearchItemsForSale | ~25% |
| GetItem | ~15% |
| AddItemToCart | ~15% |
| DisplayCart | ~15% |
| ClearCart | ~10% |
| GetSellerRating | ~20% |
| Logout | 1 call |

---

## Results

### Summary Table

| Scenario | Concurrent Clients | Avg Response Time | Std Dev | Avg Throughput | Std Dev |
|----------|-------------------|-------------------|---------|----------------|---------|
| 1 | 1 seller + 1 buyer | 2.03 ms | 0.26 ms | 963.67 ops/sec | 166.92 |
| 2 | 10 sellers + 10 buyers | 35.52 ms | 15.95 ms | 635.73 ops/sec | 273.07 |
| 3 | 100 sellers + 100 buyers | 130.37 ms | 70.61 ms | 1427.86 ops/sec | 319.00 |

### Detailed Results

#### Scenario 1: 1 Seller + 1 Buyer
- **Total operations per run:** 2,000 (1,000 per client)
- **Average Response Time:** 2.03 ms (SD: 0.26 ms)
- **Average Throughput:** 963.67 ops/sec (SD: 166.92 ops/sec)

#### Scenario 2: 10 Sellers + 10 Buyers
- **Total operations per run:** 20,000 (1,000 per client)
- **Average Response Time:** 35.52 ms (SD: 15.95 ms)
- **Average Throughput:** 635.73 ops/sec (SD: 273.07 ops/sec)

#### Scenario 3: 100 Sellers + 100 Buyers
- **Total operations per run:** 200,000 (1,000 per client)
- **Average Response Time:** 130.37 ms (SD: 70.61 ms)
- **Average Throughput:** 1427.86 ops/sec (SD: 319.00 ops/sec)

---

## Analysis

### Response Time Observations

**Trend:** Response time increases significantly with the number of concurrent clients.

| Scenario | Response Time | Increase Factor |
|----------|--------------|-----------------|
| 1 → 2 | 2.03 ms → 35.52 ms | ~17.5x |
| 2 → 3 | 35.52 ms → 130.37 ms | ~3.7x |
| 1 → 3 | 2.03 ms → 130.37 ms | ~64x |

**Explanation:**
1. **Thread Contention:** With more concurrent clients, threads compete for CPU time, causing scheduling delays
2. **Socket Overhead:** Each request creates a new TCP connection (connection-per-request model), increasing overhead at high concurrency
3. **Server-side Locking:** Python's Global Interpreter Lock (GIL) limits true parallelism for CPU-bound operations
4. **Database Contention:** Multiple threads accessing shared in-memory data structures cause lock contention

### Throughput Observations

**Trend:** Throughput shows a non-linear pattern - dipping at moderate concurrency then recovering at high concurrency.

| Scenario | Throughput | Observation |
|----------|------------|-------------|
| 1 | 963.67 ops/sec | Baseline (limited by sequential execution) |
| 2 | 635.73 ops/sec | **Decreased** (contention > parallelism gains) |
| 3 | 1427.86 ops/sec | **Increased** (parallelism compensates for latency) |

**Explanation:**

1. **Scenario 1 (Low Concurrency):**
   - Only 2 clients running sequentially
   - Throughput limited by round-trip latency
   - Low overhead, consistent performance

2. **Scenario 2 (Moderate Concurrency):**
   - 20 concurrent clients introduce contention overhead
   - Thread scheduling and context switching costs increase
   - Parallelism gains don't offset the overhead
   - "Worst of both worlds" - enough clients to cause contention, not enough to amortize it

3. **Scenario 3 (High Concurrency):**
   - 200 concurrent clients maximize parallelism
   - While individual requests are slower (130ms vs 2ms), many more requests execute simultaneously
   - **Throughput = Total Operations / Wall-Clock Time**
   - Massive parallelism means more total work completed per second despite higher per-request latency

### Performance Trade-offs

The results demonstrate a classic distributed systems trade-off:

| Metric | Low Concurrency | High Concurrency |
|--------|-----------------|------------------|
| **Latency** | Low (2ms) | High (130ms) |
| **Throughput** | Moderate | High |
| **Consistency** | High (low variance) | Lower (high variance) |

---

## Insights and Discussion

### Why Response Time Degrades

1. **Connection Overhead:** Creating a new TCP socket for each request incurs:
   - Socket creation and destruction
   - TCP handshake (SYN, SYN-ACK, ACK)
   - No connection reuse benefits

2. **Thread Management:** The thread-per-connection model:
   - Creates overhead for thread creation/destruction
   - Causes context switching costs
   - Limited by OS thread scheduling

3. **Shared State Access:** In-memory dictionaries require synchronization:
   - Python's GIL serializes access
   - Multiple threads waiting for locks

### Why Throughput Recovers at High Concurrency

Despite 64x higher latency, Scenario 3 achieves ~1.5x higher throughput because:

1. **Parallelism:** 200 clients working simultaneously vs 2 clients
2. **Amortized Overhead:** Fixed costs (server overhead) spread across more operations
3. **I/O Bound Nature:** While one request waits for I/O, others can execute

### Variability Analysis

The standard deviation increases with concurrency:
- Scenario 1: SD = 0.26 ms (12.8% of mean)
- Scenario 2: SD = 15.95 ms (44.9% of mean)
- Scenario 3: SD = 70.61 ms (54.2% of mean)

**Cause:** At high concurrency, performance becomes less predictable due to:
- Variable thread scheduling
- Network stack queuing
- Garbage collection pauses
- OS-level resource contention

---

## Potential Optimizations

Based on the evaluation results, the following optimizations could improve performance:

1. **Connection Pooling:** Reuse TCP connections instead of creating new ones per request
2. **Async I/O:** Use `asyncio` instead of threads to reduce context switching
3. **Batching:** Combine multiple operations into single requests
4. **Read Replicas:** Distribute read operations across multiple database instances
5. **Caching:** Cache frequently accessed data at the frontend servers

---

## Conclusion

The evaluation demonstrates that the distributed marketplace system:

1. **Functions correctly** under all tested load conditions
2. **Scales reasonably** to 200 concurrent clients
3. **Exhibits expected trade-offs** between latency and throughput
4. **Maintains stability** even under high load (only 1 failure in 2+ million operations)

The system meets all PA1 requirements and provides a solid foundation for future enhancements including connection pooling, database replication (PA2), and RPC-based communication (PA3).
