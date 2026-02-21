import grpc
import argparse
from flask import Flask, request, jsonify
import zeep

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import customer_db_pb2
import customer_db_pb2_grpc
import product_db_pb2
import product_db_pb2_grpc

app = Flask(__name__)

_customer_stub = None
_product_stub = None
_financial_client = None


def validate_session(req):
    session_id = req.headers.get('X-Session-ID', '')
    if not session_id:
        return None, ('Missing session', 401)
    resp = _customer_stub.GetSession(customer_db_pb2.GetSessionRequest(session_id=session_id))
    if resp.status != 'success':
        return None, (resp.message, 401)
    _customer_stub.UpdateSessionActivity(customer_db_pb2.SessionRequest(session_id=session_id))
    return resp, None


def _item_to_dict(item):
    return {
        'item_id': [item.item_id.category, item.item_id.item_id],
        'seller_id': item.seller_id,
        'name': item.name,
        'category': item.category,
        'keywords': list(item.keywords),
        'condition': item.condition,
        'price': item.price,
        'quantity': item.quantity,
        'thumbs_up': item.thumbs_up,
        'thumbs_down': item.thumbs_down
    }


@app.route('/buyer/account', methods=['POST'])
def create_account():
    data = request.json
    resp = _customer_stub.StoreUser(customer_db_pb2.StoreUserRequest(
        username=data['username'],
        password=data['password'],
        name=data['name'],
        user_type='buyer'
    ))
    if resp.status != 'success':
        return jsonify({'status': 'error', 'message': resp.message}), 400
    return jsonify({'status': 'success', 'user_id': resp.user_id})


@app.route('/buyer/login', methods=['POST'])
def login():
    data = request.json
    user_resp = _customer_stub.GetUser(customer_db_pb2.GetUserRequest(username=data['username']))
    if user_resp.status != 'success':
        return jsonify({'status': 'error', 'message': 'User not found'}), 401
    if user_resp.password != data['password']:
        return jsonify({'status': 'error', 'message': 'Invalid password'}), 401
    if user_resp.user_type != 'buyer':
        return jsonify({'status': 'error', 'message': 'Not a buyer account'}), 401
    sess_resp = _customer_stub.StoreSession(customer_db_pb2.StoreSessionRequest(
        user_id=user_resp.user_id, user_type='buyer'
    ))
    return jsonify({
        'status': 'success',
        'session_id': sess_resp.session_id,
        'buyer_id': user_resp.user_id
    })


@app.route('/buyer/logout', methods=['POST'])
def logout():
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    session_id = request.headers.get('X-Session-ID')
    _customer_stub.DeleteSession(customer_db_pb2.SessionRequest(session_id=session_id))
    return jsonify({'status': 'success'})


@app.route('/buyer/items', methods=['GET'])
def search_items():
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    category_str = request.args.get('category', '')
    keywords_str = request.args.get('keywords', '')
    has_category = bool(category_str)
    category = int(category_str) if has_category else 0
    keywords = [k.strip() for k in keywords_str.split(',') if k.strip()] if keywords_str else []
    resp = _product_stub.SearchItems(product_db_pb2.SearchItemsRequest(
        category=category,
        has_category=has_category,
        keywords=keywords
    ))
    items = [_item_to_dict(item) for item in resp.items]
    return jsonify({'status': 'success', 'items': items})


@app.route('/buyer/items/<int:cat>/<int:iid>', methods=['GET'])
def get_item(cat, iid):
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    item_id = product_db_pb2.ItemId(category=cat, item_id=iid)
    resp = _product_stub.GetItem(product_db_pb2.ItemIdRequest(item_id=item_id))
    if resp.status != 'success':
        return jsonify({'status': 'error', 'message': resp.message}), 404
    return jsonify({'status': 'success', 'item': _item_to_dict(resp.item)})


@app.route('/buyer/cart/validate', methods=['POST'])
def validate_cart_item():
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    data = request.json
    cat, iid = data['item_id']
    item_id = product_db_pb2.ItemId(category=cat, item_id=iid)
    resp = _product_stub.GetItem(product_db_pb2.ItemIdRequest(item_id=item_id))
    if resp.status != 'success':
        return jsonify({'status': 'error', 'message': 'Item not found'}), 404
    if resp.item.quantity < data['quantity']:
        return jsonify({'status': 'error', 'message': 'Not enough stock'}), 400
    return jsonify({'status': 'success'})


@app.route('/buyer/cart', methods=['PUT'])
def save_cart():
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    buyer_id = session_resp.user_id
    data = request.json
    cart_items = []
    for ci in data.get('cart', []):
        cat, iid = ci['item_id']
        cart_items.append(product_db_pb2.CartItem(
            item_id=product_db_pb2.ItemId(category=cat, item_id=iid),
            quantity=ci['quantity']
        ))
    _product_stub.StoreCart(product_db_pb2.StoreCartRequest(buyer_id=buyer_id, cart=cart_items))
    return jsonify({'status': 'success'})


@app.route('/buyer/cart', methods=['GET'])
def get_cart():
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    buyer_id = session_resp.user_id
    resp = _product_stub.GetCart(product_db_pb2.BuyerIdRequest(buyer_id=buyer_id))
    cart = [
        {'item_id': [ci.item_id.category, ci.item_id.item_id], 'quantity': ci.quantity}
        for ci in resp.cart
    ]
    return jsonify({'status': 'success', 'cart': cart})


@app.route('/buyer/cart', methods=['DELETE'])
def clear_cart():
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    buyer_id = session_resp.user_id
    _product_stub.ClearCart(product_db_pb2.BuyerIdRequest(buyer_id=buyer_id))
    return jsonify({'status': 'success'})


@app.route('/buyer/feedback', methods=['POST'])
def provide_feedback():
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    data = request.json
    cat, iid = data['item_id']
    item_id = product_db_pb2.ItemId(category=cat, item_id=iid)
    resp = _product_stub.AddItemFeedback(product_db_pb2.AddItemFeedbackRequest(
        item_id=item_id,
        feedback_type=data['feedback_type']
    ))
    if resp.status != 'success':
        return jsonify({'status': 'error', 'message': resp.message}), 400
    return jsonify({'status': 'success'})


@app.route('/buyer/seller/<int:seller_id>/rating', methods=['GET'])
def get_seller_rating(seller_id):
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    resp = _product_stub.GetSellerRating(product_db_pb2.GetSellerRatingRequest(seller_id=seller_id))
    return jsonify({'status': 'success', 'thumbs_up': resp.thumbs_up, 'thumbs_down': resp.thumbs_down})


@app.route('/buyer/purchase', methods=['POST'])
def make_purchase():
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    buyer_id = session_resp.user_id
    data = request.json
    approved = _financial_client.service.ProcessPayment(
        data['name'],
        data['card_number'],
        data['expiration_date'],
        data['security_code']
    )
    if not approved:
        return jsonify({'status': 'error', 'message': 'Payment declined'}), 402
    cat, iid = data['item_id']
    item_id = product_db_pb2.ItemId(category=cat, item_id=iid)
    resp = _product_stub.MakePurchase(product_db_pb2.MakePurchaseRequest(
        buyer_id=buyer_id,
        item_id=item_id,
        quantity=data['quantity']
    ))
    if resp.status != 'success':
        return jsonify({'status': 'error', 'message': resp.message}), 400
    return jsonify({'status': 'success'})


@app.route('/buyer/purchases', methods=['GET'])
def get_purchases():
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    buyer_id = session_resp.user_id
    resp = _product_stub.GetBuyerPurchases(product_db_pb2.BuyerIdRequest(buyer_id=buyer_id))
    purchases = [
        {
            'item_id': [p.item_id.category, p.item_id.item_id],
            'quantity': p.quantity,
            'timestamp': p.timestamp
        }
        for p in resp.purchases
    ]
    return jsonify({'status': 'success', 'purchases': purchases})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Buyer REST Server')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=5004)
    parser.add_argument('--customer-db-host', default='localhost')
    parser.add_argument('--customer-db-port', type=int, default=50051)
    parser.add_argument('--product-db-host', default='localhost')
    parser.add_argument('--product-db-port', type=int, default=50052)
    parser.add_argument('--financial-host', default='localhost')
    parser.add_argument('--financial-port', type=int, default=8000)
    args = parser.parse_args()

    _customer_stub = customer_db_pb2_grpc.CustomerDBStub(
        grpc.insecure_channel(f'{args.customer_db_host}:{args.customer_db_port}')
    )
    _product_stub = product_db_pb2_grpc.ProductDBStub(
        grpc.insecure_channel(f'{args.product_db_host}:{args.product_db_port}')
    )
    wsdl = f'http://{args.financial_host}:{args.financial_port}/?wsdl'
    _financial_client = zeep.Client(wsdl=wsdl)

    print(f'Buyer REST server on {args.host}:{args.port}')
    app.run(host=args.host, port=args.port)
