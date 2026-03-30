"""
Reusable gRPC stub pool with failover.

Used by seller_server.py and buyer_server.py to connect to multiple
replicas of the customer DB and product DB backends.

On a gRPC error (unavailable, deadline exceeded, etc.), the pool
automatically tries the next replica in the list.
"""

import grpc
import logging

logger = logging.getLogger(__name__)


class StubPool:
    """
    Maintains gRPC stubs to multiple replicas and provides failover.

    Usage:
        pool = StubPool(["host1:50051", "host2:50051"], CustomerDBStub)
        result = pool.call("GetUser", request)
    """

    def __init__(self, addresses: list, stub_class):
        self.addresses = addresses
        self.stub_class = stub_class
        self.channels = []
        self.stubs = []
        self.current = 0

        for addr in addresses:
            channel = grpc.insecure_channel(addr)
            self.channels.append(channel)
            self.stubs.append(stub_class(channel))

        logger.info("StubPool created for %s with %d replicas: %s",
                     stub_class.__name__, len(addresses), addresses)

    def call(self, method_name: str, request, timeout=10):
        """
        Call a gRPC method, trying each replica on failure.

        Returns the gRPC response on success.
        Raises the last exception if all replicas fail.
        """
        last_error = None
        for i in range(len(self.stubs)):
            idx = (self.current + i) % len(self.stubs)
            try:
                method = getattr(self.stubs[idx], method_name)
                result = method(request, timeout=timeout)
                self.current = idx  # sticky to working replica
                return result
            except grpc.RpcError as e:
                last_error = e
                logger.warning(
                    "StubPool: %s failed on %s, trying next replica. Error: %s",
                    method_name, self.addresses[idx], e.code() if hasattr(e, 'code') else e,
                )
                continue

        logger.error("StubPool: all %d replicas failed for %s", len(self.stubs), method_name)
        raise last_error
