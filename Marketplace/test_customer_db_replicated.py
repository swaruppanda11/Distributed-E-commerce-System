"""
Integration test for the replicated customer database.

Spins up 5 replicas on localhost, issues gRPC calls, and verifies:
1. User creation replicates to all nodes.
2. Session create/get/update/delete work across replicas.
3. Concurrent user registrations from different replicas succeed.
"""

import grpc
import time
import threading
import os
import glob
import logging
import sys

sys.path.insert(0, os.path.dirname(__file__))

import customer_db_pb2
import customer_db_pb2_grpc
from atomic_broadcast import AtomicBroadcastNode
from customer_database_replicated import (
    ReplicatedCustomerDBServicer,
    make_deliver_callback,
    init_db,
)
from concurrent import futures

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test")

UDP_BASE = 18000
GRPC_BASE = 50100
N = 5


def cleanup_dbs():
    for f in glob.glob("customer_data_node*.db"):
        os.remove(f)


def setup_cluster():
    """Create 5 replicated customer DB nodes and return (nodes, servers, channels, stubs)."""
    members = [("127.0.0.1", UDP_BASE + i) for i in range(N)]
    broadcast_nodes = []
    servers = []
    stubs = []
    channels = []

    for i in range(N):
        db_file = f"customer_data_node{i}.db"
        init_db(db_file)

        on_deliver = make_deliver_callback(db_file)
        bnode = AtomicBroadcastNode(i, members, on_deliver)
        bnode.start()
        broadcast_nodes.append(bnode)

        servicer = ReplicatedCustomerDBServicer(db_file, bnode)
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=5))
        customer_db_pb2_grpc.add_CustomerDBServicer_to_server(servicer, server)
        port = GRPC_BASE + i
        server.add_insecure_port(f"127.0.0.1:{port}")
        server.start()
        servers.append(server)

        channel = grpc.insecure_channel(f"127.0.0.1:{port}")
        channels.append(channel)
        stubs.append(customer_db_pb2_grpc.CustomerDBStub(channel))

    time.sleep(0.5)  # let everything spin up
    return broadcast_nodes, servers, channels, stubs


def teardown_cluster(broadcast_nodes, servers, channels):
    for ch in channels:
        ch.close()
    for s in servers:
        s.stop(0)
    for bn in broadcast_nodes:
        bn.stop()
    time.sleep(0.3)
    cleanup_dbs()


def test_user_replication():
    logger.info("=== Test: User creation replicates to all nodes ===")
    cleanup_dbs()
    bnodes, servers, channels, stubs = setup_cluster()

    try:
        # Create user via node 0
        resp = stubs[0].StoreUser(customer_db_pb2.StoreUserRequest(
            username="alice", password="pass123", name="Alice", user_type="buyer"
        ))
        assert resp.status == "success", f"StoreUser failed: {resp.message}"
        alice_id = resp.user_id
        assert alice_id > 0

        # Wait for replication
        time.sleep(1)

        # Verify user exists on ALL replicas
        for i in range(N):
            get_resp = stubs[i].GetUser(customer_db_pb2.GetUserRequest(username="alice"))
            assert get_resp.status == "success", f"Node {i}: GetUser failed: {get_resp.message}"
            assert get_resp.user_id == alice_id, f"Node {i}: user_id mismatch"
            assert get_resp.name == "Alice"
            assert get_resp.user_type == "buyer"

        # Duplicate username should fail
        resp2 = stubs[2].StoreUser(customer_db_pb2.StoreUserRequest(
            username="alice", password="other", name="Alice2", user_type="seller"
        ))
        assert resp2.status == "error", "Duplicate username should fail"

        logger.info("PASSED: User creation replicated to all %d nodes", N)
    finally:
        teardown_cluster(bnodes, servers, channels)


def test_session_lifecycle():
    logger.info("=== Test: Session create/get/update/delete across replicas ===")
    cleanup_dbs()
    bnodes, servers, channels, stubs = setup_cluster()

    try:
        # Create user via node 1
        resp = stubs[1].StoreUser(customer_db_pb2.StoreUserRequest(
            username="bob", password="pw", name="Bob", user_type="seller"
        ))
        assert resp.status == "success"
        bob_id = resp.user_id

        time.sleep(0.5)

        # Create session via node 2
        sess_resp = stubs[2].StoreSession(customer_db_pb2.StoreSessionRequest(
            user_id=bob_id, user_type="seller"
        ))
        assert sess_resp.status == "success"
        session_id = sess_resp.session_id
        assert len(session_id) > 0

        time.sleep(1)

        # Get session from node 4
        get_resp = stubs[4].GetSession(customer_db_pb2.GetSessionRequest(
            session_id=session_id
        ))
        assert get_resp.status == "success", f"GetSession failed: {get_resp.message}"
        assert get_resp.user_id == bob_id
        assert get_resp.user_type == "seller"

        # Update session activity via node 3
        upd_resp = stubs[3].UpdateSessionActivity(customer_db_pb2.SessionRequest(
            session_id=session_id
        ))
        assert upd_resp.status == "success"

        time.sleep(0.5)

        # Delete session via node 0
        del_resp = stubs[0].DeleteSession(customer_db_pb2.SessionRequest(
            session_id=session_id
        ))
        assert del_resp.status == "success"

        time.sleep(0.5)

        # Session should be gone on all nodes
        for i in range(N):
            get_resp = stubs[i].GetSession(customer_db_pb2.GetSessionRequest(
                session_id=session_id
            ))
            assert get_resp.status == "error", f"Node {i}: session should be deleted"

        logger.info("PASSED: Session lifecycle works across replicas")
    finally:
        teardown_cluster(bnodes, servers, channels)


def test_concurrent_registrations():
    logger.info("=== Test: Concurrent user registrations from different replicas ===")
    cleanup_dbs()
    bnodes, servers, channels, stubs = setup_cluster()

    try:
        errors = []
        results = [None] * N

        def register(node_idx):
            try:
                resp = stubs[node_idx].StoreUser(customer_db_pb2.StoreUserRequest(
                    username=f"user_{node_idx}",
                    password="pw",
                    name=f"User {node_idx}",
                    user_type="buyer",
                ))
                results[node_idx] = resp
            except Exception as e:
                errors.append((node_idx, e))

        threads = [threading.Thread(target=register, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        assert not errors, f"Errors: {errors}"

        # All should succeed
        for i in range(N):
            assert results[i].status == "success", (
                f"Node {i}: {results[i].status} - {results[i].message}"
            )

        time.sleep(1)

        # All users should be visible on all nodes
        for i in range(N):
            for j in range(N):
                get_resp = stubs[j].GetUser(customer_db_pb2.GetUserRequest(
                    username=f"user_{i}"
                ))
                assert get_resp.status == "success", (
                    f"Node {j}: can't find user_{i}: {get_resp.message}"
                )

        # All user_ids should be unique
        ids = set()
        for i in range(N):
            ids.add(results[i].user_id)
        assert len(ids) == N, f"Non-unique user_ids: {[r.user_id for r in results]}"

        logger.info("PASSED: %d concurrent registrations all succeeded with unique IDs", N)
    finally:
        teardown_cluster(bnodes, servers, channels)


if __name__ == "__main__":
    test_user_replication()
    print()
    test_session_lifecycle()
    print()
    test_concurrent_registrations()
    print()
    print("ALL CUSTOMER DB REPLICATION TESTS PASSED")
