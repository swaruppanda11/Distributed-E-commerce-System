import argparse
from flask import Flask, request, jsonify

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import customer_db_pb2
import customer_db_pb2_grpc
import product_db_pb2
import product_db_pb2_grpc
from stub_pool import StubPool

app = Flask(__name__)

_customer_pool = None   # StubPool for customer DB replicas
_product_pool = None    # StubPool for product DB replicas


def validate_session(req):
    session_id = req.headers.get('X-Session-ID', '')
    if not session_id:
        return None, ('Missing session', 401)
    resp = _customer_pool.call('GetSession', customer_db_pb2.GetSessionRequest(session_id=session_id))
    if resp.status != 'success':
        return None, (resp.message, 401)
    _customer_pool.call('UpdateSessionActivity', customer_db_pb2.SessionRequest(session_id=session_id))
    return resp, None


@app.route('/seller/account', methods=['POST'])
def create_account():
    data = request.json
    resp = _customer_pool.call('StoreUser', customer_db_pb2.StoreUserRequest(
        username=data['username'],
        password=data['password'],
        name=data['name'],
        user_type='seller'
    ))
    if resp.status != 'success':
        return jsonify({'status': 'error', 'message': resp.message}), 400
    return jsonify({'status': 'success', 'user_id': resp.user_id})


@app.route('/seller/login', methods=['POST'])
def login():
    data = request.json
    user_resp = _customer_pool.call('GetUser', customer_db_pb2.GetUserRequest(username=data['username']))
    if user_resp.status != 'success':
        return jsonify({'status': 'error', 'message': 'User not found'}), 401
    if user_resp.password != data['password']:
        return jsonify({'status': 'error', 'message': 'Invalid password'}), 401
    if user_resp.user_type != 'seller':
        return jsonify({'status': 'error', 'message': 'Not a seller account'}), 401
    sess_resp = _customer_pool.call('StoreSession', customer_db_pb2.StoreSessionRequest(
        user_id=user_resp.user_id, user_type='seller'
    ))
    return jsonify({
        'status': 'success',
        'session_id': sess_resp.session_id,
        'seller_id': user_resp.user_id
    })


@app.route('/seller/logout', methods=['POST'])
def logout():
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    session_id = request.headers.get('X-Session-ID')
    _customer_pool.call('DeleteSession', customer_db_pb2.SessionRequest(session_id=session_id))
    return jsonify({'status': 'success'})


@app.route('/seller/rating/<int:seller_id>', methods=['GET'])
def get_seller_rating(seller_id):
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    resp = _product_pool.call('GetSellerRating', product_db_pb2.GetSellerRatingRequest(seller_id=seller_id))
    return jsonify({'status': 'success', 'thumbs_up': resp.thumbs_up, 'thumbs_down': resp.thumbs_down})


@app.route('/seller/items', methods=['POST'])
def register_item():
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    seller_id = session_resp.user_id
    data = request.json
    resp = _product_pool.call('RegisterItem', product_db_pb2.RegisterItemRequest(
        seller_id=seller_id,
        name=data['name'],
        category=data['category'],
        keywords=data.get('keywords', []),
        condition=data['condition'],
        price=data['price'],
        quantity=data['quantity']
    ))
    if resp.status != 'success':
        return jsonify({'status': 'error', 'message': resp.message}), 400
    return jsonify({'status': 'success', 'item_id': [resp.item_id.category, resp.item_id.item_id]})


@app.route('/seller/items/<int:cat>/<int:iid>/price', methods=['PUT'])
def change_price(cat, iid):
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    data = request.json
    item_id = product_db_pb2.ItemId(category=cat, item_id=iid)
    _product_pool.call('UpdateItemPrice', product_db_pb2.UpdateItemPriceRequest(item_id=item_id, price=data['price']))
    return jsonify({'status': 'success'})


@app.route('/seller/items/<int:cat>/<int:iid>/quantity', methods=['PUT'])
def change_quantity(cat, iid):
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    data = request.json
    item_id = product_db_pb2.ItemId(category=cat, item_id=iid)
    _product_pool.call('UpdateItemQuantity', product_db_pb2.UpdateItemQuantityRequest(item_id=item_id, quantity=data['quantity']))
    return jsonify({'status': 'success'})


@app.route('/seller/items', methods=['GET'])
def display_items():
    session_resp, err = validate_session(request)
    if err:
        return jsonify({'status': 'error', 'message': err[0]}), err[1]
    seller_id = session_resp.user_id
    resp = _product_pool.call('GetSellerItems', product_db_pb2.GetSellerItemsRequest(seller_id=seller_id))
    items = []
    for item in resp.items:
        items.append({
            'item_id': [item.item_id.category, item.item_id.item_id],
            'name': item.name,
            'category': item.category,
            'keywords': list(item.keywords),
            'condition': item.condition,
            'price': item.price,
            'quantity': item.quantity,
            'thumbs_up': item.thumbs_up,
            'thumbs_down': item.thumbs_down
        })
    return jsonify({'status': 'success', 'items': items})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Seller REST Server')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=5003)
    parser.add_argument('--customer-db-addrs', type=str, default='localhost:50051',
                        help='Comma-separated customer DB replica addresses (host:port)')
    parser.add_argument('--product-db-addrs', type=str, default='localhost:50052',
                        help='Comma-separated product DB replica addresses (host:port)')
    args = parser.parse_args()

    customer_addrs = [a.strip() for a in args.customer_db_addrs.split(',')]
    product_addrs = [a.strip() for a in args.product_db_addrs.split(',')]

    _customer_pool = StubPool(customer_addrs, customer_db_pb2_grpc.CustomerDBStub)
    _product_pool = StubPool(product_addrs, product_db_pb2_grpc.ProductDBStub)

    print(f'Seller REST server on {args.host}:{args.port}')
    print(f'  Customer DB replicas: {customer_addrs}')
    print(f'  Product DB replicas: {product_addrs}')
    app.run(host=args.host, port=args.port)
