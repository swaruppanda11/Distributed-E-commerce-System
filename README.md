# Distributed Marketplace System - PA2
CSCI/ECEN 5673: Distributed Systems, Spring 2026

## System Design

A distributed e-commerce marketplace with 7 components deployed across 4 GCP VMs. The Seller and Buyer frontend servers are stateless REST (Flask) servers — all persistent state (users, sessions, carts, purchases) lives in SQLite-backed backend databases. Client-server communication uses REST (HTTP/JSON via the `requests` library). Frontend-to-database communication uses gRPC (Protocol Buffers). Financial transactions are handled by a SOAP service (spyne/zeep) with 90% approval probability. Sessions use UUID tokens with a 5-minute inactivity timeout. The cart is client-side (in memory) until the buyer explicitly saves it.

## Assumptions

1. Each of the four server components (Seller Server, Buyer Server, Customer DB, Product DB) runs on a separate GCP VM (e2-micro, us-central1-a).
2. The Financial Transactions service runs on the same VM as the Buyer Server (localhost:8000), as permitted by the assignment spec.
3. Clients run locally and connect to the cloud servers over the public internet.
4. Passwords are stored in plaintext (security is out of scope for this assignment).
5. Item IDs are composite keys: [category, item_id] — both integers.
6. Search returns items where any provided keyword matches any item keyword (case-insensitive OR logic).
7. SQLite with threading locks is used for thread-safe database access.

## Current Status

**Works:**
- All seller APIs: CreateAccount, Login, Logout, GetSellerRating, RegisterItemForSale, ChangeItemPrice, UpdateUnitsForSale, DisplayItemsForSale
- All buyer APIs: CreateAccount, Login, Logout, SearchItems, GetItem, AddItemToCart, RemoveItemFromCart, SaveCart, ClearCart, DisplayCart, ProvideFeedback, GetSellerRating, MakePurchase, GetBuyerPurchases
- REST client-server communication (Flask + requests)
- gRPC frontend-to-database communication (compiled proto stubs)
- SOAP financial transaction service (spyne server, zeep client)
- SQLite persistent storage on all database components
- Stateless frontend servers
- Cloud deployment on GCP (4 separate VMs)
- Session timeout (5 minutes inactivity)
- Client-side cart with manual Save Cart

**Not Implemented:** None — all PA2 requirements are complete.

## Cloud Deployment (GCP)

| Component | VM | External IP | Port | Protocol |
|---|---|---|---|---|
| Customer Database | customer-db | 34.67.115.201 | 50051 | gRPC |
| Product Database | product-db | 35.222.178.52 | 50052 | gRPC |
| Seller Server | seller-server | 136.116.235.76 | 5003 | REST |
| Buyer Server | buyer-server | 34.172.181.121 | 5004 | REST |
| Financial Service | buyer-server | localhost | 8000 | SOAP |

## Running the System

### Install dependencies (first time only)
```bash
cd Marketplace
pip install -r requirements.txt

# Compile gRPC stubs
python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. proto/customer_db.proto proto/product_db.proto
```

### Local deployment (all on one machine)
```bash
python financial_service.py          # Port 8000
python customer_database.py          # Port 50051
python product_database.py           # Port 50052
python seller_server.py              # Port 5003
python buyer_server.py               # Port 5004
```

### Cloud deployment (GCP - already running)
```bash
# Clients connect directly to cloud VMs
python seller_client.py --host 136.116.235.76 --port 5003
python buyer_client.py  --host 34.172.181.121 --port 5004
```

### Run performance benchmark
```bash
python benchmark.py --scenarios 1 2 3 --runs 10 --calls 1000
```
