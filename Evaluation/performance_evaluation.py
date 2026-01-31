"""
Performance Evaluation Script for E-Commerce Marketplace

This script measures:
- Average Response Time: Time between client API call and server response
- Average Throughput: Number of client operations completed per second

Scenarios tested:
- Scenario 1: 1 seller, 1 buyer
- Scenario 2: 10 sellers, 10 buyers (concurrent)
- Scenario 3: 100 sellers, 100 buyers (concurrent)

Each client invokes 1000 API calls per run, averaged over 10 runs.
"""

import time
import socket
import json
import threading
import random
from statistics import mean, stdev
from concurrent.futures import ThreadPoolExecutor

# Server configuration
SELLER_SERVER_HOST = 'localhost'
SELLER_SERVER_PORT = 5003
BUYER_SERVER_HOST = 'localhost'
BUYER_SERVER_PORT = 5004

# Test configuration
OPERATIONS_PER_CLIENT = 1000
NUM_ITERATIONS = 10

# Thread-safe lock for collecting results
results_lock = threading.Lock()


def send_request(host, port, api, session_id=None, payload=None):
    """
    Send a request to the server and measure response time.

    Returns:
        tuple: (response_dict, response_time_seconds)
    """
    start_time = time.perf_counter()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)  # 30 second timeout
        sock.connect((host, port))

        request = {
            'api': api,
            'session_id': session_id,
            'payload': payload or {}
        }
        sock.send(json.dumps(request).encode('utf-8'))

        response = sock.recv(8192).decode('utf-8')
        sock.close()

        end_time = time.perf_counter()
        response_time = end_time - start_time

        return json.loads(response), response_time
    except Exception as e:
        end_time = time.perf_counter()
        return {'status': 'error', 'message': str(e)}, end_time - start_time


def seller_workflow(seller_id, num_operations):
    """
    Simulate a seller performing operations.

    Each seller performs exactly num_operations API calls consisting of:
    - Create account (1 call)
    - Login (1 call)
    - Register items, change prices, update quantities, display items (remaining calls)
    - Logout (1 call)

    Args:
        seller_id: Unique identifier for this seller
        num_operations: Total number of API calls to make

    Returns:
        list: List of response times for each operation
    """
    response_times = []
    unique_id = f"seller_{seller_id}_{time.time()}_{random.randint(0, 999999)}"

    try:
        # Create account (1 operation)
        result, rt = send_request(SELLER_SERVER_HOST, SELLER_SERVER_PORT, 'CreateAccount',
                                  payload={
                                      'username': unique_id,
                                      'password': 'password123',
                                      'name': f'Test Seller {seller_id}'
                                  })
        response_times.append(rt)

        if result['status'] != 'success':
            # Fill remaining operations with failed attempts
            for _ in range(num_operations - 1):
                _, rt = send_request(SELLER_SERVER_HOST, SELLER_SERVER_PORT, 'Login',
                                    payload={'username': 'invalid', 'password': 'invalid'})
                response_times.append(rt)
            return response_times

        # Login (1 operation)
        result, rt = send_request(SELLER_SERVER_HOST, SELLER_SERVER_PORT, 'Login',
                                  payload={
                                      'username': unique_id,
                                      'password': 'password123'
                                  })
        response_times.append(rt)

        if result['status'] != 'success':
            for _ in range(num_operations - 2):
                _, rt = send_request(SELLER_SERVER_HOST, SELLER_SERVER_PORT, 'Login',
                                    payload={'username': 'invalid', 'password': 'invalid'})
                response_times.append(rt)
            return response_times

        session_id = result['data']['session_id']

        # Remaining operations (num_operations - 3: account, login, logout)
        remaining_ops = num_operations - 3
        registered_items = []

        # Distribute operations across different API calls
        # RegisterItem: 20%, ChangePrice: 20%, UpdateQuantity: 20%,
        # DisplayItems: 20%, GetSellerRating: 20%

        ops_per_type = remaining_ops // 5
        extra_ops = remaining_ops % 5

        # Register items
        for i in range(ops_per_type + (1 if extra_ops > 0 else 0)):
            category = random.randint(0, 9)
            result, rt = send_request(SELLER_SERVER_HOST, SELLER_SERVER_PORT,
                                      'RegisterItemForSale',
                                      session_id=session_id,
                                      payload={
                                          'name': f'Item_{seller_id}_{i}',
                                          'category': category,
                                          'keywords': ['test', 'item', f'seller{seller_id}'],
                                          'condition': random.choice(['New', 'Used']),
                                          'price': round(random.uniform(10, 500), 2),
                                          'quantity': random.randint(1, 100)
                                      })
            response_times.append(rt)
            if result['status'] == 'success':
                registered_items.append(result['data']['item_id'])

        if extra_ops > 0:
            extra_ops -= 1

        # Change item prices
        for i in range(ops_per_type + (1 if extra_ops > 0 else 0)):
            if registered_items:
                item_id = random.choice(registered_items)
                _, rt = send_request(SELLER_SERVER_HOST, SELLER_SERVER_PORT,
                                    'ChangeItemPrice',
                                    session_id=session_id,
                                    payload={
                                        'item_id': item_id,
                                        'price': round(random.uniform(10, 500), 2)
                                    })
            else:
                _, rt = send_request(SELLER_SERVER_HOST, SELLER_SERVER_PORT,
                                    'DisplayItemsForSale',
                                    session_id=session_id)
            response_times.append(rt)

        if extra_ops > 0:
            extra_ops -= 1

        # Update quantities
        for i in range(ops_per_type + (1 if extra_ops > 0 else 0)):
            if registered_items:
                item_id = random.choice(registered_items)
                _, rt = send_request(SELLER_SERVER_HOST, SELLER_SERVER_PORT,
                                    'UpdateUnitsForSale',
                                    session_id=session_id,
                                    payload={
                                        'item_id': item_id,
                                        'quantity': random.randint(1, 100)
                                    })
            else:
                _, rt = send_request(SELLER_SERVER_HOST, SELLER_SERVER_PORT,
                                    'DisplayItemsForSale',
                                    session_id=session_id)
            response_times.append(rt)

        if extra_ops > 0:
            extra_ops -= 1

        # Display items
        for i in range(ops_per_type + (1 if extra_ops > 0 else 0)):
            _, rt = send_request(SELLER_SERVER_HOST, SELLER_SERVER_PORT,
                                'DisplayItemsForSale',
                                session_id=session_id)
            response_times.append(rt)

        if extra_ops > 0:
            extra_ops -= 1

        # Get seller rating
        for i in range(ops_per_type + extra_ops):
            _, rt = send_request(SELLER_SERVER_HOST, SELLER_SERVER_PORT,
                                'GetSellerRating',
                                session_id=session_id)
            response_times.append(rt)

        # Logout (1 operation)
        _, rt = send_request(SELLER_SERVER_HOST, SELLER_SERVER_PORT, 'Logout',
                            session_id=session_id)
        response_times.append(rt)

    except Exception as e:
        print(f"Seller {seller_id} error: {e}")

    return response_times


def buyer_workflow(buyer_id, num_operations):
    """
    Simulate a buyer performing operations.

    Each buyer performs exactly num_operations API calls consisting of:
    - Create account (1 call)
    - Login (1 call)
    - Search, get items, cart operations, feedback (remaining calls)
    - Logout (1 call)

    Args:
        buyer_id: Unique identifier for this buyer
        num_operations: Total number of API calls to make

    Returns:
        list: List of response times for each operation
    """
    response_times = []
    unique_id = f"buyer_{buyer_id}_{time.time()}_{random.randint(0, 999999)}"

    try:
        # Create account (1 operation)
        result, rt = send_request(BUYER_SERVER_HOST, BUYER_SERVER_PORT, 'CreateAccount',
                                  payload={
                                      'username': unique_id,
                                      'password': 'password123',
                                      'name': f'Test Buyer {buyer_id}'
                                  })
        response_times.append(rt)

        if result['status'] != 'success':
            for _ in range(num_operations - 1):
                _, rt = send_request(BUYER_SERVER_HOST, BUYER_SERVER_PORT, 'Login',
                                    payload={'username': 'invalid', 'password': 'invalid'})
                response_times.append(rt)
            return response_times

        # Login (1 operation)
        result, rt = send_request(BUYER_SERVER_HOST, BUYER_SERVER_PORT, 'Login',
                                  payload={
                                      'username': unique_id,
                                      'password': 'password123'
                                  })
        response_times.append(rt)

        if result['status'] != 'success':
            for _ in range(num_operations - 2):
                _, rt = send_request(BUYER_SERVER_HOST, BUYER_SERVER_PORT, 'Login',
                                    payload={'username': 'invalid', 'password': 'invalid'})
                response_times.append(rt)
            return response_times

        session_id = result['data']['session_id']

        # Remaining operations (num_operations - 3: account, login, logout)
        remaining_ops = num_operations - 3
        found_items = []

        # Distribute operations:
        # SearchItems: 25%, GetItem: 15%, AddToCart: 15%,
        # DisplayCart: 15%, ClearCart: 10%, GetSellerRating: 20%

        search_ops = int(remaining_ops * 0.25)
        get_item_ops = int(remaining_ops * 0.15)
        add_cart_ops = int(remaining_ops * 0.15)
        display_cart_ops = int(remaining_ops * 0.15)
        clear_cart_ops = int(remaining_ops * 0.10)
        rating_ops = remaining_ops - search_ops - get_item_ops - add_cart_ops - display_cart_ops - clear_cart_ops

        # Search items
        for i in range(search_ops):
            category = random.randint(0, 9)
            result, rt = send_request(BUYER_SERVER_HOST, BUYER_SERVER_PORT,
                                     'SearchItemsForSale',
                                     session_id=session_id,
                                     payload={
                                         'category': category,
                                         'keywords': ['test']
                                     })
            response_times.append(rt)
            if result['status'] == 'success' and result['data']:
                for item in result['data'][:3]:
                    if item['item_id'] not in found_items:
                        found_items.append(item['item_id'])

        # Get item details
        for i in range(get_item_ops):
            if found_items:
                item_id = random.choice(found_items)
                _, rt = send_request(BUYER_SERVER_HOST, BUYER_SERVER_PORT,
                                    'GetItem',
                                    session_id=session_id,
                                    payload={'item_id': item_id})
            else:
                _, rt = send_request(BUYER_SERVER_HOST, BUYER_SERVER_PORT,
                                    'SearchItemsForSale',
                                    session_id=session_id,
                                    payload={'category': random.randint(0, 9)})
            response_times.append(rt)

        # Add items to cart
        for i in range(add_cart_ops):
            if found_items:
                item_id = random.choice(found_items)
                _, rt = send_request(BUYER_SERVER_HOST, BUYER_SERVER_PORT,
                                    'AddItemToCart',
                                    session_id=session_id,
                                    payload={
                                        'item_id': item_id,
                                        'quantity': 1
                                    })
            else:
                _, rt = send_request(BUYER_SERVER_HOST, BUYER_SERVER_PORT,
                                    'DisplayCart',
                                    session_id=session_id)
            response_times.append(rt)

        # Display cart
        for i in range(display_cart_ops):
            _, rt = send_request(BUYER_SERVER_HOST, BUYER_SERVER_PORT,
                                'DisplayCart',
                                session_id=session_id)
            response_times.append(rt)

        # Clear cart
        for i in range(clear_cart_ops):
            _, rt = send_request(BUYER_SERVER_HOST, BUYER_SERVER_PORT,
                                'ClearCart',
                                session_id=session_id)
            response_times.append(rt)

        # Get seller ratings
        for i in range(rating_ops):
            _, rt = send_request(BUYER_SERVER_HOST, BUYER_SERVER_PORT,
                                'GetSellerRating',
                                session_id=session_id,
                                payload={'seller_id': random.randint(1, 10)})
            response_times.append(rt)

        # Logout (1 operation)
        _, rt = send_request(BUYER_SERVER_HOST, BUYER_SERVER_PORT, 'Logout',
                            session_id=session_id)
        response_times.append(rt)

    except Exception as e:
        print(f"Buyer {buyer_id} error: {e}")

    return response_times


def run_scenario(num_sellers, num_buyers, ops_per_client):
    """
    Run a single scenario with the specified number of sellers and buyers.

    Args:
        num_sellers: Number of concurrent seller clients
        num_buyers: Number of concurrent buyer clients
        ops_per_client: Number of API calls each client should make

    Returns:
        tuple: (average_response_time, throughput, total_operations)
    """
    all_response_times = []

    scenario_start_time = time.perf_counter()

    # Use ThreadPoolExecutor for better thread management
    max_workers = num_sellers + num_buyers

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []

        # Submit seller tasks
        for i in range(num_sellers):
            future = executor.submit(seller_workflow, i, ops_per_client)
            futures.append(('seller', i, future))

        # Submit buyer tasks
        for i in range(num_buyers):
            future = executor.submit(buyer_workflow, i, ops_per_client)
            futures.append(('buyer', i, future))

        # Collect results
        for client_type, client_id, future in futures:
            try:
                response_times = future.result(timeout=300)  # 5 minute timeout
                with results_lock:
                    all_response_times.extend(response_times)
            except Exception as e:
                print(f"  {client_type} {client_id} failed: {e}")

    scenario_end_time = time.perf_counter()
    total_time = scenario_end_time - scenario_start_time

    # Calculate metrics
    total_operations = len(all_response_times)

    if total_operations > 0:
        avg_response_time = mean(all_response_times)
        throughput = total_operations / total_time
    else:
        avg_response_time = 0
        throughput = 0

    return avg_response_time, throughput, total_operations


def run_evaluation(num_sellers, num_buyers, iterations=NUM_ITERATIONS, ops_per_client=OPERATIONS_PER_CLIENT):
    """
    Run multiple iterations of a scenario and calculate statistics.

    Args:
        num_sellers: Number of concurrent seller clients
        num_buyers: Number of concurrent buyer clients
        iterations: Number of runs to average over
        ops_per_client: Number of API calls per client

    Returns:
        dict: Statistics including averages and standard deviations
    """
    print(f"\n{'='*70}")
    print(f"SCENARIO: {num_sellers} seller(s), {num_buyers} buyer(s)")
    print(f"Operations per client: {ops_per_client}")
    print(f"Number of iterations: {iterations}")
    print(f"{'='*70}")

    response_times = []
    throughputs = []
    total_ops_list = []

    for i in range(iterations):
        print(f"  Run {i+1}/{iterations}...", end='', flush=True)

        avg_rt, throughput, total_ops = run_scenario(num_sellers, num_buyers, ops_per_client)

        response_times.append(avg_rt)
        throughputs.append(throughput)
        total_ops_list.append(total_ops)

        print(f" Done | RT: {avg_rt*1000:.2f}ms | TP: {throughput:.2f} ops/s | Ops: {total_ops}")

        # Brief pause between runs to let servers stabilize
        time.sleep(1)

    # Calculate statistics
    avg_response_time = mean(response_times)
    std_response_time = stdev(response_times) if len(response_times) > 1 else 0
    avg_throughput = mean(throughputs)
    std_throughput = stdev(throughputs) if len(throughputs) > 1 else 0
    avg_total_ops = mean(total_ops_list)

    print(f"\n  RESULTS (Average over {iterations} runs):")
    print(f"  ----------------------------------------")
    print(f"  Average Response Time: {avg_response_time*1000:.2f} ms (+/- {std_response_time*1000:.2f} ms)")
    print(f"  Average Throughput: {avg_throughput:.2f} ops/sec (+/- {std_throughput:.2f} ops/sec)")
    print(f"  Average Total Operations: {avg_total_ops:.0f}")

    return {
        'scenario': f"{num_sellers} seller(s), {num_buyers} buyer(s)",
        'avg_response_time': avg_response_time,
        'std_response_time': std_response_time,
        'avg_throughput': avg_throughput,
        'std_throughput': std_throughput,
        'avg_total_ops': avg_total_ops
    }


def print_final_report(results):
    """Print a formatted final report of all scenarios."""
    print(f"\n{'='*70}")
    print("FINAL PERFORMANCE REPORT")
    print(f"{'='*70}")
    print(f"\nConfiguration:")
    print(f"  - Operations per client: {OPERATIONS_PER_CLIENT}")
    print(f"  - Iterations per scenario: {NUM_ITERATIONS}")
    print(f"  - Servers: localhost (ports 5003 for seller, 5004 for buyer)")

    print(f"\n{'='*70}")
    print("SUMMARY TABLE")
    print(f"{'='*70}")
    print(f"{'Scenario':<30} {'Avg RT (ms)':<15} {'Avg Throughput':<20}")
    print(f"{'-'*70}")

    for r in results:
        print(f"{r['scenario']:<30} {r['avg_response_time']*1000:>8.2f} +/- {r['std_response_time']*1000:<5.2f} "
              f"{r['avg_throughput']:>8.2f} +/- {r['std_throughput']:<5.2f} ops/s")

    print(f"\n{'='*70}")
    print("DETAILED RESULTS FOR REPORT")
    print(f"{'='*70}")

    for r in results:
        print(f"\n{r['scenario']}:")
        print(f"  - Average Response Time: {r['avg_response_time']*1000:.4f} ms (SD: {r['std_response_time']*1000:.4f} ms)")
        print(f"  - Average Throughput: {r['avg_throughput']:.2f} ops/sec (SD: {r['std_throughput']:.2f} ops/sec)")


def check_servers():
    """Check if all servers are running and accessible."""
    print("Checking server connectivity...")

    servers = [
        ('Seller Server', SELLER_SERVER_HOST, SELLER_SERVER_PORT),
        ('Buyer Server', BUYER_SERVER_HOST, BUYER_SERVER_PORT)
    ]

    all_ok = True
    for name, host, port in servers:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((host, port))
            sock.close()
            print(f"  [OK] {name} at {host}:{port}")
        except Exception as e:
            print(f"  [FAIL] {name} at {host}:{port} - {e}")
            all_ok = False

    return all_ok


def main():
    print("="*70)
    print("E-COMMERCE MARKETPLACE PERFORMANCE EVALUATION")
    print("="*70)
    print(f"\nConfiguration:")
    print(f"  - Operations per client: {OPERATIONS_PER_CLIENT}")
    print(f"  - Iterations per scenario: {NUM_ITERATIONS}")

    # Check server connectivity
    print()
    if not check_servers():
        print("\nERROR: Not all servers are accessible.")
        print("Please ensure the following servers are running:")
        print("  1. Customer Database (port 5001)")
        print("  2. Product Database (port 5002)")
        print("  3. Seller Server (port 5003)")
        print("  4. Buyer Server (port 5004)")
        print("\nStart servers with:")
        print("  python customer_database.py")
        print("  python product_database.py")
        print("  python seller_server.py")
        print("  python buyer_server.py")
        return

    print("\nAll servers are accessible. Starting evaluation...\n")

    results = []

    # Scenario 1: 1 seller, 1 buyer
    result = run_evaluation(1, 1)
    results.append(result)
    time.sleep(3)

    # Scenario 2: 10 sellers, 10 buyers
    result = run_evaluation(10, 10)
    results.append(result)
    time.sleep(3)

    # Scenario 3: 100 sellers, 100 buyers
    result = run_evaluation(100, 100)
    results.append(result)

    # Print final report
    print_final_report(results)

    print(f"\n{'='*70}")
    print("Evaluation complete!")
    print(f"{'='*70}")


if __name__ == '__main__':
    main()
