"""
Rotating Sequencer Atomic Broadcast Protocol

Uses UDP for all inter-replica communication. Provides total-order delivery
of messages across n group members using a rotating sequencer scheme.

Message types:
  REQUEST    - broadcast by originator to all members
  SEQUENCE   - broadcast by the rotating sequencer to assign global order
  ACK        - broadcast by each member upon receiving a Sequence message
  RETRANSMIT - unicast negative acknowledgement for missing messages
"""

import json
import socket
import struct
import threading
import time
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Message type constants
# ---------------------------------------------------------------------------
MSG_REQUEST = "REQUEST"
MSG_SEQUENCE = "SEQUENCE"
MSG_ACK = "ACK"
MSG_RETRANSMIT = "RETRANSMIT"

# How often the gap-detection / retransmit loop runs (seconds)
GAP_CHECK_INTERVAL = 0.05  # 50 ms
# Maximum UDP datagram payload size
MAX_UDP_SIZE = 65000
# Number of redundant sends per broadcast (to cope with UDP loss)
REDUNDANT_SENDS = 2
# Small delay between redundant sends (seconds)
REDUNDANT_DELAY = 0.002


class AtomicBroadcastNode:
    """
    A single member of a rotating-sequencer atomic broadcast group.

    Parameters
    ----------
    node_id : int
        Unique ID for this member (0 .. n-1).
    members : list[tuple[str, int]]
        List of (host, udp_port) for every group member, indexed by member ID.
    on_deliver : callable(payload: dict) -> any
        Callback invoked (in delivery-order) when a request is delivered.
        Must be thread-safe.  The return value is stored so the originator
        can retrieve it.
    """

    def __init__(self, node_id: int, members: list, on_deliver):
        self.node_id = node_id
        self.n = len(members)
        self.members = members  # [(host, port), ...]
        self.on_deliver = on_deliver

        # UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(self.members[self.node_id])
        self.sock.settimeout(0.05)

        # ---- Local sequence counter (monotonically increasing per node) ----
        self.next_local_seq = 0
        self.local_seq_lock = threading.Lock()

        # ---- Request buffer ----
        # Key: (sender_id, local_seq) -> request dict
        self.requests = {}
        self.requests_lock = threading.Lock()

        # ---- Sequence buffer ----
        # Key: global_seq -> sequence dict  (contains sender_id, local_seq)
        self.sequences = {}
        self.sequences_lock = threading.Lock()

        # ---- Mapping from (sender_id, local_seq) -> global_seq ----
        self.request_to_global = {}

        # ---- Highest local_seq received from each sender ----
        self.highest_local_seq = {}  # sender_id -> highest local_seq seen

        # ---- Global sequencer state ----
        # The next global sequence number this node will try to assign
        # (only meaningful when self.node_id == next_to_assign % n)
        self.next_global_to_assign = 0
        self.assign_lock = threading.Lock()

        # ---- Delivery state ----
        self.next_to_deliver = 0  # next global_seq we should deliver
        self.deliver_lock = threading.Lock()

        # ---- ACK tracking ----
        # global_seq -> set of member IDs that have acked
        self.acks = {}
        self.acks_lock = threading.Lock()

        # ---- Pending-result tracking (for originator blocking) ----
        # msg_id (sender_id, local_seq) -> threading.Event
        self.pending_events = {}
        # msg_id -> result returned by on_deliver
        self.pending_results = {}
        self.pending_lock = threading.Lock()

        # ---- Control ----
        self._running = False
        self._threads = []

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def start(self):
        """Start the UDP listener and gap-detection threads."""
        self._running = True
        t1 = threading.Thread(target=self._udp_listener, daemon=True, name="udp-listen")
        t2 = threading.Thread(target=self._gap_detection_loop, daemon=True, name="gap-detect")
        t3 = threading.Thread(target=self._sequencer_loop, daemon=True, name="sequencer")
        for t in (t1, t2, t3):
            t.start()
            self._threads.append(t)
        logger.info("Node %d started on %s:%d", self.node_id, *self.members[self.node_id])

    def stop(self):
        """Stop all background threads."""
        self._running = False
        for t in self._threads:
            t.join(timeout=2)
        self.sock.close()
        logger.info("Node %d stopped", self.node_id)

    def broadcast_request(self, payload: dict, timeout: float = 15.0):
        """
        Submit a client request for atomic broadcast.

        Blocks until the request has been delivered (in global order) on this
        node.  Returns the result of the on_deliver callback.

        Parameters
        ----------
        payload : dict
            JSON-serializable application payload.
        timeout : float
            Max seconds to wait for delivery.

        Returns
        -------
        The value returned by the on_deliver callback for this request.

        Raises
        ------
        TimeoutError if delivery does not happen within *timeout* seconds.
        """
        with self.local_seq_lock:
            local_seq = self.next_local_seq
            self.next_local_seq += 1

        msg_id = (self.node_id, local_seq)

        # Create an event so we can block until delivery
        event = threading.Event()
        with self.pending_lock:
            self.pending_events[msg_id] = event

        # Build and broadcast the Request message
        req_msg = {
            "type": MSG_REQUEST,
            "sender_id": self.node_id,
            "local_seq": local_seq,
            "payload": payload,
        }

        self._broadcast(req_msg)

        # Block until delivered
        if not event.wait(timeout=timeout):
            raise TimeoutError(
                f"Node {self.node_id}: request {msg_id} not delivered within {timeout}s"
            )

        with self.pending_lock:
            result = self.pending_results.pop(msg_id, None)
            self.pending_events.pop(msg_id, None)

        return result

    # -----------------------------------------------------------------------
    # UDP transport
    # -----------------------------------------------------------------------

    def _send(self, msg: dict, dest: tuple):
        """Send a single UDP datagram to (host, port)."""
        data = json.dumps(msg).encode("utf-8")
        if len(data) > MAX_UDP_SIZE:
            logger.error("Message too large (%d bytes)", len(data))
            return
        try:
            self.sock.sendto(data, dest)
        except OSError as e:
            logger.warning("Send error to %s: %s", dest, e)

    def _broadcast(self, msg: dict):
        """Send msg to every group member (including self), with redundancy."""
        for _ in range(REDUNDANT_SENDS):
            for member in self.members:
                self._send(msg, member)
            if REDUNDANT_SENDS > 1:
                time.sleep(REDUNDANT_DELAY)

    def _udp_listener(self):
        """Main receive loop."""
        while self._running:
            try:
                data, addr = self.sock.recvfrom(MAX_UDP_SIZE + 1024)
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    logger.exception("Socket error")
                break

            try:
                msg = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.warning("Bad datagram from %s", addr)
                continue

            msg_type = msg.get("type")
            if msg_type == MSG_REQUEST:
                self._handle_request(msg)
            elif msg_type == MSG_SEQUENCE:
                self._handle_sequence(msg)
            elif msg_type == MSG_ACK:
                self._handle_ack(msg)
            elif msg_type == MSG_RETRANSMIT:
                self._handle_retransmit(msg)
            else:
                logger.warning("Unknown message type: %s", msg_type)

    # -----------------------------------------------------------------------
    # Request handling
    # -----------------------------------------------------------------------

    def _handle_request(self, msg: dict):
        """Process a received Request message."""
        sender_id = msg["sender_id"]
        local_seq = msg["local_seq"]
        key = (sender_id, local_seq)

        with self.requests_lock:
            if key in self.requests:
                return  # duplicate
            self.requests[key] = msg
            # Track highest local_seq from this sender
            prev = self.highest_local_seq.get(sender_id, -1)
            if local_seq > prev:
                self.highest_local_seq[sender_id] = local_seq

        # Check if we already have a Sequence referencing this Request
        # but couldn't ACK yet because the Request was missing.
        global_seq = self.request_to_global.get(key)
        if global_seq is not None:
            self._try_ack(global_seq, sender_id, local_seq)

    # -----------------------------------------------------------------------
    # Sequencer logic
    # -----------------------------------------------------------------------

    def _sequencer_loop(self):
        """
        Continuously check whether this node is the sequencer for the next
        unassigned global sequence number, and if so, try to assign it.
        """
        while self._running:
            self._try_assign_sequence()
            time.sleep(0.005)  # 5 ms poll

    def _try_assign_sequence(self):
        """
        If this node is the sequencer for the next global seq to assign,
        check preconditions and assign if possible.
        """
        with self.assign_lock:
            k = self.next_global_to_assign

            # Am I the sequencer for global_seq k?
            if k % self.n != self.node_id:
                # Find the next k that belongs to this node
                # (fast-forward so we don't spin on irrelevant k values)
                return

            # Condition 1: received all Sequence msgs with global_seq < k
            with self.sequences_lock:
                for seq_num in range(k):
                    if seq_num not in self.sequences:
                        return

            # Condition 2: received all Request msgs assigned global_seq < k
            with self.requests_lock:
                for seq_num in range(k):
                    with self.sequences_lock:
                        seq_msg = self.sequences.get(seq_num)
                    if seq_msg is None:
                        return
                    req_key = (seq_msg["sender_id"], seq_msg["local_seq"])
                    if req_key not in self.requests:
                        return

            # Pick a Request message that has NOT yet been assigned a global seq.
            # Condition 3: All Request msgs from the same sender with local_seq
            #   less than the chosen request's local_seq must already be sequenced.
            chosen = None
            with self.requests_lock:
                candidates = []
                for req_key, req_msg in self.requests.items():
                    if req_key in self.request_to_global:
                        continue  # already sequenced
                    candidates.append(req_key)

                # Sort for determinism: by (sender_id, local_seq)
                candidates.sort()

                for req_key in candidates:
                    sid, lseq = req_key
                    # Check condition 3: all prior local_seq from this sender
                    # must already have global sequence numbers
                    all_prior_sequenced = True
                    for prev_lseq in range(lseq):
                        if (sid, prev_lseq) not in self.request_to_global:
                            # Check if we even have this request
                            if (sid, prev_lseq) not in self.requests:
                                all_prior_sequenced = False
                                break
                            # We have it but it's not sequenced yet
                            all_prior_sequenced = False
                            break
                    if all_prior_sequenced:
                        chosen = req_key
                        break

            if chosen is None:
                return  # no eligible request yet

            # Assign global sequence number k to this request
            sid, lseq = chosen
            self.request_to_global[chosen] = k

            seq_msg = {
                "type": MSG_SEQUENCE,
                "global_seq": k,
                "sender_id": sid,
                "local_seq": lseq,
                "sequencer_id": self.node_id,
            }

            with self.sequences_lock:
                self.sequences[k] = seq_msg

            # Record our own ACK
            with self.acks_lock:
                if k not in self.acks:
                    self.acks[k] = set()
                self.acks[k].add(self.node_id)

            self.next_global_to_assign = k + 1
            # Fast-forward to next k that belongs to this node
            while self.next_global_to_assign % self.n != self.node_id:
                self.next_global_to_assign += 1

            self._broadcast(seq_msg)
            logger.debug(
                "Node %d: assigned global_seq %d to request (%d, %d)",
                self.node_id, k, sid, lseq,
            )

    # -----------------------------------------------------------------------
    # Sequence handling
    # -----------------------------------------------------------------------

    def _handle_sequence(self, msg: dict):
        """Process a received Sequence message."""
        global_seq = msg["global_seq"]
        sid = msg["sender_id"]
        lseq = msg["local_seq"]

        with self.sequences_lock:
            if global_seq not in self.sequences:
                self.sequences[global_seq] = msg

        # Record mapping
        self.request_to_global[(sid, lseq)] = global_seq

        # Update our sequencer pointer if we're responsible for future seqs
        with self.assign_lock:
            if global_seq >= self.next_global_to_assign:
                # Jump ahead: next unassigned seq for this node
                candidate = global_seq + 1
                while candidate % self.n != self.node_id:
                    candidate += 1
                if candidate > self.next_global_to_assign:
                    self.next_global_to_assign = candidate

        # Only ACK when we have BOTH the Request and the Sequence,
        # confirming this node has the full information for this global_seq.
        self._try_ack(global_seq, sid, lseq)

        # Try to deliver
        self._try_deliver()

    # -----------------------------------------------------------------------
    # ACK logic — only ACK when we have both Request AND Sequence
    # -----------------------------------------------------------------------

    def _try_ack(self, global_seq: int, sender_id: int, local_seq: int):
        """Send ACK for global_seq only if we have both the Request and Sequence."""
        with self.requests_lock:
            has_request = (sender_id, local_seq) in self.requests
        with self.sequences_lock:
            has_sequence = global_seq in self.sequences

        if has_request and has_sequence:
            ack_msg = {
                "type": MSG_ACK,
                "acker_id": self.node_id,
                "global_seq": global_seq,
            }
            self._broadcast(ack_msg)

    # -----------------------------------------------------------------------
    # ACK handling
    # -----------------------------------------------------------------------

    def _handle_ack(self, msg: dict):
        """Process a received ACK message."""
        global_seq = msg["global_seq"]
        acker_id = msg["acker_id"]

        with self.acks_lock:
            if global_seq not in self.acks:
                self.acks[global_seq] = set()
            self.acks[global_seq].add(acker_id)

        # Try to deliver (majority may now be reached)
        self._try_deliver()

    # -----------------------------------------------------------------------
    # Delivery logic
    # -----------------------------------------------------------------------

    def _try_deliver(self):
        """
        Deliver as many requests as possible in global sequence order.

        Delivery conditions for global_seq s:
        1. All requests with global_seq < s have been delivered.
        2. A majority of group members have received all Request messages
           AND their corresponding Sequence messages with global_seq <= s.

        We approximate condition 2 by checking that for each global_seq
        from 0..s, at least a majority of members have ACKed.
        """
        with self.deliver_lock:
            while True:
                s = self.next_to_deliver

                # Do we have the Sequence message for s?
                with self.sequences_lock:
                    seq_msg = self.sequences.get(s)
                if seq_msg is None:
                    break

                # Do we have the Request message for s?
                sid = seq_msg["sender_id"]
                lseq = seq_msg["local_seq"]
                with self.requests_lock:
                    req_msg = self.requests.get((sid, lseq))
                if req_msg is None:
                    break

                # Check majority ACK for all seq numbers up to s
                majority = (self.n // 2) + 1
                all_majority = True
                with self.acks_lock:
                    for seq_num in range(s + 1):
                        ack_set = self.acks.get(seq_num)
                        if ack_set is None or len(ack_set) < majority:
                            all_majority = False
                            break
                if not all_majority:
                    break

                # Deliver!
                self.next_to_deliver = s + 1
                payload = req_msg["payload"]
                msg_id = (sid, lseq)

                try:
                    result = self.on_deliver(payload)
                except Exception:
                    logger.exception(
                        "Node %d: on_deliver raised for global_seq %d", self.node_id, s
                    )
                    result = None

                # Signal the originator if this node initiated the request
                with self.pending_lock:
                    if msg_id in self.pending_events:
                        self.pending_results[msg_id] = result
                        self.pending_events[msg_id].set()

                logger.debug(
                    "Node %d: delivered global_seq %d (request %s)",
                    self.node_id, s, msg_id,
                )

    # -----------------------------------------------------------------------
    # Gap detection & retransmit
    # -----------------------------------------------------------------------

    def _gap_detection_loop(self):
        """Periodically scan for missing Request or Sequence messages."""
        while self._running:
            time.sleep(GAP_CHECK_INTERVAL)
            self._detect_gaps()

    def _detect_gaps(self):
        """Send Retransmit requests for any detected gaps."""
        with self.deliver_lock:
            next_del = self.next_to_deliver

        # --- Check for missing Sequence messages ---
        # We expect a contiguous run of Sequence messages starting from 0.
        # If we have seq s+2 but not s+1, request retransmit for s+1.
        with self.sequences_lock:
            if self.sequences:
                max_seq = max(self.sequences.keys())
            else:
                max_seq = -1

        for s in range(next_del, max_seq + 1):
            with self.sequences_lock:
                if s not in self.sequences:
                    # Who is the sequencer for s?
                    sequencer_id = s % self.n
                    retransmit_msg = {
                        "type": MSG_RETRANSMIT,
                        "requester_id": self.node_id,
                        "missing_type": MSG_SEQUENCE,
                        "global_seq": s,
                    }
                    self._send(retransmit_msg, self.members[sequencer_id])

        # --- Check for missing Request messages ---
        # For each Sequence we have, ensure we also have the corresponding Request.
        with self.sequences_lock:
            seq_snapshot = dict(self.sequences)

        with self.requests_lock:
            for global_seq, seq_msg in seq_snapshot.items():
                sid = seq_msg["sender_id"]
                lseq = seq_msg["local_seq"]
                if (sid, lseq) not in self.requests:
                    retransmit_msg = {
                        "type": MSG_RETRANSMIT,
                        "requester_id": self.node_id,
                        "missing_type": MSG_REQUEST,
                        "sender_id": sid,
                        "local_seq": lseq,
                    }
                    self._send(retransmit_msg, self.members[sid])

        # --- Check for gaps in local_seq from each sender ---
        with self.requests_lock:
            for sid, highest in list(self.highest_local_seq.items()):
                for lseq in range(highest):
                    if (sid, lseq) not in self.requests:
                        retransmit_msg = {
                            "type": MSG_RETRANSMIT,
                            "requester_id": self.node_id,
                            "missing_type": MSG_REQUEST,
                            "sender_id": sid,
                            "local_seq": lseq,
                        }
                        self._send(retransmit_msg, self.members[sid])

    def _handle_retransmit(self, msg: dict):
        """Respond to a retransmit request by re-sending the missing message."""
        requester_id = msg["requester_id"]
        missing_type = msg["missing_type"]
        dest = self.members[requester_id]

        if missing_type == MSG_SEQUENCE:
            global_seq = msg["global_seq"]
            with self.sequences_lock:
                seq_msg = self.sequences.get(global_seq)
            if seq_msg is not None:
                self._send(seq_msg, dest)

        elif missing_type == MSG_REQUEST:
            sid = msg["sender_id"]
            lseq = msg["local_seq"]
            with self.requests_lock:
                req_msg = self.requests.get((sid, lseq))
            if req_msg is not None:
                self._send(req_msg, dest)

    # -----------------------------------------------------------------------
    # Diagnostics
    # -----------------------------------------------------------------------

    def status(self) -> dict:
        """Return a snapshot of internal state for debugging."""
        with self.deliver_lock:
            next_del = self.next_to_deliver
        with self.assign_lock:
            next_assign = self.next_global_to_assign
        with self.requests_lock:
            num_requests = len(self.requests)
        with self.sequences_lock:
            num_sequences = len(self.sequences)
        with self.acks_lock:
            ack_summary = {k: len(v) for k, v in self.acks.items()}

        return {
            "node_id": self.node_id,
            "next_local_seq": self.next_local_seq,
            "next_to_deliver": next_del,
            "next_global_to_assign": next_assign,
            "num_requests": num_requests,
            "num_sequences": num_sequences,
            "ack_counts": ack_summary,
        }
