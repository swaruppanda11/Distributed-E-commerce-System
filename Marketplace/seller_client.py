import socket
import json
import argparse

# Default configuration (can be overridden via command line)
SERVER_HOST = 'localhost'
SERVER_PORT = 5003

session_id = None
seller_id = None

def send_request(api, payload=None):
    """Send request to seller server"""
    global session_id, seller_id

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_HOST, SERVER_PORT))

    request = {
        'api': api,
        'session_id': session_id,
        'payload': payload or {}
    }
    sock.send(json.dumps(request).encode('utf-8'))

    response = sock.recv(4096).decode('utf-8')
    sock.close()

    result = json.loads(response)

    # Auto-logout if session expired
    if result.get('status') == 'error' and 'expired' in result.get('message', '').lower():
        print("\n⚠ Session expired. You have been logged out automatically.")
        session_id = None
        seller_id = None

    return result

def create_account():
    print("\n=== Create Seller Account ===")
    username = input("Username: ")
    password = input("Password: ")
    name = input("Name: ")
    
    result = send_request('CreateAccount', {
        'username': username,
        'password': password,
        'name': name
    })
    
    if result['status'] == 'success':
        print(f"✓ Account created! Your seller ID is: {result['data']['user_id']}")
    else:
        print(f"✗ Error: {result['message']}")

def login():
    global session_id, seller_id
    print("\n=== Seller Login ===")
    username = input("Username: ")
    password = input("Password: ")
    
    result = send_request('Login', {
        'username': username,
        'password': password
    })
    
    if result['status'] == 'success':
        session_id = result['data']['session_id']
        seller_id = result['data']['seller_id']
        print(f"✓ Logged in successfully!")
        print(f"  Seller ID: {seller_id}")
        print(f"  Session ID: {session_id}")
    else:
        print(f"✗ Error: {result['message']}")

def logout():
    global session_id, seller_id
    result = send_request('Logout')

    # Clear local state regardless of server response
    session_id = None
    seller_id = None

    if result['status'] == 'success':
        print("✓ Logged out successfully!")
    else:
        print("✓ Logged out locally (session was already expired)")

def get_seller_rating():
    result = send_request('GetSellerRating')
    
    if result['status'] == 'success':
        rating = result['data']
        print(f"\nYour rating: 👍 {rating['thumbs_up']} | 👎 {rating['thumbs_down']}")
    else:
        print(f"✗ Error: {result['message']}")

def register_item():
    print("\n=== Register Item for Sale ===")
    name = input("Item name: ")
    category = int(input("Category (integer): "))
    keywords = input("Keywords (comma-separated, max 5): ").split(',')
    keywords = [kw.strip() for kw in keywords[:5]]
    condition = input("Condition (New/Used): ")
    price = float(input("Price: "))
    quantity = int(input("Quantity: "))
    
    result = send_request('RegisterItemForSale', {
        'name': name,
        'category': category,
        'keywords': keywords,
        'condition': condition,
        'price': price,
        'quantity': quantity
    })
    
    if result['status'] == 'success':
        print(f"✓ Item registered! Item ID: {result['data']['item_id']}")
    else:
        print(f"✗ Error: {result['message']}")

def change_item_price():
    print("\n=== Change Item Price ===")
    item_id_str = input("Item ID (format: [category, id]): ")
    item_id = json.loads(item_id_str)
    new_price = float(input("New price: "))
    
    result = send_request('ChangeItemPrice', {
        'item_id': item_id,
        'price': new_price
    })
    
    if result['status'] == 'success':
        print("✓ Price updated successfully!")
    else:
        print(f"✗ Error: {result['message']}")

def update_units():
    print("\n=== Update Units for Sale ===")
    item_id_str = input("Item ID (format: [category, id]): ")
    item_id = json.loads(item_id_str)
    new_quantity = int(input("New quantity: "))
    
    result = send_request('UpdateUnitsForSale', {
        'item_id': item_id,
        'quantity': new_quantity
    })
    
    if result['status'] == 'success':
        print("✓ Quantity updated successfully!")
    else:
        print(f"✗ Error: {result['message']}")

def display_items():
    result = send_request('DisplayItemsForSale')
    
    if result['status'] == 'success':
        items = result['data']
        if not items:
            print("\nNo items for sale yet.")
        else:
            print("\n=== Your Items for Sale ===")
            for item in items:
                print(f"\nItem ID: {item['item_id']}")
                print(f"  Name: {item['name']}")
                print(f"  Category: {item['category']}")
                print(f"  Condition: {item['condition']}")
                print(f"  Price: ${item['price']}")
                print(f"  Quantity: {item['quantity']}")
                print(f"  Feedback: 👍 {item['feedback']['thumbs_up']} | 👎 {item['feedback']['thumbs_down']}")
    else:
        print(f"✗ Error: {result['message']}")

def main():
    global session_id
    
    print("=" * 50)
    print("    MARKETPLACE - SELLER CLIENT")
    print("=" * 50)
    
    while True:
        print("\n" + "=" * 50)
        if session_id:
            print(f"Logged in as Seller ID: {seller_id}")
            print("=" * 50)
            print("1. Logout")
            print("2. Get My Rating")
            print("3. Register Item for Sale")
            print("4. Change Item Price")
            print("5. Update Units for Sale")
            print("6. Display My Items")
            print("0. Exit")
        else:
            print("Not logged in")
            print("=" * 50)
            print("1. Create Account")
            print("2. Login")
            print("0. Exit")
        
        choice = input("\nEnter choice: ").strip()
        
        if choice == '0':
            print("Goodbye!")
            break
        elif not session_id:
            if choice == '1':
                create_account()
            elif choice == '2':
                login()
            else:
                print("Invalid choice!")
        else:
            if choice == '1':
                logout()
            elif choice == '2':
                get_seller_rating()
            elif choice == '3':
                register_item()
            elif choice == '4':
                change_item_price()
            elif choice == '5':
                update_units()
            elif choice == '6':
                display_items()
            else:
                print("Invalid choice!")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Seller Client')
    parser.add_argument('--host', default='localhost', help='Seller server host')
    parser.add_argument('--port', type=int, default=5003, help='Seller server port')
    args = parser.parse_args()

    SERVER_HOST = args.host
    SERVER_PORT = args.port

    main()