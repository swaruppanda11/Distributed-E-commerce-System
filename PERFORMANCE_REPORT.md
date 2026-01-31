# Performance Evaluation Report
CSCI/ECEN 5673: Distributed Systems - PA1

## Experiment Setup

- All 4 servers running on localhost (single machine)
- Each client performs 1000 API operations per run
- 10 iterations per scenario, results averaged
- Operations: CreateAccount, Login, RegisterItem, Search, AddToCart, DisplayCart, etc.

## Results

| Scenario | Avg Response Time | Avg Throughput |
|----------|------------------|----------------|
| 1 seller + 1 buyer | 2.03 ms (±0.26) | 964 ops/sec (±167) |
| 10 sellers + 10 buyers | 35.52 ms (±15.95) | 636 ops/sec (±273) |
| 100 sellers + 100 buyers | 130.37 ms (±70.61) | 1428 ops/sec (±319) |

## Analysis

**Response Time increases with concurrency** (2ms → 36ms → 130ms):
- More clients compete for server threads and CPU time
- Thread scheduling and context switching overhead increases
- Each TCP connection incurs setup/teardown costs

**Throughput dips at 10/10, then recovers at 100/100**:
- At 10/10: Contention overhead outweighs parallelism benefits
- At 100/100: Massive parallelism (200 concurrent clients) compensates for higher per-request latency
- Total work completed per second increases despite slower individual requests

**High variance at 100/100** (±70ms response time):
- Thread scheduling becomes less predictable under heavy load
- Resource contention causes variable delays

## Conclusion

The system successfully handles up to 200 concurrent clients. Performance degrades gracefully with increased load, showing expected trade-offs between latency and throughput in a distributed system.
