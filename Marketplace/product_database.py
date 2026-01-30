import socket
import json
import threading
import time

# Data storage
items = {}  # item_id -> {item details}
item_counter = 1
seller_feedback = {}  # seller_id -> {thumbs_up, thumbs_down}
item_feedback = {}  # item_id -> {thumbs_up, thumbs_down}
carts = {}  # buyer_id -> [{item_id, quantity}, ...]

def handle_client(client_socket):
    try:
        data = client_socket.recv(4096).decode('utf-8')
        request = json.loads(data)
        operation = request.get('operation')
        
        if operation == 'register_item':
            response = register_item(request['data'])
        elif operation == 'get_item':
            response = get_item(request['data'])
        elif operation == 'update_item_price':
            response = update_item_price(request['data'])
        elif operation == 'update_item_quantity':
            response = update_item_quantity(request['data'])
        elif operation == 'get_seller_items':
            response = get_seller_items(request['data'])
        elif operation == 'search_items':
            response = search_items(request['data'])
        elif operation == 'store_cart':
            response = store_cart(request['data'])
        elif operation == 'get_cart':
            response = get_cart(request['data'])
        elif operation == 'clear_cart':
            response = clear_cart(request['data'])
        elif operation == 'add_item_feedback':
            response = add_item_feedback(request['data'])
        elif operation == 'get_seller_rating':
            response = get_seller_rating(request['data'])
        else:
            response = {'status': 'error', 'message': 'Invalid operation'}
        
        client_socket.send(json.dumps(response).encode('utf-8'))
    except Exception as e:
        error_response = {'status': 'error', 'message': str(e)}
        client_socket.send(json.dumps(error_response).encode('utf-8'))
    finally:
        client_socket.close()

def register_item(data):
    global item_counter
    item_id = (data['category'], item_counter)
    item_counter += 1
    
    items[item_id] = {
        'item_id': item_id,
        'seller_id': data['seller_id'],
        'name': data['name'],
        'category': data['category'],
        'keywords': data.get('keywords', []),
        'condition': data['condition'],
        'price': data['price'],
        'quantity': data['quantity']
    }
    
    # Initialize item feedback
    item_feedback[item_id] = {'thumbs_up': 0, 'thumbs_down': 0}
    
    # Initialize seller feedback if needed
    if data['seller_id'] not in seller_feedback:
        seller_feedback[data['seller_id']] = {'thumbs_up': 0, 'thumbs_down': 0}
    
    return {'status': 'success', 'data': {'item_id': list(item_id)}}

def get_item(data):
    item_id = tuple(data['item_id'])
    if item_id in items:
        item = items[item_id].copy()
        item['item_id'] = list(item['item_id'])
        item['feedback'] = item_feedback.get(item_id, {'thumbs_up': 0, 'thumbs_down': 0})
        return {'status': 'success', 'data': item}
    return {'status': 'error', 'message': 'Item not found'}

def update_item_price(data):
    item_id = tuple(data['item_id'])
    if item_id in items:
        items[item_id]['price'] = data['price']
        return {'status': 'success'}
    return {'status': 'error', 'message': 'Item not found'}

def update_item_quantity(data):
    item_id = tuple(data['item_id'])
    if item_id in items:
        items[item_id]['quantity'] = data['quantity']
        return {'status': 'success'}
    return {'status': 'error', 'message': 'Item not found'}

def get_seller_items(data):
    seller_id = data['seller_id']
    seller_items = []
    for item_id, item in items.items():
        if item['seller_id'] == seller_id:
            item_copy = item.copy()
            item_copy['item_id'] = list(item_copy['item_id'])
            item_copy['feedback'] = item_feedback.get(item_id, {'thumbs_up': 0, 'thumbs_down': 0})
            seller_items.append(item_copy)
    return {'status': 'success', 'data': seller_items}

def search_items(data):
    category = data.get('category')
    keywords = data.get('keywords', [])
    
    results = []
    for item_id, item in items.items():
        if item['quantity'] <= 0:
            continue
        
        if category is not None and item['category'] != category:
            continue
        
        if keywords:
            keyword_match = False
            for kw in keywords:
                if kw.lower() in [k.lower() for k in item['keywords']]:
                    keyword_match = True
                    break
            if not keyword_match:
                continue
        
        item_copy = item.copy()
        item_copy['item_id'] = list(item_copy['item_id'])
        item_copy['feedback'] = item_feedback.get(item_id, {'thumbs_up': 0, 'thumbs_down': 0})
        results.append(item_copy)
    
    return {'status': 'success', 'data': results}

def store_cart(data):
    buyer_id = data['buyer_id']
    cart = data['cart']
    carts[buyer_id] = cart
    return {'status': 'success'}

def get_cart(data):
    buyer_id = data['buyer_id']
    cart = carts.get(buyer_id, [])
    return {'status': 'success', 'data': cart}

def clear_cart(data):
    buyer_id = data['buyer_id']
    if buyer_id in carts:
        del carts[buyer_id]
    return {'status': 'success'}

def add_item_feedback(data):
    item_id = tuple(data['item_id'])
    feedback_type = data['feedback_type']
    
    if item_id not in items:
        return {'status': 'error', 'message': 'Item not found'}
    
    if item_id not in item_feedback:
        item_feedback[item_id] = {'thumbs_up': 0, 'thumbs_down': 0}
    item_feedback[item_id][feedback_type] += 1
    
    seller_id = items[item_id]['seller_id']
    if seller_id not in seller_feedback:
        seller_feedback[seller_id] = {'thumbs_up': 0, 'thumbs_down': 0}
    seller_feedback[seller_id][feedback_type] += 1
    
    return {'status': 'success'}

def get_seller_rating(data):
    seller_id = data['seller_id']
    rating = seller_feedback.get(seller_id, {'thumbs_up': 0, 'thumbs_down': 0})
    return {'status': 'success', 'data': rating}

def start_server(host='localhost', port=5002):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(5)
    
    print(f"Product Database listening on {host}:{port}")
    
    while True:
        client_socket, addr = server_socket.accept()
        print(f"Connection from {addr}")
        
        client_thread = threading.Thread(target=handle_client, args=(client_socket,))
        client_thread.start()

if __name__ == '__main__':
    start_server()