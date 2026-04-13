# PA3 Demo Script — Grading Interview

---

## Part 0: Architecture & Design Decisions

### Overall Architecture

```
                         ┌──────────────────────────────────┐
    Seller Clients ──REST──▶  Seller Servers (4 replicas)   │
                         │       stateless Flask             │
                         │       StubPool → gRPC failover   │──gRPC──▶ Customer DB (5 replicas)
                         └──────────────────────────────────┘          Atomic Broadcast + SQLite
                                                                       UDP between replicas
                         ┌──────────────────────────────────┐
    Buyer Clients  ──REST──▶  Buyer Servers  (4 replicas)   │
                         │       stateless Flask             │──gRPC──▶ Product DB  (5 replicas)
                         │       StubPool → gRPC failover   │          Raft (PySyncObj) + in-memory
                         │                                   │
                         │                 SOAP ─────────────┼────────▶ Financial Service (1 instance)
                         └──────────────────────────────────┘
```

- **19 total processes** spread across **4 GCP VMs**
- 3-tier design: Clients → Stateless Frontends → Replicated Backends
- Communication: Client↔Frontend = REST, Frontend↔Backend = gRPC, Payment = SOAP
- Each replicated component is spread across multiple VMs so no single VM failure kills a majority

### "Why did you choose this atomic broadcast design?"

The assignment required a **rotating sequencer** — so the core design was given. But the key design decisions I made were:

1. **Why rotating sequencer instead of a fixed sequencer?**
   - A fixed sequencer is a single point of failure and a bottleneck
   - Rotating means node `k mod n` sequences message `k`, so the load is distributed evenly across all 5 nodes
   - If one node is slow, it only delays the sequence numbers it's responsible for, not all of them

2. **Why add ACK messages (not in the spec's 3 types)?**
   - The spec's delivery condition says "a majority of group members have received all Request and Sequence messages"
   - I need a way to *know* what other nodes have received — ACKs are the mechanism for that
   - A node only ACKs when it has **both** the REQUEST and the SEQUENCE for a given slot, so a majority of ACKs guarantees a majority has the full information
   - Without ACKs, there's no way to verify delivery condition 2

3. **Why UDP with redundant sends?**
   - UDP is required by the spec (unreliable communication)
   - Since UDP can drop packets, I send each broadcast **2 times** (REDUNDANT_SENDS = 2) with a small delay between them — cheap insurance against packet loss
   - If that still fails, the **gap detection loop** (every 50ms) catches any missing messages and sends targeted RETRANSMIT requests

4. **Why pre-compute IDs and timestamps before broadcast?**
   - All 5 replicas must apply the same write in the same way
   - If each replica generated its own user_id or session_id, they'd diverge
   - So the originating node computes user_id, session_id, and timestamp *before* broadcasting, and includes them in the payload — all replicas use the same values

5. **Why SQLite for customer DB but in-memory for product DB?**
   - Customer DB uses my custom atomic broadcast — no built-in crash recovery, so SQLite gives persistence on disk
   - Product DB uses PySyncObj Raft — it has built-in snapshotting and log replay for crash recovery, so in-memory state is safe (Raft restores it after a crash)

### "Walk me through what happens when a user creates an account"

```
1. Buyer client sends POST /buyer/account to a buyer server (REST)
2. Buyer server calls StoreUser on customer DB via gRPC (StubPool picks a replica)
3. That customer DB replica:
   a. Pre-computes the next user_id (reads MAX from local SQLite)
   b. Packages the write as a payload: {op: "StoreUser", user_id: 5, username: "alice", ...}
   c. Calls broadcast_request(payload) on its AtomicBroadcastNode
4. AtomicBroadcastNode broadcasts a REQUEST message (UDP) to all 5 members
5. The rotating sequencer (node k mod 5) picks this request, assigns it global_seq k,
   broadcasts a SEQUENCE message
6. Each node ACKs when it has both the REQUEST and SEQUENCE
7. Once a majority (3/5) have ACKed for all slots up to k, the message is delivered
8. on_deliver callback runs on EVERY replica — inserts the row into local SQLite
9. The originating node's broadcast_request() returns the result
10. gRPC response goes back to buyer server → REST response to client
```

### "What's the architecture for handling failures?"

| Component | Failure Model | Recovery Mechanism |
|---|---|---|
| Customer DB (5 replicas) | Servers don't fail, communication unreliable | UDP retransmit on gap detection (every 50ms) |
| Product DB (5 replicas) | Servers CAN crash, communication unreliable | Raft leader election (0.4-1.4s), log replay on restart |
| Seller/Buyer servers (4 each) | Can crash | Stateless — just restart. Client fails over to another replica |
| Clients | N/A | Configured with all server addresses, tries next on connection error |

The system tolerates:
- **Any 2 out of 5** product DB crashes (Raft needs majority = 3)
- **Any 3 out of 4** frontend crashes (just need 1 alive)
- **Any UDP packet loss** on customer DB (retransmit recovers it)

---

## Part 0.5: How the Two Algorithms Actually Work (Plain English)

### The core problem both algorithms solve

In PA2 we had one database. If it dies, the system is dead. PA3 runs 5 copies
of each database. But now the hard question is: how do you keep all 5 copies
in sync? If a seller registers an item on replica 1, replicas 2-5 need that
same item. And if two sellers register items at the same time on different
replicas, all 5 must apply those writes in the EXACT same order — otherwise
the databases diverge and you get inconsistent data.

Both protocols solve this: **total order replication** — every replica sees
every write in the same order.

---

### Atomic Broadcast — How it works (Customer DB)

Think of it like a group chat with 5 people where everyone needs to agree on
the order of messages.

**Step by step — what happens when "Create Account" is called:**

1. The write arrives at one of the 5 customer DB replicas (say node 2)
2. Node 2 **broadcasts a REQUEST** to all 5 nodes over UDP
   - Contains: "Create user alice, user_id=5, password=..."
   - The user_id is pre-computed BEFORE broadcast so all replicas use the same value
3. Now someone needs to assign this request a position in the global order.
   That someone is the **rotating sequencer**:
   - Global position 0 → assigned by node 0
   - Global position 1 → assigned by node 1
   - Global position 2 → assigned by node 2
   - ...wraps around: position 5 → back to node 0
   - So the job rotates. No single node is the bottleneck.
4. The sequencer for the next position picks this request and broadcasts a
   **SEQUENCE message**: "Global position 7 = the request from node 2"
5. Each node, when it has BOTH the REQUEST and the SEQUENCE for a slot,
   broadcasts an **ACK**: "I have everything for position 7"
6. Once **3 out of 5** nodes have ACKed for all positions up to 7,
   the write is **delivered** — every replica inserts the row into SQLite

**Why majority ACK?**
- If only 1 node applied a write, that data could be lost if that node lags
- By waiting for 3/5 to confirm, we guarantee the write survives even if
  2 nodes are temporarily behind

**What about dropped UDP packets?**
- Every 50ms, each node scans for gaps: "I have positions 0,1,2,4 but not 3"
- It sends a **RETRANSMIT** request to whoever should have the missing message
- This is "negative acknowledgment" — only ask when something is missing

**Why pre-compute IDs before broadcast?**
- If each replica computed its own user_id, they might pick different numbers
  (because other writes could interleave differently on each replica)
- So the originating node computes user_id=5 BEFORE broadcasting, puts it
  in the payload, and all 5 replicas use that same value → deterministic

**The delivery rules (from the assignment spec):**
A replica can apply write at global position `s` only when:
1. It has already applied positions 0, 1, 2, ..., s-1 (strict order)
2. A majority (3/5) have ACKed everything up to and including s (durability)

---

### Raft — How it works (Product DB)

Raft uses a completely different approach: instead of rotating who's in charge,
it **elects a single leader** and all writes go through that leader.

**Step by step — what happens when "Register Item" is called:**

1. The write arrives at one of the 5 product DB replicas via gRPC
2. If that replica is NOT the leader, it **forwards** the write to the leader
   (this is what `commandsWaitLeader=True` does)
3. The leader **appends** the write to its log
4. The leader **sends** the log entry to all 4 followers
5. Once **3 out of 5** nodes (including leader) have the entry, the leader
   **commits** it — applies it to in-memory state
6. Followers apply it too once they hear about the commit
7. Response goes back to the client

**What if the leader crashes?**
- The remaining 4 nodes notice the leader stopped sending heartbeats
- After a timeout (0.4–1.4 seconds), they hold an **election**
- One node gets majority votes and becomes the new leader
- Writes resume through the new leader — no data is lost because committed
  entries were already on a majority of nodes

**Reads are local:**
- Any replica can answer a read (search items, get item, etc.)
- No consensus needed for reads — just return what's in local memory
- This is safe because all replicas eventually have the same data

---

### How they compare

```
                    Atomic Broadcast              Raft
                    (Customer DB)                 (Product DB)
Who orders writes?  Rotating — node k mod 5       Single elected leader
Transport           UDP (unreliable, fast)         TCP (reliable, slower)
Crash recovery      None (spec says no crashes)    Built-in (log replay)
Write speed         ~150ms                         ~320ms
Why slower?         —                              All writes funnel through
                                                   one leader + TCP overhead
Storage             SQLite on disk                 In-memory (Raft snapshots)
Implementation      Custom (atomic_broadcast.py)   PySyncObj library
```

**Why is atomic broadcast faster?**
- UDP has no connection overhead (fire-and-forget, handle loss with retransmit)
- The sequencer role rotates, so no single node is the bottleneck
- Raft funnels ALL writes through one leader, which serializes them

**Why use Raft at all then?**
- It handles crashes. If a product DB node dies and restarts, Raft replays
  its log and brings it back to current state. Atomic broadcast can't do this.
- The assignment required Raft for product DB and atomic broadcast for customer DB.

---

### The one-sentence version

**Atomic broadcast** = "everyone shout your writes, take turns numbering them,
wait for majority to confirm before applying" (no leader, UDP, no crash recovery)

**Raft** = "elect a leader, leader decides the order, leader pushes to followers,
handles crashes" (single leader, TCP, crash recovery built-in)

Both achieve the same end result: all 5 replicas apply writes in identical order.

---

### How they fit into the full system

```
Buyer clicks "Create Account"
  → buyer_client sends REST to buyer_server
    → buyer_server sends gRPC to customer_database_replicated (via StubPool)
      → that replica broadcasts via ATOMIC BROADCAST (UDP)
        → all 5 customer DB replicas apply the write in the same order
      → gRPC response back
    → REST response back

Seller clicks "Register Item"
  → seller_client sends REST to seller_server
    → seller_server sends gRPC to product_database_replicated (via StubPool)
      → that replica forwards to RAFT LEADER
        → leader replicates to majority, commits
        → all 5 product DB replicas apply the write
      → gRPC response back
    → REST response back

Anyone does a READ (search, get item, get user, etc.)
  → goes to whichever replica the StubPool connects to
  → reads local state directly, no consensus needed
  → fast (~128ms, just network RTT)
```

---

## Part 1: Explaining the Protocols

### "How did you implement Raft?" (Product DB)

- Used **PySyncObj**, an open-source Python Raft library
- All product data lives **in-memory** inside `RaftProductDB` (extends `SyncObj`)
- Write methods have `@replicated` decorator — PySyncObj automatically handles:
  - Route write to leader
  - Leader appends to log, replicates to majority (3/5), commits
- Read methods are plain Python — read local state directly, no consensus
- `commandsWaitLeader=True` so writes on any follower auto-forward to the leader
- 5 replicas across 4 VMs, Raft timeout 0.4-1.4s for leader election
- **Key file**: `Marketplace/product_database_replicated.py`
  - Lines 43-138: `RaftProductDB` class with `@replicated` write methods
  - Lines 196-368: gRPC servicer wrapping the Raft node
  - Lines 376-384: Raft config (`commandsWaitLeader`, timeouts)

### "How did you implement the Rotating Sequencer Atomic Broadcast?" (Customer DB)

- Custom protocol over **UDP** (unreliable transport, as required)
- 4 message types: REQUEST, SEQUENCE, ACK, RETRANSMIT
- Flow:
  1. A write comes in -> node broadcasts **REQUEST** to all 5 members
  2. The **sequencer** for global sequence number `k` is node `k mod n` (rotating)
  3. Sequencer picks an unsequenced request, assigns it `global_seq = k`, broadcasts **SEQUENCE**
  4. Each node sends **ACK** when it has both the REQUEST and SEQUENCE for that slot
  5. A message is **delivered** only when:
     - All prior messages (global_seq < k) have been delivered
     - A **majority** (3/5) of nodes have ACKed for all slots up to k
- **Gap detection** runs every 50ms — sends RETRANSMIT for missing messages
- Pre-computes user_id, session_id, timestamps before broadcast for determinism
- **Key file**: `Marketplace/atomic_broadcast.py`
  - Lines 41-55: `AtomicBroadcastNode` class
  - Lines 284-376: Sequencer logic (3 preconditions from the spec)
  - Lines 456-520: Delivery logic (2 delivery conditions)
  - Lines 526-610: Gap detection + retransmit

---

## Part 2: Demo Commands

> Replace `<VM*_EXT>` with actual external IPs.
> Replace `<SID>` with session_id from login responses.
> All commands run from your local machine.

### Step 1: Show DB is empty (SSH into VM1)

```bash
gcloud compute ssh customer-db --zone=us-central1-a --project=ecommerce-pa2-2026

# On VM1:
sqlite3 ~/customer_data_node0.db "SELECT * FROM users;"
sqlite3 ~/customer_data_node0.db "SELECT * FROM sessions;"
# Should be empty (or show prior data)
exit
```

### Step 2: Create seller account + login

```bash
# Create account
curl -s -X POST http://<VM1_EXT>:5003/seller/account \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_seller","password":"pass","name":"Demo Seller"}' | python3 -m json.tool

# Login — SAVE the session_id from response
curl -s -X POST http://<VM1_EXT>:5003/seller/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_seller","password":"pass"}' | python3 -m json.tool
```

### Step 3: Register an item for sale

```bash
curl -s -X POST http://<VM1_EXT>:5003/seller/items \
  -H "Content-Type: application/json" \
  -H "X-Session-ID: <SELLER_SID>" \
  -d '{"name":"Laptop","category":0,"keywords":["laptop","computer"],"condition":"new","price":999.99,"quantity":10}' | python3 -m json.tool
```

### Step 4: Create buyer account + login

```bash
# Create account
curl -s -X POST http://<VM2_EXT>:5004/buyer/account \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_buyer","password":"pass","name":"Demo Buyer"}' | python3 -m json.tool

# Login — SAVE the session_id from response
curl -s -X POST http://<VM2_EXT>:5004/buyer/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_buyer","password":"pass"}' | python3 -m json.tool
```

### Step 5: Search for the item

```bash
curl -s "http://<VM2_EXT>:5004/buyer/items?keywords=laptop" \
  -H "X-Session-ID: <BUYER_SID>" | python3 -m json.tool
```

### Step 6: Make a purchase

```bash
curl -s -X POST http://<VM2_EXT>:5004/buyer/purchase \
  -H "Content-Type: application/json" \
  -H "X-Session-ID: <BUYER_SID>" \
  -d '{"item_id":[0,1],"quantity":1,"name":"Demo Buyer","card_number":"4111111111111111","expiration_date":"12/28","security_code":"123"}' | python3 -m json.tool
```

> If payment is declined (10% chance), just run it again.

### Step 7: Verify purchase went through

```bash
# Buyer sees purchase history
curl -s http://<VM2_EXT>:5004/buyer/purchases \
  -H "X-Session-ID: <BUYER_SID>" | python3 -m json.tool

# Seller sees quantity decreased (was 10, now 9)
curl -s http://<VM1_EXT>:5003/seller/items \
  -H "X-Session-ID: <SELLER_SID>" | python3 -m json.tool
```

---

## Part 3: Show Database Replication

### Customer DB — same rows on all nodes (Atomic Broadcast)

```bash
echo "=== Node 0 (VM1) ==="
gcloud compute ssh customer-db --zone=us-central1-a --project=ecommerce-pa2-2026 \
  --command='sqlite3 ~/customer_data_node0.db "SELECT user_id, username, name, user_type FROM users;"'

echo "=== Node 2 (VM2) ==="
gcloud compute ssh product-db --zone=us-central1-a --project=ecommerce-pa2-2026 \
  --command='sqlite3 ~/customer_data_node2.db "SELECT user_id, username, name, user_type FROM users;"'

echo "=== Node 4 (VM3) ==="
gcloud compute ssh seller-server --zone=us-central1-a --project=ecommerce-pa2-2026 \
  --command='sqlite3 ~/customer_data_node4.db "SELECT user_id, username, name, user_type FROM users;"'
```

> All three should show identical rows — proves atomic broadcast works.

### Product DB — same data from different replicas (Raft)

```bash
# Search via buyer server on VM2 (routes to product DB replicas on VM2 first)
curl -s "http://<VM2_EXT>:5004/buyer/items?keywords=laptop" \
  -H "X-Session-ID: <BUYER_SID>" | python3 -m json.tool

# Search via buyer server on VM4 (routes to product DB replica on VM4 first)
curl -s "http://<VM4_EXT>:5004/buyer/items?keywords=laptop" \
  -H "X-Session-ID: <BUYER_SID>" | python3 -m json.tool
```

> Both return the same item with same quantity — proves Raft replication works.

---

## Cheat Sheet: If They Ask Follow-Up Questions

| Question | Answer |
|---|---|
| Why UDP for atomic broadcast? | Assignment requires it. Also faster than TCP — no connection overhead. |
| Why Raft for product DB? | Assignment requires using an existing Raft implementation. We used PySyncObj. |
| How does failover work? | StubPool tries each DB replica in round-robin. Clients try each server in a list. |
| What if the Raft leader dies? | New leader elected in 0.4-1.4s. Writes stall briefly, then resume. No data loss. |
| What if a customer DB node dies? | Not expected (spec says servers don't fail, only communication is unreliable). Retransmit handles lost UDP packets. |
| How are writes deterministic across replicas? | user_id, session_id, timestamps are pre-computed BEFORE broadcast so all replicas use the same values. |
| How many nodes can fail? | Product DB: 2 out of 5 (Raft needs majority). Frontend: 3 out of 4 (just need one alive). |
| Where is the cart stored? | Client-side (in-memory in buyer_client.py). "Save Cart" persists to product DB via Raft. |
