import socket
import json

def send_request(operation, data):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('localhost', 5002))
    
    request = {'operation': operation, 'data': data}
    sock.send(json.dumps(request).encode('utf-8'))
    
    response = sock.recv(4096).decode('utf-8')
    print(f"{operation} Response:", response)
    
    sock.close()
    return json.loads(response)

if __name__ == '__main__':
    # Test registering an item
    result = send_request('register_item', {
        'seller_id': 1,
        'name': 'Laptop',
        'category': 1,
        'keywords': ['electronics', 'computer'],
        'condition': 'New',
        'price': 999.99,
        'quantity': 5
    })
    
    # Get the item_id from the response
    item_id = result['data']['item_id']
    print(f"Created item with ID: {item_id}")
    
    # Test getting item using the returned item_id
    send_request('get_item', {'item_id': item_id})