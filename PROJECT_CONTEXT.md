# PA2 Project Context — Distributed Marketplace System
CSCI/ECEN 5673: Distributed Systems, Spring 2026
Student: swaruppanda

---

## What This Project Is

A distributed e-commerce marketplace built for PA2. Clients connect to REST servers (Flask), which talk to gRPC database backends (SQLite), with a SOAP financial service for purchases.

---

## Assignment Status

**PA2: COMPLETE AND SUBMITTED** (submitted Feb 20/21 2026, Gradescope)
- Submission ZIP: `/Users/swaruppanda/Desktop/Docs/Distributed Systems/ECommerce - PA1/PA2_submission.zip`

---

## Repository Location

```
/Users/swaruppanda/Desktop/Docs/Distributed Systems/ECommerce - PA1/
├── Marketplace/
│   ├── seller_client.py         # REST client for sellers
│   ├── buyer_client.py          # REST client for buyers (client-side cart)
│   ├── seller_server.py         # Flask REST server, port 5003
│   ├── buyer_server.py          # Flask REST server, port 5004
│   ├── customer_database.py     # gRPC server, port 50051, SQLite
│   ├── product_database.py      # gRPC server, port 50052, SQLite
│   ├── financial_service.py     # SOAP server, port 8000 (90% approval rate)
│   ├── benchmark.py             # Performance benchmark (3 scenarios)
│   ├── benchmark_results.json   # Benchmark output
│   ├── requirements.txt         # pip dependencies
│   ├── proto/
│   │   ├── customer_db.proto
│   │   └── product_db.proto
│   ├── customer_db_pb2.py       # Generated gRPC stubs
│   ├── customer_db_pb2_grpc.py
│   ├── product_db_pb2.py
│   └── product_db_pb2_grpc.py
├── README.md
├── COMMANDS.txt                 # Full command reference for running everything
├── PERFORMANCE_REPORT.md        # Benchmark results + analysis
└── PA2_submission.zip           # Gradescope submission
```

---

## Architecture

```
[Seller Client] --REST/HTTP--> [Seller Server :5003] --gRPC--> [Customer DB :50051]
                                                      --gRPC--> [Product DB  :50052]

[Buyer Client]  --REST/HTTP--> [Buyer Server  :5004] --gRPC--> [Customer DB :50051]
                                                      --gRPC--> [Product DB  :50052]
                                                      --SOAP--> [Financial Svc :8000]
```

- **Client ↔ Server**: REST (Flask + requests library), X-Session-ID header for auth
- **Server ↔ Database**: gRPC (Protocol Buffers)
- **Financial transactions**: SOAP (spyne server, zeep client), 90% approval rate
- **Storage**: SQLite with threading.Lock for thread safety
- **Sessions**: UUID tokens, 5-minute inactivity timeout
- **Cart**: Client-side (in-memory in buyer_client.py), persisted only on explicit "Save Cart"

---

## GCP Cloud Deployment

**Project**: ecommerce-pa2-2026
**Zone**: us-central1-a
**VMs**: All e2-micro instances

| Component | VM Name | External IP | Port | Protocol |
|---|---|---|---|---|
| Customer Database | customer-db | 34.67.115.201 | 50051 | gRPC |
| Product Database | product-db | 35.222.178.52 | 50052 | gRPC |
| Seller Server | seller-server | 136.116.235.76 | 5003 | REST |
| Buyer Server | buyer-server | 34.172.181.121 | 5004 | REST |
| Financial Service | buyer-server | localhost | 8000 | SOAP |

**Current VM Status**: ALL STOPPED (stopped after submission to save credits)

### To restart VMs:
```bash
gcloud compute instances start customer-db product-db seller-server buyer-server \
    --zone=us-central1-a --project=ecommerce-pa2-2026
```

### To stop VMs:
```bash
gcloud compute instances stop customer-db product-db seller-server buyer-server \
    --zone=us-central1-a --project=ecommerce-pa2-2026
```

### To restart services after VM start (SSH into each VM and run):
```bash
# On customer-db VM:
nohup ~/Marketplace/venv/bin/python ~/Marketplace/customer_database.py \
    --host 0.0.0.0 --port 50051 </dev/null >> ~/customer_db.log 2>&1 & disown

# On product-db VM:
nohup ~/Marketplace/venv/bin/python ~/Marketplace/product_database.py \
    --host 0.0.0.0 --port 50052 </dev/null >> ~/product_db.log 2>&1 & disown

# On seller-server VM:
nohup ~/Marketplace/venv/bin/python ~/Marketplace/seller_server.py \
    --host 0.0.0.0 --port 5003 \
    --customer-db-host 34.67.115.201 --customer-db-port 50051 \
    --product-db-host  35.222.178.52  --product-db-port  50052 \
    </dev/null >> ~/seller_server.log 2>&1 & disown

# On buyer-server VM (financial service FIRST, then buyer server):
nohup ~/Marketplace/venv/bin/python ~/Marketplace/financial_service.py \
    --host 0.0.0.0 --port 8000 </dev/null >> ~/financial.log 2>&1 & disown

nohup ~/Marketplace/venv/bin/python ~/Marketplace/buyer_server.py \
    --host 0.0.0.0 --port 5004 \
    --customer-db-host 34.67.115.201 --customer-db-port 50051 \
    --product-db-host  35.222.178.52  --product-db-port  50052 \
    --financial-host localhost --financial-port 8000 \
    </dev/null >> ~/buyer_server.log 2>&1 & disown
```

**IMPORTANT**: Always start financial_service.py BEFORE buyer_server.py — zeep fetches the WSDL at startup time.

---

## Local Development / Testing

```bash
cd Marketplace
pip install -r requirements.txt

# Compile gRPC stubs (if proto files change):
python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. \
    proto/customer_db.proto proto/product_db.proto

# Start all services locally (5 terminals, in this order):
python financial_service.py
python customer_database.py
python product_database.py
python seller_server.py
python buyer_server.py --financial-host localhost

# Run clients:
python seller_client.py   # connects to localhost:5003
python buyer_client.py    # connects to localhost:5004
```

---

## Performance Results

### PA2 (GCP Cloud)
| Scenario | Avg Response Time | Avg Throughput | Notes |
|---|---|---|---|
| 1 seller + 1 buyer | 104.82 ms (±2.27) | 17.1 ops/s (±0.5) | 10 real runs |
| 10 sellers + 10 buyers | 547.66 ms | 31.4 ops/s | 1 real run |
| 100 sellers + 100 buyers | ~2183 ms | ~78.5 ops/s | Extrapolated |

### PA1 (Localhost, for comparison)
| Scenario | Avg Response Time | Avg Throughput |
|---|---|---|
| 1 seller + 1 buyer | 2.03 ms (±0.26) | 964 ops/s (±167) |
| 10 sellers + 10 buyers | 35.52 ms (±15.95) | 636 ops/s (±273) |
| 100 sellers + 100 buyers | 130.37 ms (±70.61) | 1428 ops/s (±319) |

PA2 is ~50× slower due to internet RTT to GCP (30–80ms per hop).

---

## Key Implementation Notes

1. **Item IDs** are composite: `[category, item_id]` — both integers
2. **Search** uses OR logic — any keyword match returns the item (case-insensitive)
3. **RemoveItemFromCart** is purely client-side (no server endpoint) — removing from pending_cart locally
4. **Passwords** stored in plaintext (security out of scope per assignment)
5. **Session timeout** = 5 minutes of inactivity (checked server-side)
6. **SQLite databases** persist on each VM at `~/Marketplace/*.db`
7. **gRPC stubs** (pb2 files) are pre-compiled and included in the repo — no need to recompile unless .proto changes

---

## Dependencies (requirements.txt)
```
grpcio>=1.60.0
grpcio-tools>=1.60.0
flask>=3.0.0
requests>=2.31.0
spyne>=2.14.0
zeep>=4.2.1
lxml>=5.1.0
```

---

## Known Issues / Lessons Learned

- **No timeout on requests**: Original benchmark had no timeout, causing threads to hang for 75+ seconds on dropped packets. Fixed by adding `timeout=15` to all requests calls.
- **pkill python kills SSH tunnel**: gcloud SSH helper is Python-based. Use specific process names instead of `pkill -9 -f python`.
- **buyer_server crash on startup**: zeep fetches WSDL at import time. financial_service must be running BEFORE buyer_server starts.
- **Multiple duplicate processes**: If a service fails to start and you retry, old processes may still be running. Use `fuser -k <port>/tcp` to clear the port first.
- **GCP e2-micro VMs**: Burstable shared-core, 1GB RAM. Will CPU-throttle under sustained load (Scenario 3). SQLite write lock becomes the bottleneck at high concurrency.
