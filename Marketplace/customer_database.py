import grpc
import sqlite3
import threading
import time
import uuid
import argparse
from concurrent import futures

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import customer_db_pb2
import customer_db_pb2_grpc

DB_FILE = 'customer_data.db'
db_lock = threading.Lock()


def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)


def init_db():
    with db_lock:
        conn = get_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id   INTEGER PRIMARY KEY AUTOINCREMENT,
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


class CustomerDBServicer(customer_db_pb2_grpc.CustomerDBServicer):

    def StoreUser(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                cursor = conn.execute(
                    'INSERT INTO users (username, password, name, user_type) VALUES (?, ?, ?, ?)',
                    (request.username, request.password, request.name, request.user_type)
                )
                conn.commit()
                user_id = cursor.lastrowid
                return customer_db_pb2.StoreUserResponse(
                    status='success', message='User created', user_id=user_id
                )
            except sqlite3.IntegrityError:
                return customer_db_pb2.StoreUserResponse(
                    status='error', message='Username already exists', user_id=0
                )
            finally:
                conn.close()

    def GetUser(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                row = conn.execute(
                    'SELECT user_id, username, password, name, user_type FROM users WHERE username = ?',
                    (request.username,)
                ).fetchone()
                if row is None:
                    return customer_db_pb2.GetUserResponse(status='error', message='User not found')
                return customer_db_pb2.GetUserResponse(
                    status='success', message='',
                    user_id=row[0], username=row[1], password=row[2],
                    name=row[3], user_type=row[4]
                )
            finally:
                conn.close()

    def StoreSession(self, request, context):
        session_id = str(uuid.uuid4())
        with db_lock:
            conn = get_connection()
            try:
                conn.execute(
                    'INSERT INTO sessions (session_id, user_id, user_type, last_activity) VALUES (?, ?, ?, ?)',
                    (session_id, request.user_id, request.user_type, time.time())
                )
                conn.commit()
                return customer_db_pb2.StoreSessionResponse(
                    status='success', message='', session_id=session_id
                )
            finally:
                conn.close()

    def GetSession(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                row = conn.execute(
                    'SELECT user_id, user_type, last_activity FROM sessions WHERE session_id = ?',
                    (request.session_id,)
                ).fetchone()
                if row is None:
                    return customer_db_pb2.GetSessionResponse(status='error', message='Session not found')
                user_id, user_type, last_activity = row
                if time.time() - last_activity > 300:
                    conn.execute('DELETE FROM sessions WHERE session_id = ?', (request.session_id,))
                    conn.commit()
                    return customer_db_pb2.GetSessionResponse(status='error', message='Session expired')
                return customer_db_pb2.GetSessionResponse(
                    status='success', message='',
                    user_id=user_id, user_type=user_type, last_activity=last_activity
                )
            finally:
                conn.close()

    def UpdateSessionActivity(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                conn.execute(
                    'UPDATE sessions SET last_activity = ? WHERE session_id = ?',
                    (time.time(), request.session_id)
                )
                conn.commit()
                return customer_db_pb2.StatusResponse(status='success', message='')
            finally:
                conn.close()

    def DeleteSession(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                conn.execute('DELETE FROM sessions WHERE session_id = ?', (request.session_id,))
                conn.commit()
                return customer_db_pb2.StatusResponse(status='success', message='')
            finally:
                conn.close()


def serve(host='0.0.0.0', port=50051):
    init_db()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    customer_db_pb2_grpc.add_CustomerDBServicer_to_server(CustomerDBServicer(), server)
    server.add_insecure_port(f'{host}:{port}')
    server.start()
    print(f'Customer Database gRPC server listening on {host}:{port}')
    server.wait_for_termination()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Customer Database gRPC Server')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=50051)
    args = parser.parse_args()
    serve(host=args.host, port=args.port)
