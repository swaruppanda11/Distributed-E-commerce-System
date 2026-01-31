import socket
import json

SERVER_HOST = 'localhost'
SERVER_PORT = 5004

session_id = None
buyer_id = None

def send_request(api, payload=None):
    """Send request to buyer server"""
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
    
    return json.loads(response)

def create_account():
    print("\n=== Create Buyer Account ===")
    username = input("Username: ")
    password = input("Password: ")
    name = input("Name: ")
    
    result = send_request('CreateAccount', {
        'username': username,
        'password': password,
        'name': name
    })
    
    if result['status'] == 'success':
        print(f"✓ Account created! Your buyer ID is: {result['data']['user_id']}")
    else:
        print(f"✗ Error: {result['message']}")

def login():
    global session_id, buyer_id
    print("\n=== Buyer Login ===")
    username = input("Username: ")
    password = input("Password: ")
    
    result = send_request('Login', {
        'username': username,
        'password': password
    })
    
    if result['status'] == 'success':
        session_id = result['data']['session_id']
        buyer_id = result['data']['buyer_id']
        print(f"✓ Logged in successfully! Buyer ID: {buyer_id}")
    else:
        print(f"✗ Error: {result['message']}")

def logout():
    global session_id, buyer_id
    result = send_request('Logout')
    
    if result['status'] == 'success':
        print("✓ Logged out successfully!")
        session_id = None
        buyer_id = None
    else:
        print(f"✗ Error: {result['message']}")

def search_items():
    print("\n=== Search Items ===")
    category_input = input("Category (integer, press Enter to skip): ")
    category = int(category_input) if category_input else None
    keywords_input = input("Keywords (comma-separated, press Enter to skip): ")
    keywords = [kw.strip() for kw in keywords_input.split(',')] if keywords_input else []
    
    payload = {}
    if category is not None:
        payload['category'] = category
    if keywords:
        payload['keywords'] = keywords
    
    result = send_request('SearchItemsForSale', payload)
    
    if result['status'] == 'success':
        items = result['data']
        if not items:
            print("\nNo items found.")
        else:
            print(f"\n=== Search Results ({len(items)} items) ===")
            for item in items:
                print(f"\nItem ID: {item['item_id']}")
                print(f"  Name: {item['name']}")
                print(f"  Category: {item['category']}")
                print(f"  Condition: {item['condition']}")
                print(f"  Price: ${item['price']}")
                print(f"  Quantity: {item['quantity']}")
                print(f"  Keywords: {', '.join(item['keywords'])}")
                print(f"  Feedback: 👍 {item['feedback']['thumbs_up']} | 👎 {item['feedback']['thumbs_down']}")
    else:
        print(f"✗ Error: {result['message']}")

def get_item():
    print("\n=== Get Item Details ===")
    item_id_str = input("Item ID (format: [category, id]): ")
    item_id = json.loads(item_id_str)
    
    result = send_request('GetItem', {'item_id': item_id})
    
    if result['status'] == 'success':
        item = result['data']
        print(f"\n=== Item Details ===")
        print(f"Item ID: {item['item_id']}")
        print(f"Name: {item['name']}")
        print(f"Seller ID: {item['seller_id']}")
        print(f"Category: {item['category']}")
        print(f"Condition: {item['condition']}")
        print(f"Price: ${item['price']}")
        print(f"Quantity: {item['quantity']}")
        print(f"Keywords: {', '.join(item['keywords'])}")
        print(f"Feedback: 👍 {item['feedback']['thumbs_up']} | 👎 {item['feedback']['thumbs_down']}")
    else:
        print(f"✗ Error: {result['message']}")

def add_to_cart():
    print("\n=== Add Item to Cart ===")
    item_id_str = input("Item ID (format: [category, id]): ")
    item_id = json.loads(item_id_str)
    quantity = int(input("Quantity: "))
    
    result = send_request('AddItemToCart', {
        'item_id': item_id,
        'quantity': quantity
    })
    
    if result['status'] == 'success':
        print("✓ Item added to cart!")
    else:
        print(f"✗ Error: {result['message']}")

def remove_from_cart():
    print("\n=== Remove Item from Cart ===")
    item_id_str = input("Item ID (format: [category, id]): ")
    item_id = json.loads(item_id_str)
    quantity = int(input("Quantity: "))
    
    result = send_request('RemoveItemFromCart', {
        'item_id': item_id,
        'quantity': quantity
    })
    
    if result['status'] == 'success':
        print("✓ Item removed from cart!")
    else:
        print(f"✗ Error: {result['message']}")

def display_cart():
    result = send_request('DisplayCart')
    
    if result['status'] == 'success':
        cart = result['data']
        if not cart:
            print("\nYour cart is empty.")
        else:
            print("\n=== Your Shopping Cart ===")
            for cart_item in cart:
                print(f"Item ID: {cart_item['item_id']} - Quantity: {cart_item['quantity']}")
    else:
        print(f"✗ Error: {result['message']}")

def clear_cart():
    result = send_request('ClearCart')
    
    if result['status'] == 'success':
        print("✓ Cart cleared!")
    else:
        print(f"✗ Error: {result['message']}")

def provide_feedback():
    print("\n=== Provide Feedback ===")
    item_id_str = input("Item ID (format: [category, id]): ")
    item_id = json.loads(item_id_str)
    feedback = input("Feedback (thumbs_up/thumbs_down): ")
    
    result = send_request('ProvideFeedback', {
        'item_id': item_id,
        'feedback_type': feedback
    })
    
    if result['status'] == 'success':
        print("✓ Feedback submitted!")
    else:
        print(f"✗ Error: {result['message']}")

def get_seller_rating():
    print("\n=== Get Seller Rating ===")
    seller_id = int(input("Seller ID: "))
    
    result = send_request('GetSellerRating', {'seller_id': seller_id})
    
    if result['status'] == 'success':
        rating = result['data']
        print(f"\nSeller {seller_id} rating: 👍 {rating['thumbs_up']} | 👎 {rating['thumbs_down']}")
    else:
        print(f"✗ Error: {result['message']}")

def get_purchase_history():
    result = send_request('GetBuyerPurchases')
    
    if result['status'] == 'success':
        purchases = result['data']
        if not purchases:
            print("\nNo purchase history yet.")
        else:
            print("\n=== Purchase History ===")
            for item_id in purchases:
                print(f"Item ID: {item_id}")
    else:
        print(f"✗ Error: {result['message']}")

def main():
    global session_id
    
    print("=" * 50)
    print("    MARKETPLACE - BUYER CLIENT")
    print("=" * 50)
    
    while True:
        print("\n" + "=" * 50)
        if session_id:
            print(f"Logged in as Buyer ID: {buyer_id}")
            print("=" * 50)
            print("1. Logout")
            print("2. Search Items")
            print("3. Get Item Details")
            print("4. Add Item to Cart")
            print("5. Remove Item from Cart")
            print("6. Display Cart")
            print("7. Clear Cart")
            print("8. Provide Feedback")
            print("9. Get Seller Rating")
            print("10. View Purchase History")
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
                search_items()
            elif choice == '3':
                get_item()
            elif choice == '4':
                add_to_cart()
            elif choice == '5':
                remove_from_cart()
            elif choice == '6':
                display_cart()
            elif choice == '7':
                clear_cart()
            elif choice == '8':
                provide_feedback()
            elif choice == '9':
                get_seller_rating()
            elif choice == '10':
                get_purchase_history()
            else:
                print("Invalid choice!")

if __name__ == '__main__':
    main()