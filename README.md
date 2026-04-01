# Distributed Marketplace System - PA3 (Replication)
CSCI/ECEN 5673: Distributed Systems, Spring 2026

## System Design

A replicated e-commerce marketplace with 19 processes across 4 GCP VMs. The Customer Database (5 replicas) uses a custom Rotating Sequencer Atomic Broadcast protocol over UDP for total-order replication — writes are broadcast and sequenced with majority-ACK delivery, reads go to local SQLite. The Product Database (5 replicas) uses Raft consensus via PySyncObj with in-memory state — write methods go through Raft log replication, reads are served locally. Seller Servers (4 replicas) and Buyer Servers (4 replicas) are stateless REST frontends that use gRPC stub pools with automatic failover across all DB replicas. Clients are configured with multiple server addresses and fail over transparently on connection errors. The Financial Service (1 instance) handles SOAP-based payment processing.

## Assumptions

1. Four GCP e2-micro VMs (us-central1-a); 19 processes distributed so that a majority of each replicated group survives any single VM failure.
2. The Rotating Sequencer Atomic Broadcast assigns sequencer for global sequence k to node (k mod n). A message is delivered when a majority of nodes ACK it and the node has both the Request and Sequence messages.
3. Raft product DB uses `commandsWaitLeader=True` so writes on followers are auto-forwarded to the Raft leader.
4. For deterministic replication of the customer DB, user IDs, session IDs, and timestamps are pre-computed before broadcast.
5. Passwords are stored in plaintext (security out of scope). Session timeout is 5 minutes.
6. Item IDs are composite keys: [category, item_id].

## Current Status

**Works:** All PA2 functionality plus: 5-way Customer DB replication (atomic broadcast), 5-way Product DB replication (Raft), 4 seller server replicas with failover, 4 buyer server replicas with failover, client-side failover, per-function latency benchmarking across 4 failure scenarios x 3 concurrency levels.

**Not Implemented:** None — all PA3 requirements are complete.

## Replica Layout (4 VMs, 19 processes)

| VM | Processes |
|---|---|
| VM1 (customer-db) | CustDB 0,1 + ProdDB 0 + Seller 0 + Financial |
| VM2 (product-db) | CustDB 2,3 + ProdDB 1,2 + Seller 1 + Buyer 0 |
| VM3 (seller-server) | CustDB 4 + ProdDB 3 + Seller 2,3 + Buyer 1 |
| VM4 (buyer-server) | ProdDB 4 + Buyer 2,3 |

## Running the System

See `COMMANDS.txt` for complete copy-paste deployment commands including per-VM process startup, firewall rules, client commands, benchmarking, and failure injection.

### Quick local test
```bash
cd Marketplace
pip install -r requirements.txt
python financial_service.py
python customer_database_replicated.py --node-id 0 --members "localhost:6000" --grpc-port 50051
python product_database_replicated.py --raft-addr "localhost:4321" --raft-partners "" --grpc-port 50052
python seller_server.py --port 5003 --customer-db-addrs "localhost:50051" --product-db-addrs "localhost:50052"
python buyer_server.py --port 5004 --customer-db-addrs "localhost:50051" --product-db-addrs "localhost:50052" --financial-host localhost --financial-port 8000
```

### Benchmark
```bash
python benchmark_pa3.py --seller-urls "http://VM1:5003,..." --buyer-urls "http://VM2:5004,..." --scenarios 1 2 3 --runs 3 --calls 50 --failures no_failure frontend_fail follower_fail leader_fail
```
