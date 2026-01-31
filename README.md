# Distributed Marketplace System - Programming Assignment 1
CSCI/ECEN 5673: Distributed Systems, Spring 2026

## System Overview

A distributed e-commerce marketplace system implementing a client-server architecture with stateless frontend servers and persistent backend databases. The system allows sellers to list items for sale and buyers to browse, search, and purchase items through a command-line interface.

## Architecture

### Components (6 total)

**Backend (Databases):**
- **Customer Database** (Port 5001): Manages user accounts, authentication, and session state
- **Product Database** (Port 5002): Manages items, shopping carts, and feedback ratings

**Frontend (Servers):**
- **Seller Server** (Port 5003): Stateless server handling seller operations
- **Buyer Server** (Port 5004): Stateless server handling buyer operations

**Clients:**
- **Seller Client**: CLI application for sellers to manage their accounts and items
- **Buyer Client**: CLI application for buyers to browse and purchase items

### Key Design Decisions

1. **Stateless Frontend Architecture**
   - All persistent state (sessions, carts, user data) stored in backend databases
   - Frontend servers can be restarted without losing session state
   - Enables horizontal scaling of frontend servers

2. **TCP Socket Communication**
   - All inter-component communication uses raw TCP sockets
   - JSON-based message protocol for simplicity and extensibility
   - Connection-per-request model for database communication

3. **Session Management**
   - UUID-based session tokens generated at login
   - Sessions stored in Customer Database with timestamp tracking
   - Automatic 5-minute timeout for inactive sessions
   - Sessions independent of TCP connections (can reconnect with same session)

4. **Search Algorithm**
   - Case-insensitive keyword matching
   - Returns items where ANY provided keyword matches ANY item keyword
   - Filters out items with zero quantity
   - Optional category filtering

5. **Shopping Cart Persistence**
   - Carts stored in Product Database, not in frontend memory
   - Automatically persists across sessions and client reconnections
   - Tied to buyer_id, not session_id

## System Requirements

- Python 3.7+
- Standard library only (no external dependencies)
  - `socket` - TCP communication
  - `json` - Message serialization
  - `threading` - Concurrent client handling
  - `time`, `uuid` - Session management

## Running the System

### 1. Start Backend Databases

In separate terminals:
```bash
# Terminal 1 - Customer Database
python customer_database.py
# Listening on localhost:5001

# Terminal 2 - Product Database
python product_database.py
# Listening on localhost:5002
```

### 2. Start Frontend Servers

In separate terminals:
```bash
# Terminal 3 - Seller Server
python seller_server.py
# Listening on localhost:5003

# Terminal 4 - Buyer Server
python buyer_server.py
# Listening on localhost:5004
```

### 3. Start Clients
```bash
# Seller Interface
python seller_client.py

# Buyer Interface (in another terminal)
python buyer_client.py
```

## Implemented APIs

### Seller APIs
✅ `CreateAccount` - Register new seller account  
✅ `Login` - Authenticate and create session  
✅ `Logout` - End session  
✅ `GetSellerRating` - View feedback (thumbs up/down)  
✅ `RegisterItemForSale` - List new item with attributes  
✅ `ChangeItemPrice` - Update item price  
✅ `UpdateUnitsForSale` - Update item quantity  
✅ `DisplayItemsForSale` - View all seller's items  

### Buyer APIs
✅ `CreateAccount` - Register new buyer account  
✅ `Login` - Authenticate and create session  
✅ `Logout` - End session  
✅ `SearchItemsForSale` - Search by category and/or keywords  
✅ `GetItem` - Get detailed item information  
✅ `AddItemToCart` - Add items to shopping cart  
✅ `RemoveItemFromCart` - Remove items from cart  
✅ `SaveCart` - Explicitly save cart (auto-saved by default)  
✅ `ClearCart` - Empty shopping cart  
✅ `DisplayCart` - View cart contents  
✅ `ProvideFeedback` - Rate item (thumbs up/down)  
✅ `GetSellerRating` - View seller's feedback  
✅ `GetBuyerPurchases` - View purchase history  

❌ `MakePurchase` - Not required for this assignment

## Data Models

### User Account
```python
{
    'user_id': int,           # Unique ID assigned by server
    'username': str,          # Max 32 chars
    'password': str,          # Stored in plaintext (security in PA2)
    'name': str,              # Max 32 chars
    'user_type': 'buyer'|'seller'
}
```

### Session
```python
{
    'session_id': str,        # UUID
    'user_id': int,
    'user_type': 'buyer'|'seller',
    'last_activity': float    # Unix timestamp
}
```

### Item
```python
{
    'item_id': [category, id], # Unique tuple
    'seller_id': int,
    'name': str,               # Max 32 chars
    'category': int,
    'keywords': [str],         # Up to 5, max 8 chars each
    'condition': 'New'|'Used',
    'price': float,
    'quantity': int
}
```

### Shopping Cart
```python
[
    {
        'item_id': [category, id],
        'quantity': int
    },
    ...
]
```

## Message Protocol

All TCP messages use JSON format:

**Request:**
```json
{
    "api": "APIName",
    "session_id": "uuid-string-or-null",
    "payload": { /* API-specific data */ }
}
```

**Response:**
```json
{
    "status": "success"|"error",
    "data": { /* Response data */ },
    "message": "Error description (if error)"
}
```

## Configuration

### Changing Ports/Hosts

All components support command-line arguments for configuration:

**Databases:**
```bash
python customer_database.py --host 0.0.0.0 --port 5001
python product_database.py --host 0.0.0.0 --port 5002
```

**Servers:**
```bash
python seller_server.py --host 0.0.0.0 --port 5003 \
    --customer-db-host 192.168.1.10 --customer-db-port 5001 \
    --product-db-host 192.168.1.11 --product-db-port 5002

python buyer_server.py --host 0.0.0.0 --port 5004 \
    --customer-db-host 192.168.1.10 --customer-db-port 5001 \
    --product-db-host 192.168.1.11 --product-db-port 5002
```

**Clients:**
```bash
python seller_client.py --host 192.168.1.12 --port 5003
python buyer_client.py --host 192.168.1.13 --port 5004
```

### Distributed Deployment

To run on separate machines:
1. Use command-line arguments to specify hosts/ports (no code changes needed)
2. Ensure network connectivity between machines
3. Update firewall rules to allow TCP connections on required ports
4. All communication occurs over TCP sockets

## Testing

### Manual Testing
Use the CLI clients to interact with the system.

### Automated Testing
```bash
# Test databases
python test_db.py
python test_product_db.py

# Test servers
python test_seller_server.py
python test_buyer_server.py
```

### Performance Evaluation
```bash
# Run 10 iterations of all 3 scenarios
cd Evaluation
python performance_evaluation.py
```

## Current System Status

### ✅ What Works
- All 6 components fully functional
- All required APIs implemented and tested
- Session management with automatic timeout
- Stateless frontend servers
- Concurrent client support (100+ simultaneous clients)
- Shopping cart persistence across sessions
- Item and seller feedback system
- Search functionality with category and keyword filtering
- Error handling for invalid operations

### ❌ What Doesn't Work
- `MakePurchase` API (not required for PA1)
- Security/encryption (addressed in future assignment)
- Connection pooling (would improve performance)
- Database persistence to disk (currently in-memory)

### ⚠️ Known Limitations
- Connection-per-request model creates overhead at high concurrency
- No database replication or fault tolerance
- Passwords stored in plaintext
- No input validation for string lengths (assumes clients follow limits)
- High variability in performance at 100+ concurrent clients

## Assumptions

1. **Network**: All components can communicate via TCP/IP
2. **Reliability**: TCP provides reliable, ordered delivery
3. **Security**: Authentication is simple (no encryption) for PA1
4. **Concurrency**: Thread-per-connection model is sufficient for evaluation
5. **Data Persistence**: In-memory storage acceptable for PA1
6. **Item IDs**: Tuple format [category, counter] is sufficient for uniqueness
7. **Search**: Simple keyword matching is acceptable (no ranking algorithm)
8. **Timeouts**: 5-minute session timeout is reasonable for user activity

## Future Enhancements (PA2/PA3)

- Implement `MakePurchase` with transaction support
- Add encryption for passwords and sensitive data
- Implement connection pooling for database communication
- Add database replication using Raft consensus
- Use gRPC for more efficient communication
- Add persistent storage (write to disk)
- Implement proper authentication tokens
- Add load balancing for frontend servers

## File Structure
```
ECommerce - PA1/
├── Marketplace/
│   ├── customer_database.py      # Customer DB server
│   ├── product_database.py       # Product DB server
│   ├── seller_server.py          # Seller frontend server
│   ├── buyer_server.py           # Buyer frontend server
│   ├── seller_client.py          # Seller CLI client
│   └── buyer_client.py           # Buyer CLI client
├── Evaluation/
│   └── performance_evaluation.py # Performance evaluation script
├── Test files/
│   ├── test_db.py               # Customer DB tests
│   ├── test_product_db.py       # Product DB tests
│   ├── test_seller_server.py    # Seller server tests
│   └── test_buyer_server.py     # Buyer server tests
├── README.md                     # This file
├── PERFORMANCE_REPORT.md         # Performance evaluation results
└── COMMANDS.txt                  # Command reference for demo
```

## Authors

Swarup Panda  
CU Boulder, Spring 2026

## License

Academic project for CSCI/ECEN 5673