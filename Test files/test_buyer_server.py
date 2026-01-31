import socket
import json

def send_request(api, session_id=None, payload=None):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('localhost', 5004))
    
    request = {
        'api': api,
        'session_id': session_id,
        'payload': payload or {}
    }
    sock.send(json.dumps(request).encode('utf-8'))
    
    response = sock.recv(4096).decode('utf-8')
    print(f"{api} Response:", response)
    
    sock.close()
    return json.loads(response)

if __name__ == '__main__':
    # Create account
    send_request('CreateAccount', payload={
        'username': 'buyer1',
        'password': 'pass123',
        'name': 'Alice Buyer'
    })
    
    # Login
    login_result = send_request('Login', payload={
        'username': 'buyer1',
        'password': 'pass123'
    })
    
    session_id = login_result['data']['session_id']
    print(f"Session ID: {session_id}")
    
    # Search items
    send_request('SearchItemsForSale', session_id=session_id, payload={
        'category': 2,
        'keywords': ['phone']
    })
    
    # Add to cart (use item_id from previous seller test)
    send_request('AddItemToCart', session_id=session_id, payload={
        'item_id': [2, 1],
        'quantity': 2
    })
    
    # Display cart
    send_request('DisplayCart', session_id=session_id)