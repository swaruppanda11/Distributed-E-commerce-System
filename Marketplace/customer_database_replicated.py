"""
Replicated Customer Database using Rotating Sequencer Atomic Broadcast.

Each replica runs:
  - A gRPC server (same interface as customer_database.py)
  - An AtomicBroadcastNode for total-order replication of write operations

Read operations go directly to local SQLite.
Write operations are broadcast and applied in identical order on all replicas.
"""

import grpc
import sqlite3
import threading
import time
import uuid
import argparse
import logging
from concurrent import futures

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import customer_db_pb2
import customer_db_pb2_grpc
from atomic_broadcast import AtomicBroadcastNode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

db_lock = threading.Lock()


def get_connection(db_file):
    return sqlite3.connect(db_file, check_same_thread=False)


def init_db(db_file):
    with db_lock:
        conn = get_connection(db_file)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id   INTEGER PRIMARY KEY,
                username  TEXT UNIQUE NOT NULL,
                password  TEXT NOT NULL,
                name      TEXT NOT NULL,
                user_type TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id    TEXT PRIMARY KEY,
                user_id       INTEGER NOT NULL,
                user_type     TEXT NOT NULL,
                last_activity REAL NOT NULL
            )
        ''')
        conn.commit()
        conn.close()


class ReplicatedCustomerDBServicer(customer_db_pb2_grpc.CustomerDBServicer):
    """
    gRPC servicer that replicates writes via atomic broadcast.
    """

    def __init__(self, db_file, broadcast_node):
        self.db_file = db_file
        self.broadcast_node = broadcast_node

    # -------------------------------------------------------------------
    # Write operations — go through atomic broadcast
    # -------------------------------------------------------------------

    def StoreUser(self, request, context):
        # Pre-compute user_id so all replicas use the same value
        with db_lock:
            conn = get_connection(self.db_file)
            try:
                row = conn.execute('SELECT MAX(user_id) FROM users').fetchone()
                next_id = (row[0] or 0) + 1
            finally:
                conn.close()

        payload = {
            "op": "StoreUser",
            "user_id": next_id,
            "username": request.username,
            "password": request.password,
            "name": request.name,
            "user_type": request.user_type,
        }

        try:
            result = self.broadcast_node.broadcast_request(payload, timeout=15)
        except TimeoutError:
            return customer_db_pb2.StoreUserResponse(
                status='error', message='Replication timeout', user_id=0
            )

        return customer_db_pb2.StoreUserResponse(
            status=result["status"],
            message=result["message"],
            user_id=result.get("user_id", 0),
        )

    def StoreSession(self, request, context):
        # Pre-compute session_id and timestamp for determinism
        session_id = str(uuid.uuid4())
        now = time.time()

        payload = {
            "op": "StoreSession",
            "session_id": session_id,
            "user_id": request.user_id,
            "user_type": request.user_type,
            "timestamp": now,
        }

        try:
            result = self.broadcast_node.broadcast_request(payload, timeout=15)
        except TimeoutError:
            return customer_db_pb2.StoreSessionResponse(
                status='error', message='Replication timeout', session_id=''
            )

        return customer_db_pb2.StoreSessionResponse(
            status=result["status"],
            message=result["message"],
            session_id=result.get("session_id", ""),
        )

    def UpdateSessionActivity(self, request, context):
        now = time.time()

        payload = {
            "op": "UpdateSessionActivity",
            "session_id": request.session_id,
            "timestamp": now,
        }

        try:
            result = self.broadcast_node.broadcast_request(payload, timeout=15)
        except TimeoutError:
            return customer_db_pb2.StatusResponse(
                status='error', message='Replication timeout'
            )

        return customer_db_pb2.StatusResponse(
            status=result["status"], message=result["message"]
        )

    def DeleteSession(self, request, context):
        payload = {
            "op": "DeleteSession",
            "session_id": request.session_id,
        }

        try:
            result = self.broadcast_node.broadcast_request(payload, timeout=15)
        except TimeoutError:
            return customer_db_pb2.StatusResponse(
                status='error', message='Replication timeout'
            )

        return customer_db_pb2.StatusResponse(
            status=result["status"], message=result["message"]
        )

    # -------------------------------------------------------------------
    # Read operations — go directly to local SQLite
    # -------------------------------------------------------------------

    def GetUser(self, request, context):
        with db_lock:
            conn = get_connection(self.db_file)
            try:
                row = conn.execute(
                    'SELECT user_id, username, password, name, user_type FROM users WHERE username = ?',
                    (request.username,)
                ).fetchone()
                if row is None:
                    return customer_db_pb2.GetUserResponse(
                        status='error', message='User not found'
                    )
                return customer_db_pb2.GetUserResponse(
                    status='success', message='',
                    user_id=row[0], username=row[1], password=row[2],
                    name=row[3], user_type=row[4]
                )
            finally:
                conn.close()

    def GetSession(self, request, context):
        with db_lock:
            conn = get_connection(self.db_file)
            try:
                row = conn.execute(
                    'SELECT user_id, user_type, last_activity FROM sessions WHERE session_id = ?',
                    (request.session_id,)
                ).fetchone()
                if row is None:
                    return customer_db_pb2.GetSessionResponse(
                        status='error', message='Session not found'
                    )
                user_id, user_type, last_activity = row
                if time.time() - last_activity > 300:
                    conn.execute(
                        'DELETE FROM sessions WHERE session_id = ?',
                        (request.session_id,)
                    )
                    conn.commit()
                    return customer_db_pb2.GetSessionResponse(
                        status='error', message='Session expired'
                    )
                return customer_db_pb2.GetSessionResponse(
                    status='success', message='',
                    user_id=user_id, user_type=user_type,
                    last_activity=last_activity
                )
            finally:
                conn.close()


# -----------------------------------------------------------------------
# Delivery callback — executed in total order on every replica
# -----------------------------------------------------------------------

def make_deliver_callback(db_file):
    """
    Returns a callback that applies write operations to local SQLite.
    Called by the atomic broadcast node when a request is delivered.
    """

    def on_deliver(payload):
        op = payload["op"]

        if op == "StoreUser":
            return _deliver_store_user(db_file, payload)
        elif op == "StoreSession":
            return _deliver_store_session(db_file, payload)
        elif op == "UpdateSessionActivity":
            return _deliver_update_session(db_file, payload)
        elif op == "DeleteSession":
            return _deliver_delete_session(db_file, payload)
        else:
            logger.error("Unknown operation: %s", op)
            return {"status": "error", "message": f"Unknown operation: {op}"}

    return on_deliver


def _deliver_store_user(db_file, payload):
    user_id = payload["user_id"]
    username = payload["username"]
    password = payload["password"]
    name = payload["name"]
    user_type = payload["user_type"]

    with db_lock:
        conn = get_connection(db_file)
        try:
            # Check if username already exists
            existing = conn.execute(
                'SELECT user_id FROM users WHERE username = ?', (username,)
            ).fetchone()
            if existing:
                return {"status": "error", "message": "Username already exists", "user_id": 0}

            # Check if user_id is already taken (race from another broadcast)
            existing_id = conn.execute(
                'SELECT user_id FROM users WHERE user_id = ?', (user_id,)
            ).fetchone()
            if existing_id:
                # Reassign to next available ID
                row = conn.execute('SELECT MAX(user_id) FROM users').fetchone()
                user_id = (row[0] or 0) + 1

            conn.execute(
                'INSERT INTO users (user_id, username, password, name, user_type) VALUES (?, ?, ?, ?, ?)',
                (user_id, username, password, name, user_type)
            )
            conn.commit()
            return {"status": "success", "message": "User created", "user_id": user_id}
        except sqlite3.IntegrityError:
            return {"status": "error", "message": "Username already exists", "user_id": 0}
        finally:
            conn.close()


def _deliver_store_session(db_file, payload):
    session_id = payload["session_id"]
    user_id = payload["user_id"]
    user_type = payload["user_type"]
    timestamp = payload["timestamp"]

    with db_lock:
        conn = get_connection(db_file)
        try:
            conn.execute(
                'INSERT INTO sessions (session_id, user_id, user_type, last_activity) VALUES (?, ?, ?, ?)',
                (session_id, user_id, user_type, timestamp)
            )
            conn.commit()
            return {"status": "success", "message": "", "session_id": session_id}
        finally:
            conn.close()


def _deliver_update_session(db_file, payload):
    session_id = payload["session_id"]
    timestamp = payload["timestamp"]

    with db_lock:
        conn = get_connection(db_file)
        try:
            conn.execute(
                'UPDATE sessions SET last_activity = ? WHERE session_id = ?',
                (timestamp, session_id)
            )
            conn.commit()
            return {"status": "success", "message": ""}
        finally:
            conn.close()


def _deliver_delete_session(db_file, payload):
    session_id = payload["session_id"]

    with db_lock:
        conn = get_connection(db_file)
        try:
            conn.execute(
                'DELETE FROM sessions WHERE session_id = ?', (session_id,)
            )
            conn.commit()
            return {"status": "success", "message": ""}
        finally:
            conn.close()


# -----------------------------------------------------------------------
# Server entry point
# -----------------------------------------------------------------------

def parse_members(members_str):
    """Parse 'host1:port1,host2:port2,...' into [(host, port), ...]."""
    result = []
    for entry in members_str.split(","):
        host, port = entry.strip().rsplit(":", 1)
        result.append((host, int(port)))
    return result


def serve(node_id, members, grpc_host='0.0.0.0', grpc_port=50051):
    db_file = f'customer_data_node{node_id}.db'
    init_db(db_file)

    # Create atomic broadcast node
    on_deliver = make_deliver_callback(db_file)
    broadcast_node = AtomicBroadcastNode(node_id, members, on_deliver)
    broadcast_node.start()

    # Create gRPC server
    servicer = ReplicatedCustomerDBServicer(db_file, broadcast_node)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    customer_db_pb2_grpc.add_CustomerDBServicer_to_server(servicer, server)
    server.add_insecure_port(f'{grpc_host}:{grpc_port}')
    server.start()

    logger.info(
        "Replicated Customer DB node %d | gRPC %s:%d | UDP %s:%d",
        node_id, grpc_host, grpc_port, *members[node_id]
    )

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        pass
    finally:
        broadcast_node.stop()
        server.stop(0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Replicated Customer Database')
    parser.add_argument('--node-id', type=int, required=True,
                        help='Unique node ID (0 to n-1)')
    parser.add_argument('--members', type=str, required=True,
                        help='Comma-separated list of host:udp_port for all members')
    parser.add_argument('--grpc-host', default='0.0.0.0')
    parser.add_argument('--grpc-port', type=int, default=50051)
    args = parser.parse_args()

    members = parse_members(args.members)
    serve(args.node_id, members, args.grpc_host, args.grpc_port)
