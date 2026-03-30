"""
Integration tests for the Rotating Sequencer Atomic Broadcast protocol.

Runs 5 nodes on localhost with different UDP ports and verifies:
1. All nodes deliver messages in the same total order.
2. All submitted messages are eventually delivered.
3. The protocol works when multiple nodes submit concurrently.
"""

import time
import threading
import logging
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from atomic_broadcast import AtomicBroadcastNode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test")

BASE_PORT = 17000  # Use high ports to avoid conflicts


def make_members(n=5, base_port=BASE_PORT):
    return [("127.0.0.1", base_port + i) for i in range(n)]


# ---------------------------------------------------------------------------
# Test 1: Single sender, 5 nodes
# ---------------------------------------------------------------------------
def test_single_sender():
    logger.info("=== Test 1: Single sender, 5 nodes ===")
    n = 5
    members = make_members(n)
    delivery_logs = [[] for _ in range(n)]
    locks = [threading.Lock() for _ in range(n)]

    def make_callback(node_idx):
        def on_deliver(payload):
            with locks[node_idx]:
                delivery_logs[node_idx].append(payload)
            return {"status": "ok"}
        return on_deliver

    nodes = []
    for i in range(n):
        node = AtomicBroadcastNode(i, members, make_callback(i))
        nodes.append(node)

    for node in nodes:
        node.start()
    time.sleep(0.2)  # let threads spin up

    # Node 0 sends 10 messages
    num_messages = 10
    for j in range(num_messages):
        result = nodes[0].broadcast_request({"msg": f"hello-{j}"}, timeout=10)
        assert result == {"status": "ok"}, f"Unexpected result: {result}"

    # Wait for all deliveries to propagate
    time.sleep(1)

    for node in nodes:
        node.stop()

    # Verify: all nodes delivered the same 10 messages in the same order
    for i in range(n):
        assert len(delivery_logs[i]) == num_messages, (
            f"Node {i} delivered {len(delivery_logs[i])} messages, expected {num_messages}"
        )

    # Check total order: all logs should be identical
    for i in range(1, n):
        assert delivery_logs[0] == delivery_logs[i], (
            f"Order mismatch: node 0 vs node {i}\n"
            f"  Node 0: {delivery_logs[0]}\n"
            f"  Node {i}: {delivery_logs[i]}"
        )

    logger.info("PASSED: All %d nodes delivered %d messages in identical order", n, num_messages)


# ---------------------------------------------------------------------------
# Test 2: Multiple concurrent senders
# ---------------------------------------------------------------------------
def test_concurrent_senders():
    logger.info("=== Test 2: Multiple concurrent senders, 5 nodes ===")
    n = 5
    members = make_members(n, base_port=BASE_PORT + 100)
    delivery_logs = [[] for _ in range(n)]
    locks = [threading.Lock() for _ in range(n)]

    def make_callback(node_idx):
        def on_deliver(payload):
            with locks[node_idx]:
                delivery_logs[node_idx].append(payload)
            return {"status": "ok"}
        return on_deliver

    nodes = []
    for i in range(n):
        node = AtomicBroadcastNode(i, members, make_callback(i))
        nodes.append(node)

    for node in nodes:
        node.start()
    time.sleep(0.2)

    # Each of the 5 nodes sends 5 messages concurrently
    msgs_per_node = 5
    total_messages = n * msgs_per_node
    errors = []

    def sender(node_idx):
        try:
            for j in range(msgs_per_node):
                nodes[node_idx].broadcast_request(
                    {"from": node_idx, "seq": j}, timeout=15
                )
        except Exception as e:
            errors.append((node_idx, e))

    threads = []
    for i in range(n):
        t = threading.Thread(target=sender, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=30)

    # Wait for delivery propagation
    time.sleep(2)

    for node in nodes:
        node.stop()

    assert not errors, f"Sender errors: {errors}"

    # All nodes should have delivered exactly total_messages
    for i in range(n):
        assert len(delivery_logs[i]) == total_messages, (
            f"Node {i} delivered {len(delivery_logs[i])}, expected {total_messages}"
        )

    # Total order: all logs identical
    for i in range(1, n):
        assert delivery_logs[0] == delivery_logs[i], (
            f"Order mismatch: node 0 vs node {i}\n"
            f"  Node 0: {delivery_logs[0]}\n"
            f"  Node {i}: {delivery_logs[i]}"
        )

    # All messages present (regardless of order)
    delivered_set = set()
    for payload in delivery_logs[0]:
        delivered_set.add((payload["from"], payload["seq"]))
    expected_set = {(i, j) for i in range(n) for j in range(msgs_per_node)}
    assert delivered_set == expected_set, (
        f"Missing messages: {expected_set - delivered_set}"
    )

    logger.info(
        "PASSED: %d concurrent senders, %d total messages, identical order on all nodes",
        n, total_messages,
    )


# ---------------------------------------------------------------------------
# Test 3: 3-node group (odd majority = 2)
# ---------------------------------------------------------------------------
def test_three_nodes():
    logger.info("=== Test 3: 3-node group ===")
    n = 3
    members = make_members(n, base_port=BASE_PORT + 200)
    delivery_logs = [[] for _ in range(n)]
    locks = [threading.Lock() for _ in range(n)]

    def make_callback(node_idx):
        def on_deliver(payload):
            with locks[node_idx]:
                delivery_logs[node_idx].append(payload)
            return payload.get("value", 0) * 2
        return on_deliver

    nodes = []
    for i in range(n):
        node = AtomicBroadcastNode(i, members, make_callback(i))
        nodes.append(node)

    for node in nodes:
        node.start()
    time.sleep(0.2)

    # Node 1 sends 5 messages, check return values
    results = []
    for j in range(5):
        r = nodes[1].broadcast_request({"value": j + 1}, timeout=10)
        results.append(r)

    time.sleep(1)
    for node in nodes:
        node.stop()

    # Verify return values (value * 2)
    expected_results = [2, 4, 6, 8, 10]
    assert results == expected_results, f"Results: {results}, expected: {expected_results}"

    # Verify all nodes got the same deliveries
    for i in range(n):
        assert len(delivery_logs[i]) == 5, f"Node {i} delivered {len(delivery_logs[i])}"
    for i in range(1, n):
        assert delivery_logs[0] == delivery_logs[i]

    logger.info("PASSED: 3-node group, return values correct, total order maintained")


# ---------------------------------------------------------------------------
# Test 4: Stress test with higher message count
# ---------------------------------------------------------------------------
def test_stress():
    logger.info("=== Test 4: Stress test (5 nodes, 3 senders, 20 msgs each) ===")
    n = 5
    members = make_members(n, base_port=BASE_PORT + 300)
    delivery_logs = [[] for _ in range(n)]
    locks = [threading.Lock() for _ in range(n)]

    def make_callback(node_idx):
        def on_deliver(payload):
            with locks[node_idx]:
                delivery_logs[node_idx].append(payload)
            return "ok"
        return on_deliver

    nodes = []
    for i in range(n):
        node = AtomicBroadcastNode(i, members, make_callback(i))
        nodes.append(node)

    for node in nodes:
        node.start()
    time.sleep(0.2)

    senders = [0, 2, 4]
    msgs_per_sender = 20
    total = len(senders) * msgs_per_sender
    errors = []

    def sender(node_idx):
        try:
            for j in range(msgs_per_sender):
                nodes[node_idx].broadcast_request(
                    {"s": node_idx, "i": j}, timeout=20
                )
        except Exception as e:
            errors.append((node_idx, e))

    threads = [threading.Thread(target=sender, args=(i,)) for i in senders]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    time.sleep(3)
    for node in nodes:
        node.stop()

    assert not errors, f"Errors: {errors}"

    for i in range(n):
        assert len(delivery_logs[i]) == total, (
            f"Node {i}: {len(delivery_logs[i])} delivered, expected {total}"
        )

    for i in range(1, n):
        assert delivery_logs[0] == delivery_logs[i], f"Order mismatch node 0 vs {i}"

    logger.info("PASSED: Stress test — %d messages delivered in identical order on all %d nodes", total, n)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_single_sender()
    print()
    test_concurrent_senders()
    print()
    test_three_nodes()
    print()
    test_stress()
    print()
    print("ALL TESTS PASSED")
