import grpc
import sqlite3
import threading
import argparse
from concurrent import futures
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import product_db_pb2
import product_db_pb2_grpc

DB_FILE = 'product_data.db'
db_lock = threading.Lock()


def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)


def init_db():
    with db_lock:
        conn = get_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS items (
                category    INTEGER NOT NULL,
                item_id     INTEGER NOT NULL,
                seller_id   INTEGER NOT NULL,
                name        TEXT NOT NULL,
                keywords    TEXT NOT NULL,
                condition   TEXT NOT NULL,
                price       REAL NOT NULL,
                quantity    INTEGER NOT NULL,
                thumbs_up   INTEGER DEFAULT 0,
                thumbs_down INTEGER DEFAULT 0,
                PRIMARY KEY (category, item_id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS item_counter (
                id      INTEGER PRIMARY KEY,
                counter INTEGER NOT NULL DEFAULT 0
            )
        ''')
        conn.execute('INSERT OR IGNORE INTO item_counter (id, counter) VALUES (1, 0)')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS carts (
                buyer_id INTEGER NOT NULL,
                category INTEGER NOT NULL,
                item_id  INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                PRIMARY KEY (buyer_id, category, item_id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS seller_feedback (
                seller_id   INTEGER PRIMARY KEY,
                thumbs_up   INTEGER DEFAULT 0,
                thumbs_down INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS purchases (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_id  INTEGER NOT NULL,
                category  INTEGER NOT NULL,
                item_id   INTEGER NOT NULL,
                quantity  INTEGER NOT NULL,
                timestamp TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()


def _next_item_id(conn):
    conn.execute('UPDATE item_counter SET counter = counter + 1 WHERE id = 1')
    row = conn.execute('SELECT counter FROM item_counter WHERE id = 1').fetchone()
    return row[0]


def _row_to_item(row):
    cat, iid, seller_id, name, kw_str, condition, price, quantity, thumbs_up, thumbs_down = row
    keywords = kw_str.split(',') if kw_str else []
    return product_db_pb2.ItemData(
        item_id=product_db_pb2.ItemId(category=cat, item_id=iid),
        seller_id=seller_id,
        name=name,
        category=cat,
        keywords=keywords,
        condition=condition,
        price=price,
        quantity=quantity,
        thumbs_up=thumbs_up,
        thumbs_down=thumbs_down
    )


class ProductDBServicer(product_db_pb2_grpc.ProductDBServicer):

    def RegisterItem(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                new_id = _next_item_id(conn)
                kw_str = ','.join(request.keywords)
                conn.execute(
                    'INSERT INTO items (category, item_id, seller_id, name, keywords, condition, price, quantity) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (request.category, new_id, request.seller_id, request.name,
                     kw_str, request.condition, request.price, request.quantity)
                )
                conn.execute('INSERT OR IGNORE INTO seller_feedback (seller_id) VALUES (?)', (request.seller_id,))
                conn.commit()
                item_id = product_db_pb2.ItemId(category=request.category, item_id=new_id)
                return product_db_pb2.RegisterItemResponse(status='success', message='', item_id=item_id)
            finally:
                conn.close()

    def GetItem(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                row = conn.execute(
                    'SELECT category, item_id, seller_id, name, keywords, condition, price, quantity, '
                    'thumbs_up, thumbs_down FROM items WHERE category = ? AND item_id = ?',
                    (request.item_id.category, request.item_id.item_id)
                ).fetchone()
                if row is None:
                    return product_db_pb2.GetItemResponse(status='error', message='Item not found')
                return product_db_pb2.GetItemResponse(status='success', message='', item=_row_to_item(row))
            finally:
                conn.close()

    def UpdateItemPrice(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                conn.execute(
                    'UPDATE items SET price = ? WHERE category = ? AND item_id = ?',
                    (request.price, request.item_id.category, request.item_id.item_id)
                )
                conn.commit()
                return product_db_pb2.StatusResponse(status='success', message='')
            finally:
                conn.close()

    def UpdateItemQuantity(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                conn.execute(
                    'UPDATE items SET quantity = ? WHERE category = ? AND item_id = ?',
                    (request.quantity, request.item_id.category, request.item_id.item_id)
                )
                conn.commit()
                return product_db_pb2.StatusResponse(status='success', message='')
            finally:
                conn.close()

    def GetSellerItems(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                rows = conn.execute(
                    'SELECT category, item_id, seller_id, name, keywords, condition, price, quantity, '
                    'thumbs_up, thumbs_down FROM items WHERE seller_id = ?',
                    (request.seller_id,)
                ).fetchall()
                items = [_row_to_item(r) for r in rows]
                return product_db_pb2.GetItemsResponse(status='success', message='', items=items)
            finally:
                conn.close()

    def SearchItems(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                rows = conn.execute(
                    'SELECT category, item_id, seller_id, name, keywords, condition, price, quantity, '
                    'thumbs_up, thumbs_down FROM items WHERE quantity > 0'
                ).fetchall()
                results = []
                for row in rows:
                    cat, iid, seller_id, name, kw_str, condition, price, qty, tu, td = row
                    if request.has_category and cat != request.category:
                        continue
                    keywords = kw_str.split(',') if kw_str else []
                    if request.keywords:
                        kw_lower = [k.lower() for k in keywords]
                        if not any(k.lower() in kw_lower for k in request.keywords):
                            continue
                    results.append(_row_to_item(row))
                return product_db_pb2.GetItemsResponse(status='success', message='', items=results)
            finally:
                conn.close()

    def StoreCart(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                conn.execute('DELETE FROM carts WHERE buyer_id = ?', (request.buyer_id,))
                for cart_item in request.cart:
                    conn.execute(
                        'INSERT INTO carts (buyer_id, category, item_id, quantity) VALUES (?, ?, ?, ?)',
                        (request.buyer_id, cart_item.item_id.category, cart_item.item_id.item_id, cart_item.quantity)
                    )
                conn.commit()
                return product_db_pb2.StatusResponse(status='success', message='')
            finally:
                conn.close()

    def GetCart(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                rows = conn.execute(
                    'SELECT category, item_id, quantity FROM carts WHERE buyer_id = ?',
                    (request.buyer_id,)
                ).fetchall()
                cart = [
                    product_db_pb2.CartItem(
                        item_id=product_db_pb2.ItemId(category=r[0], item_id=r[1]),
                        quantity=r[2]
                    )
                    for r in rows
                ]
                return product_db_pb2.GetCartResponse(status='success', message='', cart=cart)
            finally:
                conn.close()

    def ClearCart(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                conn.execute('DELETE FROM carts WHERE buyer_id = ?', (request.buyer_id,))
                conn.commit()
                return product_db_pb2.StatusResponse(status='success', message='')
            finally:
                conn.close()

    def AddItemFeedback(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                row = conn.execute(
                    'SELECT seller_id FROM items WHERE category = ? AND item_id = ?',
                    (request.item_id.category, request.item_id.item_id)
                ).fetchone()
                if row is None:
                    return product_db_pb2.StatusResponse(status='error', message='Item not found')
                seller_id = row[0]
                if request.feedback_type == 'thumbs_up':
                    conn.execute(
                        'UPDATE items SET thumbs_up = thumbs_up + 1 WHERE category = ? AND item_id = ?',
                        (request.item_id.category, request.item_id.item_id)
                    )
                    conn.execute(
                        'UPDATE seller_feedback SET thumbs_up = thumbs_up + 1 WHERE seller_id = ?',
                        (seller_id,)
                    )
                else:
                    conn.execute(
                        'UPDATE items SET thumbs_down = thumbs_down + 1 WHERE category = ? AND item_id = ?',
                        (request.item_id.category, request.item_id.item_id)
                    )
                    conn.execute(
                        'UPDATE seller_feedback SET thumbs_down = thumbs_down + 1 WHERE seller_id = ?',
                        (seller_id,)
                    )
                conn.commit()
                return product_db_pb2.StatusResponse(status='success', message='')
            finally:
                conn.close()

    def GetSellerRating(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                row = conn.execute(
                    'SELECT thumbs_up, thumbs_down FROM seller_feedback WHERE seller_id = ?',
                    (request.seller_id,)
                ).fetchone()
                if row is None:
                    return product_db_pb2.GetSellerRatingResponse(
                        status='success', message='', thumbs_up=0, thumbs_down=0
                    )
                return product_db_pb2.GetSellerRatingResponse(
                    status='success', message='', thumbs_up=row[0], thumbs_down=row[1]
                )
            finally:
                conn.close()

    def MakePurchase(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                row = conn.execute(
                    'SELECT quantity FROM items WHERE category = ? AND item_id = ?',
                    (request.item_id.category, request.item_id.item_id)
                ).fetchone()
                if row is None:
                    return product_db_pb2.StatusResponse(status='error', message='Item not found')
                if row[0] < request.quantity:
                    return product_db_pb2.StatusResponse(status='error', message='Not enough stock')
                conn.execute(
                    'UPDATE items SET quantity = quantity - ? WHERE category = ? AND item_id = ?',
                    (request.quantity, request.item_id.category, request.item_id.item_id)
                )
                timestamp = datetime.utcnow().isoformat()
                conn.execute(
                    'INSERT INTO purchases (buyer_id, category, item_id, quantity, timestamp) VALUES (?, ?, ?, ?, ?)',
                    (request.buyer_id, request.item_id.category, request.item_id.item_id,
                     request.quantity, timestamp)
                )
                conn.commit()
                return product_db_pb2.StatusResponse(status='success', message='')
            finally:
                conn.close()

    def GetBuyerPurchases(self, request, context):
        with db_lock:
            conn = get_connection()
            try:
                rows = conn.execute(
                    'SELECT category, item_id, quantity, timestamp FROM purchases WHERE buyer_id = ?',
                    (request.buyer_id,)
                ).fetchall()
                purchases = [
                    product_db_pb2.PurchaseRecord(
                        item_id=product_db_pb2.ItemId(category=r[0], item_id=r[1]),
                        quantity=r[2],
                        timestamp=r[3]
                    )
                    for r in rows
                ]
                return product_db_pb2.GetBuyerPurchasesResponse(
                    status='success', message='', purchases=purchases
                )
            finally:
                conn.close()


def serve(host='0.0.0.0', port=50052):
    init_db()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    product_db_pb2_grpc.add_ProductDBServicer_to_server(ProductDBServicer(), server)
    server.add_insecure_port(f'{host}:{port}')
    server.start()
    print(f'Product Database gRPC server listening on {host}:{port}')
    server.wait_for_termination()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Product Database gRPC Server')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=50052)
    args = parser.parse_args()
    serve(host=args.host, port=args.port)
