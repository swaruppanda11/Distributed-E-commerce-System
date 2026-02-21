import requests
import json
import argparse

SERVER_HOST = 'localhost'
SERVER_PORT = 5003

session_id = None
seller_id = None


def base_url():
    return f'http://{SERVER_HOST}:{SERVER_PORT}'


def send(method, path, data=None, params=None):
    global session_id, seller_id
    headers = {'X-Session-ID': session_id} if session_id else {}
    url = base_url() + path
    try:
        if method == 'GET':
            resp = requests.get(url, headers=headers, params=params)
        elif method == 'POST':
            resp = requests.post(url, headers=headers, json=data)
        elif method == 'PUT':
            resp = requests.put(url, headers=headers, json=data)
        elif method == 'DELETE':
            resp = requests.delete(url, headers=headers)
        result = resp.json()
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

    if result.get('status') == 'error' and 'expired' in result.get('message', '').lower():
        print("\nSession expired. You have been logged out automatically.")
        session_id = None
        seller_id = None

    return result


def parse_item_id(prompt="Item ID (format: [category, id], e.g. [1, 1]): "):
    raw = input(prompt)
    try:
        item_id = json.loads(raw)
        if not (isinstance(item_id, list) and len(item_id) == 2):
            print("Invalid format. Expected [category_int, item_int]")
            return None
        return item_id
    except json.JSONDecodeError:
        print("Invalid format. Expected [category_int, item_int]")
        return None


def create_account():
    print("\n=== Create Seller Account ===")
    username = input("Username: ")
    password = input("Password: ")
    name = input("Name: ")
    result = send('POST', '/seller/account', {'username': username, 'password': password, 'name': name})
    if result['status'] == 'success':
        print(f"Account created! Your seller ID is: {result['user_id']}")
    else:
        print(f"Error: {result['message']}")


def login():
    global session_id, seller_id
    print("\n=== Seller Login ===")
    username = input("Username: ")
    password = input("Password: ")
    result = send('POST', '/seller/login', {'username': username, 'password': password})
    if result['status'] == 'success':
        session_id = result['session_id']
        seller_id = result['seller_id']
        print(f"Logged in! Seller ID: {seller_id}")
    else:
        print(f"Error: {result['message']}")


def logout():
    global session_id, seller_id
    send('POST', '/seller/logout')
    session_id = None
    seller_id = None
    print("Logged out.")


def get_seller_rating():
    result = send('GET', f'/seller/rating/{seller_id}')
    if result['status'] == 'success':
        print(f"\nYour rating: Thumbs Up: {result['thumbs_up']} | Thumbs Down: {result['thumbs_down']}")
    else:
        print(f"Error: {result['message']}")


def register_item():
    print("\n=== Register Item for Sale ===")
    name = input("Item name: ")
    category = int(input("Category (integer): "))
    keywords = input("Keywords (comma-separated, max 5): ").split(',')
    keywords = [kw.strip() for kw in keywords[:5]]
    condition = input("Condition (New/Used): ")
    price = float(input("Price: "))
    quantity = int(input("Quantity: "))
    result = send('POST', '/seller/items', {
        'name': name, 'category': category, 'keywords': keywords,
        'condition': condition, 'price': price, 'quantity': quantity
    })
    if result['status'] == 'success':
        print(f"Item registered! Item ID: {result['item_id']}")
    else:
        print(f"Error: {result['message']}")


def change_item_price():
    print("\n=== Change Item Price ===")
    item_id = parse_item_id()
    if item_id is None:
        return
    new_price = float(input("New price: "))
    cat, iid = item_id
    result = send('PUT', f'/seller/items/{cat}/{iid}/price', {'price': new_price})
    if result['status'] == 'success':
        print("Price updated!")
    else:
        print(f"Error: {result['message']}")


def update_units():
    print("\n=== Update Units for Sale ===")
    item_id = parse_item_id()
    if item_id is None:
        return
    new_quantity = int(input("New quantity: "))
    cat, iid = item_id
    result = send('PUT', f'/seller/items/{cat}/{iid}/quantity', {'quantity': new_quantity})
    if result['status'] == 'success':
        print("Quantity updated!")
    else:
        print(f"Error: {result['message']}")


def display_items():
    result = send('GET', '/seller/items')
    if result['status'] == 'success':
        items = result['items']
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
                print(f"  Feedback: Thumbs Up: {item['thumbs_up']} | Thumbs Down: {item['thumbs_down']}")
    else:
        print(f"Error: {result['message']}")


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
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int, default=5003)
    args = parser.parse_args()

    SERVER_HOST = args.host
    SERVER_PORT = args.port

    main()
