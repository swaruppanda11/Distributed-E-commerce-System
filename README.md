# Distributed Marketplace System - PA1
CSCI/ECEN 5673: Distributed Systems, Spring 2026

## System Design

A distributed e-commerce marketplace with 6 components: Customer Database, Product Database, Seller Server, Buyer Server, Seller Client, and Buyer Client. Frontend servers are stateless - all persistent data (sessions, carts, users) stored in backend databases. Components communicate via TCP sockets using JSON messages. Sessions use UUID tokens with 5-minute timeout. Search matches items where any provided keyword matches any item keyword (case-insensitive).

## Assumptions

1. All components communicate via TCP/IP over the network
2. In-memory storage is acceptable (no disk persistence required)
3. Simple plaintext authentication (security addressed in future assignments)
4. Thread-per-connection model sufficient for evaluation workloads

## Current Status

**Works:** All 6 components, all required APIs (except MakePurchase which is not required), session timeout, stateless frontend, concurrent client support up to 200 clients.

**Not Implemented:** MakePurchase (not required for PA1).

## Running the System

```bash
# Start servers (in separate terminals, from Marketplace folder)
python customer_database.py    # Port 5001
python product_database.py     # Port 5002
python seller_server.py        # Port 5003
python buyer_server.py         # Port 5004

# Start clients
python seller_client.py
python buyer_client.py

# Run evaluation (from Evaluation folder)
python performance_evaluation.py
```

## Author

Swarup Panda, CU Boulder
