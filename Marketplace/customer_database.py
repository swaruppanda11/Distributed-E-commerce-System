import socket
import json
import threading

users = {}
sessions = {}
carts = {}
user_counter = 1

def handle_client(client_socket):
    try:
        data = client_socket.recv(4096).decode('utf-8')
        request = json.loads(data)
        operation = request.get('operation')
        
        if operation == 'store_user':
            response = store_user(request['data'])
        elif operation == 'get_user':
            response = get_user(request['data'])
        else:
            response = {'status': 'error', 'message': 'Invalid operation'}
        
        client_socket.send(json.dumps(response).encode('utf-8'))
    except Exception as e:
        error_response = {'status': 'error', 'message': str(e)}
        client_socket.send(json.dumps(error_response).encode('utf-8'))
    finally:
        client_socket.close()

def store_user(user_data):
    global user_counter
    user_id = user_counter
    user_counter += 1
    
    users[user_id] = {
        'user_id': user_id,
        'username': user_data['username'],
        'password': user_data['password'],
        'name': user_data['name'],
        'user_type': user_data['user_type']
    }
    
    return {'status': 'success', 'data': {'user_id': user_id}}

def get_user(data):
    username = data['username']
    for uid, user_info in users.items():
        if user_info['username'] == username:
            return {'status': 'success', 'data': user_info}
    return {'status': 'error', 'message': 'User not found'}

def start_server(host='localhost', port=5001):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(5)
    
    print(f"Customer Database listening on {host}:{port}")
    
    while True:
        client_socket, addr = server_socket.accept()
        print(f"Connection from {addr}")
        
        client_thread = threading.Thread(target=handle_client, args=(client_socket,))
        client_thread.start()

if __name__ == '__main__':
    start_server()