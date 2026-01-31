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
                
                seller_id = session_response['data']['user_id']
                
                if api == 'Logout':
                    response = logout(session_id)
                elif api == 'GetSellerRating':
                    response = get_seller_rating(seller_id)
                elif api == 'RegisterItemForSale':
                    response = register_item_for_sale(seller_id, payload)
                elif api == 'ChangeItemPrice':
                    response = change_item_price(payload)
                elif api == 'UpdateUnitsForSale':
                    response = update_units_for_sale(payload)
                elif api == 'DisplayItemsForSale':
                    response = display_items_for_sale(seller_id)
                else:
                    response = {'status': 'error', 'message': 'Unknown API'}
        
        client_socket.send(json.dumps(response).encode('utf-8'))
    except Exception as e:
        error_response = {'status': 'error', 'message': str(e)}
        client_socket.send(json.dumps(error_response).encode('utf-8'))
    finally:
        client_socket.close()

def create_account(payload):
    # Store user in customer database
    user_data = {
        'username': payload['username'],
        'password': payload['password'],
        'name': payload['name'],
        'user_type': 'seller'
    }
    response = send_to_db(CUSTOMER_DB_HOST, CUSTOMER_DB_PORT, 'store_user', user_data)
    return response

def login(payload):
    # Get user from database
    user_response = send_to_db(CUSTOMER_DB_HOST, CUSTOMER_DB_PORT, 'get_user', {'username': payload['username']})
    
    if user_response['status'] != 'success':
        return {'status': 'error', 'message': 'User not found'}
    
    user = user_response['data']
    
    # Check password
    if user['password'] != payload['password']:
        return {'status': 'error', 'message': 'Invalid password'}
    
    # Check user type
    if user['user_type'] != 'seller':
        return {'status': 'error', 'message': 'Not a seller account'}
    
    # Create session
    session_data = {
        'user_id': user['user_id'],
        'user_type': 'seller'
    }
    session_response = send_to_db(CUSTOMER_DB_HOST, CUSTOMER_DB_PORT, 'store_session', session_data)
    
    if session_response['status'] == 'success':
        return {
            'status': 'success',
            'data': {
                'session_id': session_response['data']['session_id'],
                'seller_id': user['user_id']
            }
        }
    return session_response

def logout(session_id):
    response = send_to_db(CUSTOMER_DB_HOST, CUSTOMER_DB_PORT, 'delete_session', {'session_id': session_id})
    return response

def get_seller_rating(seller_id):
    response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'get_seller_rating', {'seller_id': seller_id})
    return response

def register_item_for_sale(seller_id, payload):
    item_data = {
        'seller_id': seller_id,
        'name': payload['name'],
        'category': payload['category'],
        'keywords': payload.get('keywords', []),
        'condition': payload['condition'],
        'price': payload['price'],
        'quantity': payload['quantity']
    }
    response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'register_item', item_data)
    return response

def change_item_price(payload):
    response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'update_item_price', {
        'item_id': payload['item_id'],
        'price': payload['price']
    })
    return response

def update_units_for_sale(payload):
    response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'update_item_quantity', {
        'item_id': payload['item_id'],
        'quantity': payload['quantity']
    })
    return response

def display_items_for_sale(seller_id):
    response = send_to_db(PRODUCT_DB_HOST, PRODUCT_DB_PORT, 'get_seller_items', {'seller_id': seller_id})
    return response

def start_server(host='localhost', port=5003):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(5)
    
    print(f"Seller Server listening on {host}:{port}")
    
    while True:
        client_socket, addr = server_socket.accept()
        print(f"Connection from {addr}")
        
        client_thread = threading.Thread(target=handle_client, args=(client_socket,))
        client_thread.start()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Seller Server')
    parser.add_argument('--host', default='localhost', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5003, help='Port to bind to')
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