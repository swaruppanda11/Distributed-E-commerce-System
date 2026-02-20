import socket
import json
import threading
import argparse

# Default configuration (can be overridden via command line)
CUSTOMER_DB_HOST = 'localhost'
CUSTOMER_DB_PORT = 5001
PRODUCT_DB_HOST = 'localhost'
PRODUCT_DB_PORT = 5002

def send_to_db(host, port, operation, data):
    """Helper function to communicate with databases"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    
    request = {'operation': operation, 'data': data}
    sock.send(json.dumps(request).encode('utf-8'))
    
    response = sock.recv(4096).decode('utf-8')
    sock.close()
    
    return json.loads(response)

def handle_client(client_socket):
    try:
        data = client_socket.recv(4096).decode('utf-8')
        request = json.loads(data)
        
        api = request.get('api')
        session_id = request.get('session_id')
        payload = request.get('payload', {})
        
        # APIs that don't require login
        if api == 'CreateAccount':
            response = create_account(payload)
        elif api == 'Login':
            response = login(payload)
        else:
            # Validate session for all other APIs
            session_response = send_to_db(CUSTOMER_DB_HOST, CUSTOMER_DB_PORT, 'get_session', {'session_id': session_id})
            if session_response['status'] != 'success':
                response = {'status': 'error', 'message': 'Invalid or expired session'}
            else:
                # Update session activity
                send_to_db(CUSTOMER_DB_HOST, CUSTOMER_DB_PORT, 'update_session_activity', {'session_id': session_id})
                
                buyer_id = session_response['data']['user_id']
                
                if api == 'Logout':
                    response = logout(session_id)
                elif api == 'SearchItemsForSale':
                    response = search_items(payload)
                elif api == 'GetItem':
                    response = get_item(payload)
                elif api == 'AddItemToCart':
                    response = add_item_to_cart(buyer_id, payload)
                elif api == 'RemoveItemFromCart':
                    response = remove_item_from_cart(buyer_id, payload)
                elif api == 'SaveCart':
                    response = save_cart(buyer_id, payload)
                elif api == 'ClearCart':
                    response = clear_cart(buyer_id)
                elif api == 'DisplayCart':
                    response = display_cart(buyer_id)
                elif api == 'ProvideFeedback':
                    response = provide_feedback(payload)
                elif api == 'GetSellerRating':
                    response = get_seller_rating(payload)
                elif api == 'GetBuyerPurchases':
                    response = get_buyer_purchases(buyer_id)
                else:
                    response = {'status': 'error', 'message': 'Unknown API'}
        
        client_socket.send(json.dumps(response).encode('utf-8'))
    except Exception as e:
        error_response = {'status': 'error', 'message': str(e)}
        client_socket.send(json.dumps(error_response).encode('utf-8'))
    finally:
        client_socket.close()

def create_account(payload):
    user_data = {
        'username': payload['username'],
        'password': payload['password'],
        'name': payload['name'],
        'user_type': 'buyer'
    }
    response = send_to_db(CUSTOMER_DB_HOST, CUSTOMER_DB_PORT, 'store_user', user_data)
    return response

def login(payload):
    user_response = send_to_db(CUSTOMER_DB_HOST, CUSTOMER_DB_PORT, 'get_user', {'username': payload['username']})
    
    if user_response['status'] != 'success':
        return {'status': 'error', 'message': 'User not found'}
    
    user = user_response['data']
    
    if user['password'] != payload['password']:
        return {'status': 'error', 'message': 'Invalid password'}
    
    if user['user_type'] != 'buyer':
        return {'status': 'error', 'message': 'Not a buyer account'}
    
    session_data = {
        'user_id': user['user_id'],
        'user_type': 'buyer'
    }
    session_response = send_to_db(CUSTOMER_DB_HOST, CUSTOMER_DB_PORT, 'store_session', session_data)
    
    if session_response['status'] == 'success':
        return {
            'status': 'success',
            'data': {
                'session_id': session_response['data']['session_id'],
                'buyer_id': user['user_id']
            }
        }
    return session_response

def logout(session_id):
    response = send_to_db(CUSTOMER_DB_HOST, CUSTOMER_DB_PORT, 'delete_session', {'session_id': session_id})
    return response

def search_items(payload):
    response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'search_items', payload)
    return response

def get_item(payload):
    response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'get_item', {'item_id': payload['item_id']})
    return response

def add_item_to_cart(_buyer_id, payload):
    # Only validate availability — cart is managed client-side until explicitly saved
    item_response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'get_item', {'item_id': payload['item_id']})
    if item_response['status'] != 'success':
        return {'status': 'error', 'message': 'Item not found'}

    item = item_response['data']
    if item['quantity'] < payload['quantity']:
        return {'status': 'error', 'message': 'Not enough items available'}

    return {'status': 'success', 'message': 'Item available'}

def remove_item_from_cart(buyer_id, payload):
    # Get current cart
    cart_response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'get_cart', {'buyer_id': buyer_id})
    cart = cart_response['data']
    
    # Remove from cart
    for i, cart_item in enumerate(cart):
        if cart_item['item_id'] == payload['item_id']:
            if cart_item['quantity'] <= payload['quantity']:
                cart.pop(i)
            else:
                cart_item['quantity'] -= payload['quantity']
            break
    
    # Save cart
    save_response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'store_cart', {'buyer_id': buyer_id, 'cart': cart})
    return save_response

def save_cart(buyer_id, payload):
    cart = payload.get('cart', [])
    response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'store_cart', {'buyer_id': buyer_id, 'cart': cart})
    return response

def clear_cart(buyer_id):
    response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'clear_cart', {'buyer_id': buyer_id})
    return response

def display_cart(buyer_id):
    response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'get_cart', {'buyer_id': buyer_id})
    return response

def provide_feedback(payload):
    response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'add_item_feedback', {
        'item_id': payload['item_id'],
        'feedback_type': payload['feedback_type']  # 'thumbs_up' or 'thumbs_down'
    })
    return response

def get_seller_rating(payload):
    response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'get_seller_rating', {'seller_id': payload['seller_id']})
    return response

def get_buyer_purchases(buyer_id):
    # For now, return empty list since we haven't implemented MakePurchase yet
    return {'status': 'success', 'data': []}

def start_server(host='localhost', port=5004):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(5)
    
    print(f"Buyer Server listening on {host}:{port}")
    
    while True:
        client_socket, addr = server_socket.accept()
        print(f"Connection from {addr}")
        
        client_thread = threading.Thread(target=handle_client, args=(client_socket,))
        client_thread.start()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Buyer Server')
    parser.add_argument('--host', default='localhost', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5004, help='Port to bind to')
    parser.add_argument('--customer-db-host', default='localhost', help='Customer DB host')
    parser.add_argument('--customer-db-port', type=int, default=5001, help='Customer DB port')
    parser.add_argument('--product-db-host', default='localhost', help='Product DB host')
    parser.add_argument('--product-db-port', type=int, default=5002, help='Product DB port')
    args = parser.parse_args()

    # Update config
    CUSTOMER_DB_HOST = args.customer_db_host
    CUSTOMER_DB_PORT = args.customer_db_port
    PRODUCT_DB_HOST = args.product_db_host
    PRODUCT_DB_PORT = args.product_db_port

    start_server(host=args.host, port=args.port)