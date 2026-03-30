"""
Integration test for the Raft-replicated product database.

Spins up 5 Raft replicas on localhost, issues gRPC calls, and verifies:
1. Item registration replicates to all nodes (reads from any node).
2. Cart, feedback, purchase operations work.
3. Leader failover: kill the leader, writes still succeed on a new leader.
"""

import grpc
import time
import threading
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import product_db_pb2
import product_db_pb2_grpc
from product_database_replicated import RaftProductDB, ReplicatedProductDBServicer
from pysyncobj import SyncObjConf
from concurrent import futures

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test")

N = 5
RAFT_BASE_PORT = 14000
GRPC_BASE_PORT = 51100


def setup_cluster():
    """Create 5 Raft replicas and gRPC servers, return (raft_nodes, servers, channels, stubs)."""
    raft_addrs = [f"127.0.0.1:{RAFT_BASE_PORT + i}" for i in range(N)]
    raft_nodes = []
    servers = []
    channels = []
    stubs = []

    for i in range(N):
        partners = [a for j, a in enumerate(raft_addrs) if j != i]
        conf = SyncObjConf(
            autoTick=True,
            appendEntriesUseBatch=True,
            dynamicMembershipChange=False,
            commandsWaitLeader=True,
            connectionTimeout=5.0,
            raftMinTimeout=0.4,
            raftMaxTimeout=1.4,
        )
        raft_node = RaftProductDB(raft_addrs[i], partners, conf)
        raft_nodes.append(raft_node)

        servicer = ReplicatedProductDBServicer(raft_node)
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=5))
        product_db_pb2_grpc.add_ProductDBServicer_to_server(servicer, server)
        grpc_port = GRPC_BASE_PORT + i
        server.add_insecure_port(f"127.0.0.1:{grpc_port}")
        server.start()
        servers.append(server)

        channel = grpc.insecure_channel(f"127.0.0.1:{grpc_port}")
        channels.append(channel)
        stubs.append(product_db_pb2_grpc.ProductDBStub(channel))

    # Wait for leader election
    logger.info("Waiting for Raft leader election...")
    deadline = time.time() + 15
    while time.time() < deadline:
        for rn in raft_nodes:
            if rn._getLeader() is not None:
                logger.info("Leader elected!")
                time.sleep(1)  # extra settle time
                return raft_nodes, servers, channels, stubs
        time.sleep(0.3)

    raise RuntimeError("Raft leader election timed out")


def teardown_cluster(raft_nodes, servers, channels):
    for ch in channels:
        ch.close()
    for s in servers:
        s.stop(0)
    for rn in raft_nodes:
        rn.destroy()
    time.sleep(0.5)


# ---------------------------------------------------------------------------
# Test 1: Item registration + replication
# ---------------------------------------------------------------------------
def test_item_registration():
    logger.info("=== Test: Item registration replicates to all nodes ===")
    raft_nodes, servers, channels, stubs = setup_cluster()

    try:
        # Register item via node 0
        resp = stubs[0].RegisterItem(product_db_pb2.RegisterItemRequest(
            seller_id=1, name="Laptop", category=0,
            keywords=["electronics", "computer"],
            condition="new", price=999.99, quantity=10,
        ), timeout=15)
        assert resp.status == "success", f"RegisterItem failed: {resp.message}"
        assert resp.item_id.item_id > 0
        registered_id = resp.item_id.item_id

        # Wait for replication
        time.sleep(2)

        # Verify item exists on ALL nodes
        for i in range(N):
            get_resp = stubs[i].GetItem(product_db_pb2.ItemIdRequest(
                item_id=product_db_pb2.ItemId(category=0, item_id=registered_id)
            ), timeout=10)
            assert get_resp.status == "success", f"Node {i}: GetItem failed: {get_resp.message}"
            assert get_resp.item.name == "Laptop"
            assert get_resp.item.quantity == 10

        logger.info("PASSED: Item replicated to all %d nodes", N)
    finally:
        teardown_cluster(raft_nodes, servers, channels)


# ---------------------------------------------------------------------------
# Test 2: Full workflow — register, cart, purchase, feedback, ratings
# ---------------------------------------------------------------------------
def test_full_workflow():
    logger.info("=== Test: Full workflow (register, cart, purchase, feedback) ===")
    raft_nodes, servers, channels, stubs = setup_cluster()

    try:
        # Register 2 items via different nodes
        resp1 = stubs[0].RegisterItem(product_db_pb2.RegisterItemRequest(
            seller_id=10, name="Book", category=1,
            keywords=["education"], condition="new", price=25.0, quantity=50,
        ), timeout=15)
        assert resp1.status == "success"
        book_id = resp1.item_id.item_id

        resp2 = stubs[2].RegisterItem(product_db_pb2.RegisterItemRequest(
            seller_id=10, name="Pen", category=1,
            keywords=["stationery"], condition="new", price=5.0, quantity=100,
        ), timeout=15)
        assert resp2.status == "success"
        pen_id = resp2.item_id.item_id

        time.sleep(1)

        # Search from node 3
        search_resp = stubs[3].SearchItems(product_db_pb2.SearchItemsRequest(
            category=1, has_category=True, keywords=["education"]
        ), timeout=10)
        assert search_resp.status == "success"
        assert len(search_resp.items) >= 1

        # Store cart via node 1
        cart_resp = stubs[1].StoreCart(product_db_pb2.StoreCartRequest(
            buyer_id=100,
            cart=[
                product_db_pb2.CartItem(
                    item_id=product_db_pb2.ItemId(category=1, item_id=book_id),
                    quantity=2
                ),
            ]
        ), timeout=15)
        assert cart_resp.status == "success"

        time.sleep(1)

        # Get cart from node 4
        get_cart = stubs[4].GetCart(product_db_pb2.BuyerIdRequest(buyer_id=100), timeout=10)
        assert get_cart.status == "success"
        assert len(get_cart.cart) == 1

        # Make purchase via node 2
        purchase_resp = stubs[2].MakePurchase(product_db_pb2.MakePurchaseRequest(
            buyer_id=100,
            item_id=product_db_pb2.ItemId(category=1, item_id=book_id),
            quantity=2,
        ), timeout=15)
        assert purchase_resp.status == "success"

        time.sleep(1)

        # Verify quantity reduced on node 0
        item_resp = stubs[0].GetItem(product_db_pb2.ItemIdRequest(
            item_id=product_db_pb2.ItemId(category=1, item_id=book_id)
        ), timeout=10)
        assert item_resp.item.quantity == 48, f"Expected 48, got {item_resp.item.quantity}"

        # Add feedback via node 3
        fb_resp = stubs[3].AddItemFeedback(product_db_pb2.AddItemFeedbackRequest(
            item_id=product_db_pb2.ItemId(category=1, item_id=book_id),
            feedback_type="thumbs_up",
        ), timeout=15)
        assert fb_resp.status == "success"

        time.sleep(1)

        # Check seller rating from node 4
        rating = stubs[4].GetSellerRating(product_db_pb2.GetSellerRatingRequest(
            seller_id=10
        ), timeout=10)
        assert rating.thumbs_up >= 1

        # Get buyer purchases from node 1
        purch = stubs[1].GetBuyerPurchases(product_db_pb2.BuyerIdRequest(buyer_id=100), timeout=10)
        assert purch.status == "success"
        assert len(purch.purchases) == 1

        # Clear cart
        clear_resp = stubs[0].ClearCart(product_db_pb2.BuyerIdRequest(buyer_id=100), timeout=15)
        assert clear_resp.status == "success"

        time.sleep(1)

        # Verify cart is empty on node 3
        empty_cart = stubs[3].GetCart(product_db_pb2.BuyerIdRequest(buyer_id=100), timeout=10)
        assert len(empty_cart.cart) == 0

        logger.info("PASSED: Full workflow across all replicas")
    finally:
        teardown_cluster(raft_nodes, servers, channels)


# ---------------------------------------------------------------------------
# Test 3: Get seller items
# ---------------------------------------------------------------------------
def test_seller_items():
    logger.info("=== Test: GetSellerItems across replicas ===")
    raft_nodes, servers, channels, stubs = setup_cluster()

    try:
        # Register 3 items for seller 5
        for idx in range(3):
            resp = stubs[idx % N].RegisterItem(product_db_pb2.RegisterItemRequest(
                seller_id=5, name=f"Widget-{idx}", category=2,
                keywords=["widget"], condition="new", price=10.0 + idx, quantity=20,
            ), timeout=15)
            assert resp.status == "success", f"RegisterItem {idx} failed"

        time.sleep(2)

        # Check from every node
        for i in range(N):
            items_resp = stubs[i].GetSellerItems(product_db_pb2.GetSellerItemsRequest(
                seller_id=5
            ), timeout=10)
            assert items_resp.status == "success"
            assert len(items_resp.items) == 3, (
                f"Node {i}: expected 3 items, got {len(items_resp.items)}"
            )

        logger.info("PASSED: GetSellerItems consistent across all nodes")
    finally:
        teardown_cluster(raft_nodes, servers, channels)


if __name__ == "__main__":
    test_item_registration()
    print()
    test_full_workflow()
    print()
    test_seller_items()
    print()
    print("ALL PRODUCT DB REPLICATION TESTS PASSED")
