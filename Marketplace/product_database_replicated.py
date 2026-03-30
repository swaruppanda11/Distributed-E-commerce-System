"""
Replicated Product Database using Raft (PySyncObj).

Each replica runs:
  - A gRPC server (same interface as product_database.py)
  - A PySyncObj Raft node for consensus on write operations

All state is kept in-memory inside the SyncObj subclass. PySyncObj handles
leader election, log replication, snapshots, and crash recovery.

Write operations use @replicated methods (go through Raft consensus).
Read operations go directly to local in-memory state.
"""

import grpc
import threading
import argparse
import logging
import time
from concurrent import futures
from datetime import datetime

from pysyncobj import SyncObj, SyncObjConf, replicated

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import product_db_pb2
import product_db_pb2_grpc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Raft-replicated product state
# ---------------------------------------------------------------------------

class RaftProductDB(SyncObj):
    """
    All product data held in-memory, replicated via Raft.
    Write methods are decorated with @replicated so they go through consensus.
    Read methods are plain Python — they read local state directly.
    """

    def __init__(self, self_addr, partners, conf=None):
        super().__init__(self_addr, partners, conf)
        self._items = {}           # (category, item_id) -> dict
        self._item_counter = 0
        self._carts = {}           # buyer_id -> [(category, item_id, quantity), ...]
        self._seller_feedback = {} # seller_id -> {"thumbs_up": int, "thumbs_down": int}
        self._purchases = []       # [{"buyer_id":, "category":, "item_id":, "quantity":, "timestamp":}, ...]

    # --- Write operations (Raft-replicated) ---

    @replicated
    def register_item(self, seller_id, name, category, keywords, condition, price, quantity):
        self._item_counter += 1
        item_id = self._item_counter
        self._items[(category, item_id)] = {
            "seller_id": seller_id,
            "name": name,
            "category": category,
            "keywords": keywords,
            "condition": condition,
            "price": price,
            "quantity": quantity,
            "thumbs_up": 0,
            "thumbs_down": 0,
        }
        if seller_id not in self._seller_feedback:
            self._seller_feedback[seller_id] = {"thumbs_up": 0, "thumbs_down": 0}
        return {"status": "success", "category": category, "item_id": item_id}

    @replicated
    def update_item_price(self, category, item_id, price):
        key = (category, item_id)
        if key in self._items:
            self._items[key]["price"] = price
            return {"status": "success"}
        return {"status": "error", "message": "Item not found"}

    @replicated
    def update_item_quantity(self, category, item_id, quantity):
        key = (category, item_id)
        if key in self._items:
            self._items[key]["quantity"] = quantity
            return {"status": "success"}
        return {"status": "error", "message": "Item not found"}

    @replicated
    def store_cart(self, buyer_id, cart_items):
        # cart_items: list of [category, item_id, quantity]
        self._carts[buyer_id] = cart_items
        return {"status": "success"}

    @replicated
    def clear_cart(self, buyer_id):
        self._carts.pop(buyer_id, None)
        return {"status": "success"}

    @replicated
    def add_item_feedback(self, category, item_id, feedback_type):
        key = (category, item_id)
        if key not in self._items:
            return {"status": "error", "message": "Item not found"}
        item = self._items[key]
        seller_id = item["seller_id"]
        if feedback_type == "thumbs_up":
            item["thumbs_up"] += 1
            if seller_id in self._seller_feedback:
                self._seller_feedback[seller_id]["thumbs_up"] += 1
        else:
            item["thumbs_down"] += 1
            if seller_id in self._seller_feedback:
                self._seller_feedback[seller_id]["thumbs_down"] += 1
        return {"status": "success"}

    @replicated
    def make_purchase(self, buyer_id, category, item_id, quantity, timestamp):
        key = (category, item_id)
        if key not in self._items:
            return {"status": "error", "message": "Item not found"}
        if self._items[key]["quantity"] < quantity:
            return {"status": "error", "message": "Not enough stock"}
        self._items[key]["quantity"] -= quantity
        self._purchases.append({
            "buyer_id": buyer_id,
            "category": category,
            "item_id": item_id,
            "quantity": quantity,
            "timestamp": timestamp,
        })
        return {"status": "success"}

    # --- Read operations (local state, no Raft) ---

    def get_item(self, category, item_id):
        return self._items.get((category, item_id))

    def get_seller_items(self, seller_id):
        results = []
        for (cat, iid), item in self._items.items():
            if item["seller_id"] == seller_id:
                results.append((cat, iid, item))
        return results

    def search_items(self, category, has_category, keywords):
        results = []
        for (cat, iid), item in self._items.items():
            if item["quantity"] <= 0:
                continue
            if has_category and cat != category:
                continue
            if keywords:
                item_kw_lower = [k.lower() for k in item["keywords"]]
                if not any(k.lower() in item_kw_lower for k in keywords):
                    continue
            results.append((cat, iid, item))
        return results

    def get_cart(self, buyer_id):
        return self._carts.get(buyer_id, [])

    def get_seller_rating(self, seller_id):
        return self._seller_feedback.get(seller_id, {"thumbs_up": 0, "thumbs_down": 0})

    def get_buyer_purchases(self, buyer_id):
        return [p for p in self._purchases if p["buyer_id"] == buyer_id]


# ---------------------------------------------------------------------------
# gRPC servicer wrapping the Raft node
# ---------------------------------------------------------------------------

def _item_dict_to_proto(category, item_id, item):
    """Convert an in-memory item dict to a protobuf ItemData."""
    return product_db_pb2.ItemData(
        item_id=product_db_pb2.ItemId(category=category, item_id=item_id),
        seller_id=item["seller_id"],
        name=item["name"],
        category=category,
        keywords=item["keywords"],
        condition=item["condition"],
        price=item["price"],
        quantity=item["quantity"],
        thumbs_up=item["thumbs_up"],
        thumbs_down=item["thumbs_down"],
    )


class ReplicatedProductDBServicer(product_db_pb2_grpc.ProductDBServicer):

    def __init__(self, raft_node: RaftProductDB):
        self.raft = raft_node

    def _wait_ready(self, timeout=10):
        """Wait until the Raft cluster has a leader."""
        start = time.time()
        while time.time() - start < timeout:
            if self.raft._getLeader() is not None:
                return True
            time.sleep(0.1)
        return False

    def _is_leader(self):
        leader = self.raft._getLeader()
        return leader is not None and leader == self.raft.selfNode

    # --- Write operations (go through Raft) ---

    def RegisterItem(self, request, context):
        if not self._wait_ready():
            return product_db_pb2.RegisterItemResponse(
                status='error', message='Cluster not ready', item_id=product_db_pb2.ItemId()
            )
        result = self.raft.register_item(
            request.seller_id, request.name, request.category,
            list(request.keywords), request.condition,
            float(request.price), request.quantity,
            sync=True, timeout=10,
        )
        if result is None:
            return product_db_pb2.RegisterItemResponse(
                status='error', message='Raft replication failed',
                item_id=product_db_pb2.ItemId()
            )
        return product_db_pb2.RegisterItemResponse(
            status=result["status"], message='',
            item_id=product_db_pb2.ItemId(
                category=result["category"], item_id=result["item_id"]
            )
        )

    def UpdateItemPrice(self, request, context):
        if not self._wait_ready():
            return product_db_pb2.StatusResponse(status='error', message='Cluster not ready')
        result = self.raft.update_item_price(
            request.item_id.category, request.item_id.item_id,
            float(request.price),
            sync=True, timeout=10,
        )
        if result is None:
            return product_db_pb2.StatusResponse(status='error', message='Raft replication failed')
        return product_db_pb2.StatusResponse(status=result["status"], message=result.get("message", ""))

    def UpdateItemQuantity(self, request, context):
        if not self._wait_ready():
            return product_db_pb2.StatusResponse(status='error', message='Cluster not ready')
        result = self.raft.update_item_quantity(
            request.item_id.category, request.item_id.item_id,
            request.quantity,
            sync=True, timeout=10,
        )
        if result is None:
            return product_db_pb2.StatusResponse(status='error', message='Raft replication failed')
        return product_db_pb2.StatusResponse(status=result["status"], message=result.get("message", ""))

    def StoreCart(self, request, context):
        if not self._wait_ready():
            return product_db_pb2.StatusResponse(status='error', message='Cluster not ready')
        cart_items = [
            [ci.item_id.category, ci.item_id.item_id, ci.quantity]
            for ci in request.cart
        ]
        result = self.raft.store_cart(
            request.buyer_id, cart_items,
            sync=True, timeout=10,
        )
        if result is None:
            return product_db_pb2.StatusResponse(status='error', message='Raft replication failed')
        return product_db_pb2.StatusResponse(status=result["status"], message="")

    def ClearCart(self, request, context):
        if not self._wait_ready():
            return product_db_pb2.StatusResponse(status='error', message='Cluster not ready')
        result = self.raft.clear_cart(
            request.buyer_id,
            sync=True, timeout=10,
        )
        if result is None:
            return product_db_pb2.StatusResponse(status='error', message='Raft replication failed')
        return product_db_pb2.StatusResponse(status=result["status"], message="")

    def AddItemFeedback(self, request, context):
        if not self._wait_ready():
            return product_db_pb2.StatusResponse(status='error', message='Cluster not ready')
        result = self.raft.add_item_feedback(
            request.item_id.category, request.item_id.item_id,
            request.feedback_type,
            sync=True, timeout=10,
        )
        if result is None:
            return product_db_pb2.StatusResponse(status='error', message='Raft replication failed')
        return product_db_pb2.StatusResponse(status=result["status"], message=result.get("message", ""))

    def MakePurchase(self, request, context):
        if not self._wait_ready():
            return product_db_pb2.StatusResponse(status='error', message='Cluster not ready')
        timestamp = datetime.utcnow().isoformat()
        result = self.raft.make_purchase(
            request.buyer_id,
            request.item_id.category, request.item_id.item_id,
            request.quantity, timestamp,
            sync=True, timeout=10,
        )
        if result is None:
            return product_db_pb2.StatusResponse(status='error', message='Raft replication failed')
        return product_db_pb2.StatusResponse(status=result["status"], message=result.get("message", ""))

    # --- Read operations (local state) ---

    def GetItem(self, request, context):
        item = self.raft.get_item(request.item_id.category, request.item_id.item_id)
        if item is None:
            return product_db_pb2.GetItemResponse(status='error', message='Item not found')
        return product_db_pb2.GetItemResponse(
            status='success', message='',
            item=_item_dict_to_proto(request.item_id.category, request.item_id.item_id, item)
        )

    def GetSellerItems(self, request, context):
        results = self.raft.get_seller_items(request.seller_id)
        items = [_item_dict_to_proto(cat, iid, item) for cat, iid, item in results]
        return product_db_pb2.GetItemsResponse(status='success', message='', items=items)

    def SearchItems(self, request, context):
        results = self.raft.search_items(
            request.category, request.has_category, list(request.keywords)
        )
        items = [_item_dict_to_proto(cat, iid, item) for cat, iid, item in results]
        return product_db_pb2.GetItemsResponse(status='success', message='', items=items)

    def GetCart(self, request, context):
        cart_items = self.raft.get_cart(request.buyer_id)
        cart = [
            product_db_pb2.CartItem(
                item_id=product_db_pb2.ItemId(category=ci[0], item_id=ci[1]),
                quantity=ci[2]
            )
            for ci in cart_items
        ]
        return product_db_pb2.GetCartResponse(status='success', message='', cart=cart)

    def GetSellerRating(self, request, context):
        rating = self.raft.get_seller_rating(request.seller_id)
        return product_db_pb2.GetSellerRatingResponse(
            status='success', message='',
            thumbs_up=rating["thumbs_up"], thumbs_down=rating["thumbs_down"]
        )

    def GetBuyerPurchases(self, request, context):
        purchases = self.raft.get_buyer_purchases(request.buyer_id)
        records = [
            product_db_pb2.PurchaseRecord(
                item_id=product_db_pb2.ItemId(category=p["category"], item_id=p["item_id"]),
                quantity=p["quantity"],
                timestamp=p["timestamp"],
            )
            for p in purchases
        ]
        return product_db_pb2.GetBuyerPurchasesResponse(
            status='success', message='', purchases=records
        )


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def serve(raft_addr, raft_partners, grpc_host='0.0.0.0', grpc_port=50052):
    conf = SyncObjConf(
        autoTick=True,
        appendEntriesUseBatch=True,
        dynamicMembershipChange=False,
        commandsWaitLeader=True,       # writes on followers auto-forward to leader
        connectionTimeout=5.0,
        raftMinTimeout=0.4,
        raftMaxTimeout=1.4,
    )

    raft_node = RaftProductDB(raft_addr, raft_partners, conf)

    servicer = ReplicatedProductDBServicer(raft_node)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    product_db_pb2_grpc.add_ProductDBServicer_to_server(servicer, server)
    server.add_insecure_port(f'{grpc_host}:{grpc_port}')
    server.start()

    logger.info(
        "Replicated Product DB | Raft %s | Partners %s | gRPC %s:%d",
        raft_addr, raft_partners, grpc_host, grpc_port,
    )

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop(0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Replicated Product Database (Raft)')
    parser.add_argument('--raft-addr', type=str, required=True,
                        help='This node Raft address (host:port)')
    parser.add_argument('--raft-partners', type=str, required=True,
                        help='Comma-separated Raft addresses of partner nodes')
    parser.add_argument('--grpc-host', default='0.0.0.0')
    parser.add_argument('--grpc-port', type=int, default=50052)
    args = parser.parse_args()

    partners = [p.strip() for p in args.raft_partners.split(",")]
    serve(args.raft_addr, partners, args.grpc_host, args.grpc_port)
