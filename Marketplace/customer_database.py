import socket
import json
import threading
import time
import uuid

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
        elif operation == 'store_session':
            response = store_session(request['data'])
        elif operation == 'get_session':
            response = get_session(request['data'])
        elif operation == 'update_session_activity':
            response = update_session_activity(request['data'])
        elif operation == 'delete_session':
            response = delete_session(request['data'])
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


def store_session(data):
    # data contains: user_id, user_type
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        'session_id': session_id,
        'user_id': data['user_id'],
        'user_type': data['user_type'],
        'last_activity': time.time()
    }
    return {'status': 'success', 'data': {'session_id': session_id}}

def get_session(data):
    # data contains: session_id
    session_id = data['session_id']
    if session_id in sessions:
        session = sessions[session_id]
        # Check if session expired (5 minutes = 300 seconds)
        if time.time() - session['last_activity'] > 300:
            del sessions[session_id]
            return {'status': 'error', 'message': 'Session expired'}
        return {'status': 'success', 'data': session}
    return {'status': 'error', 'message': 'Session not found'}

def update_session_activity(data):
    # data contains: session_id
    session_id = data['session_id']
    if session_id in sessions:
        sessions[session_id]['last_activity'] = time.time()
        return {'status': 'success'}
    return {'status': 'error', 'message': 'Session not found'}

def delete_session(data):
    # data contains: session_id
    session_id = data['session_id']
    if session_id in sessions:
        del sessions[session_id]
        return {'status': 'success'}
    return {'status': 'error', 'message': 'Session not found'}


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