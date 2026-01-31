import socket
import json

def test_store_user():
    # Connect to database
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('localhost', 5001))
    
    # Send request
    request = {
        'operation': 'store_user',
        'data': {
            'username': 'alice',
            'password': 'pass123',
            'name': 'Alice Smith',
            'user_type': 'buyer'
        }
    }
    sock.send(json.dumps(request).encode('utf-8'))
    
    # Get response
    response = sock.recv(4096).decode('utf-8')
    print("Store User Response:", response)
    
    sock.close()

def test_get_user():
    # Connect to database
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('localhost', 5001))
    
    # Send request
    request = {
        'operation': 'get_user',
        'data': {
            'username': 'alice'
        }
    }
    sock.send(json.dumps(request).encode('utf-8'))
    
    # Get response
    response = sock.recv(4096).decode('utf-8')
    print("Get User Response:", response)
    
    sock.close()

if __name__ == '__main__':
    test_store_user()
    test_get_user()