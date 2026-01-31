import socket
import json

def send_request(api, session_id=None, payload=None):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('localhost', 5003))
    
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
    result = send_request('CreateAccount', payload={
        'username': 'seller1',
        'password': 'pass123',
        'name': 'John Seller'
    })
    
    # Login
    login_result = send_request('Login', payload={
        'username': 'seller1',
        'password': 'pass123'
    })
    
    session_id = login_result['data']['session_id']
    print(f"Session ID: {session_id}")
    
    # Register item
    send_request('RegisterItemForSale', session_id=session_id, payload={
        'name': 'iPhone 13',
        'category': 2,
        'keywords': ['phone', 'apple'],
        'condition': 'New',
        'price': 799.99,
        'quantity': 10
    })
    
    # Display items
    send_request('DisplayItemsForSale', session_id=session_id)