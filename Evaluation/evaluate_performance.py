import subprocess
import time
import socket
import json
import threading
from statistics import mean

def send_request(host, port, api, session_id=None, payload=None):
    """Send request and measure response time"""
    start_time = time.time()
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    
    request = {
        'api': api,
        'session_id': session_id,
        'payload': payload or {}
    }
    sock.send(json.dumps(request).encode('utf-8'))
    
    response = sock.recv(4096).decode('utf-8')
    sock.close()
    
    end_time = time.time()
    response_time = end_time - start_time
    
    return json.loads(response), response_time

def seller_workflow(seller_num):
    """Simulate a seller performing operations"""
    response_times = []
    
    # Create account
    _, rt = send_request('localhost', 5003, 'CreateAccount', payload={
        'username': f'seller_{seller_num}',
        'password': 'pass',
        'name': f'Seller {seller_num}'
    })
    response_times.append(rt)
    
    # Login
    result, rt = send_request('localhost', 5003, 'Login', payload={
        'username': f'seller_{seller_num}',
        'password': 'pass'
    })
    response_times.append(rt)
    session_id = result['data']['session_id']
    
    # Register items
    for i in range(5):
        _, rt = send_request('localhost', 5003, 'RegisterItemForSale', 
                            session_id=session_id,
                            payload={
                                'name': f'Item {i}',
                                'category': 1,
                                'keywords': ['test'],
                                'condition': 'New',
                                'price': 99.99,
                                'quantity': 10
                            })
        response_times.append(rt)
    
    # Display items
    _, rt = send_request('localhost', 5003, 'DisplayItemsForSale', session_id=session_id)
    response_times.append(rt)
    
    return response_times

def buyer_workflow(buyer_num):
    """Simulate a buyer performing operations"""
    response_times = []
    
    # Create account
    _, rt = send_request('localhost', 5004, 'CreateAccount', payload={
        'username': f'buyer_{buyer_num}',
        'password': 'pass',
        'name': f'Buyer {buyer_num}'
    })
    response_times.append(rt)
    
    # Login
    result, rt = send_request('localhost', 5004, 'Login', payload={
        'username': f'buyer_{buyer_num}',
        'password': 'pass'
    })
    response_times.append(rt)
    session_id = result['data']['session_id']
    
    # Search
    _, rt = send_request('localhost', 5004, 'SearchItemsForSale',
                        session_id=session_id,
                        payload={'category': 1})
    response_times.append(rt)
    
    # Add to cart
    _, rt = send_request('localhost', 5004, 'AddItemToCart',
                        session_id=session_id,
                        payload={'item_id': [1, 1], 'quantity': 1})
    response_times.append(rt)
    
    # Display cart
    _, rt = send_request('localhost', 5004, 'DisplayCart', session_id=session_id)
    response_times.append(rt)
    
    return response_times

def run_scenario(num_sellers, num_buyers):
    """Run a scenario with given number of sellers and buyers"""
    print(f"\n{'='*60}")
    print(f"Running scenario: {num_sellers} sellers, {num_buyers} buyers")
    print(f"{'='*60}")
    
    all_response_times = []
    threads = []
    results = []
    
    start_time = time.time()
    
    # Launch seller threads
    for i in range(num_sellers):
        def seller_task(num):
            rt = seller_workflow(num)
            results.append(rt)
        
        t = threading.Thread(target=seller_task, args=(i,))
        threads.append(t)
        t.start()
    
    # Launch buyer threads
    for i in range(num_buyers):
        def buyer_task(num):
            rt = buyer_workflow(num)
            results.append(rt)
        
        t = threading.Thread(target=buyer_task, args=(i,))
        threads.append(t)
        t.start()
    
    # Wait for all to complete
    for t in threads:
        t.join()
    
    end_time = time.time()
    total_time = end_time - start_time
    
    # Collect all response times
    for result in results:
        all_response_times.extend(result)
    
    # Calculate metrics
    avg_response_time = mean(all_response_times)
    total_operations = len(all_response_times)
    throughput = total_operations / total_time
    
    print(f"\nResults:")
    print(f"  Total operations: {total_operations}")
    print(f"  Total time: {total_time:.2f} seconds")
    print(f"  Average response time: {avg_response_time:.4f} seconds")
    print(f"  Throughput: {throughput:.2f} operations/second")
    
    return avg_response_time, throughput

if __name__ == '__main__':
    print("=" * 60)
    print("MARKETPLACE PERFORMANCE EVALUATION")
    print("=" * 60)
    
    # Run 3 scenarios
    results = []
    
    # Scenario 1
    avg_rt, tput = run_scenario(1, 1)
    results.append(("1 seller, 1 buyer", avg_rt, tput))
    
    time.sleep(2)  # Brief pause between scenarios
    
    # Scenario 2
    avg_rt, tput = run_scenario(10, 10)
    results.append(("10 sellers, 10 buyers", avg_rt, tput))
    
    time.sleep(2)
    
    # Scenario 3
    avg_rt, tput = run_scenario(100, 100)
    results.append(("100 sellers, 100 buyers", avg_rt, tput))
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for scenario, avg_rt, tput in results:
        print(f"\n{scenario}:")
        print(f"  Avg Response Time: {avg_rt:.4f}s")
        print(f"  Throughput: {tput:.2f} ops/sec")