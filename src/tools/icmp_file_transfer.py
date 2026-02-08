"""ICMP file transfer tool built on scapy.

Transfers files through ICMP packets with client/server mode.
Client splits files into chunks and sends them as ICMP echo requests.
Server listens for ICMP packets, reassembles file chunks, and sends ACKs.

Features:
    - Custom ICMP packet identification via magic bytes and ICMP ID field
    - Configurable payload size and sending interval
    - Stop-and-Wait ARQ for reliable delivery with retransmission
"""

import struct
import os
import logging
import threading
import time
import argparse
from scapy.all import IP, ICMP, Raw, send, sniff


# Magic bytes to identify packets from this tool
MAGIC = b'OASI'
# Custom ICMP identifier field value
ICMP_IDENT = 0x4F41
# Header: MAGIC(4) + TYPE(1) + SEQ(4)
HEADER_SIZE = 9

# Packet types
TYPE_METADATA = 0x01
TYPE_DATA = 0x02
TYPE_ACK = 0x03
TYPE_FIN = 0x04


def build_payload(pkt_type, seq_num, data=b''):
    """Build the raw payload bytes for an ICMP packet."""
    return MAGIC + struct.pack('!BI', pkt_type, seq_num) + data


def parse_payload(raw_payload):
    """Parse raw ICMP payload bytes into components.

    Returns:
        dict with 'type', 'seq', 'data' keys, or None if invalid.
    """
    if len(raw_payload) < HEADER_SIZE:
        return None
    if raw_payload[:4] != MAGIC:
        return None
    pkt_type, seq_num = struct.unpack('!BI', raw_payload[4:9])
    return {'type': pkt_type, 'seq': seq_num, 'data': raw_payload[9:]}


def is_valid_packet(pkt):
    """Check if a scapy packet is a valid ICMP file transfer packet."""
    if not pkt.haslayer(ICMP) or not pkt.haslayer(Raw):
        return False
    if pkt[ICMP].id != ICMP_IDENT:
        return False
    raw = bytes(pkt[Raw].load)
    return len(raw) >= HEADER_SIZE and raw[:4] == MAGIC


def build_icmp_packet(dest_ip, pkt_type, seq_num, data=b''):
    """Construct a full ICMP echo request with custom payload."""
    payload = build_payload(pkt_type, seq_num, data)
    return IP(dst=dest_ip) / ICMP(type=8, id=ICMP_IDENT) / Raw(load=payload)


def encode_metadata(total_chunks, filename):
    """Encode file metadata (total chunks and filename) into bytes."""
    return struct.pack('!I', total_chunks) + filename.encode('utf-8')


def decode_metadata(data):
    """Decode file metadata from bytes.

    Returns:
        Tuple of (total_chunks, filename), or (None, None) if invalid.
    """
    if len(data) < 4:
        return None, None
    total_chunks = struct.unpack('!I', data[:4])[0]
    filename = data[4:].decode('utf-8')
    return total_chunks, filename


class ICMPFileClient:
    """Client for sending files via ICMP packets with Stop-and-Wait ARQ."""

    def __init__(self, dest_ip, *, payload_size=512, interval=0.05,
                 timeout=2.0, max_retries=5):
        if payload_size <= HEADER_SIZE:
            raise ValueError(
                f"payload_size must be greater than {HEADER_SIZE}")
        self.dest_ip = dest_ip
        self.payload_size = payload_size
        self.interval = interval
        self.timeout = timeout
        self.max_retries = max_retries
        self.ack_event = threading.Event()
        self.expected_ack_seq = -1
        self.stop_sniff = threading.Event()

    def send_file(self, filepath):
        """Send a file to the server via ICMP packets."""
        filename = os.path.basename(filepath)
        with open(filepath, 'rb') as f:
            file_data = f.read()

        data_per_chunk = self.payload_size - HEADER_SIZE

        chunks = [file_data[i:i + data_per_chunk]
                  for i in range(0, len(file_data), data_per_chunk)]
        total_chunks = len(chunks)

        listener = threading.Thread(
            target=self._listen_for_acks, daemon=True)
        listener.start()

        try:
            meta = encode_metadata(total_chunks, filename)
            self._send_with_retry(TYPE_METADATA, 0, meta)

            for i, chunk in enumerate(chunks):
                time.sleep(self.interval)
                self._send_with_retry(TYPE_DATA, i + 1, chunk)

            time.sleep(self.interval)
            self._send_with_retry(TYPE_FIN, total_chunks + 1)
            logging.info(
                "File '%s' sent successfully (%d chunks)",
                filename, total_chunks)
        finally:
            self.stop_sniff.set()

    def _send_with_retry(self, pkt_type, seq, data=b''):
        """Send a packet and wait for ACK, retrying on timeout."""
        for attempt in range(self.max_retries):
            pkt = build_icmp_packet(self.dest_ip, pkt_type, seq, data)
            self.expected_ack_seq = seq
            self.ack_event.clear()
            send(pkt, verbose=False)

            if self.ack_event.wait(timeout=self.timeout):
                return True
            logging.warning(
                "Timeout for ACK seq=%d, retry %d/%d",
                seq, attempt + 1, self.max_retries)

        raise TimeoutError(
            f"Failed to get ACK for seq={seq} "
            f"after {self.max_retries} retries")

    def _listen_for_acks(self):
        """Listen for ACK packets from the server."""
        def handle_packet(pkt):
            if is_valid_packet(pkt):
                parsed = parse_payload(bytes(pkt[Raw].load))
                if parsed and parsed['type'] == TYPE_ACK:
                    if parsed['seq'] == self.expected_ack_seq:
                        self.ack_event.set()

        sniff(filter="icmp", prn=handle_packet,
              stop_filter=lambda _: self.stop_sniff.is_set(),
              timeout=self.timeout * self.max_retries * 2)


class ICMPFileServer:
    """Server for receiving files via ICMP packets."""

    def __init__(self, output_dir='.', timeout=60):
        self.output_dir = output_dir
        self.timeout = timeout
        self.received_chunks = {}
        self.filename = None
        self.total_chunks = 0
        self.stop_event = threading.Event()

    def start(self):
        """Start listening for incoming ICMP file transfers."""
        logging.info(
            "ICMP File Server started, listening for transfers...")
        os.makedirs(self.output_dir, exist_ok=True)
        sniff(filter="icmp", prn=self._handle_packet,
              stop_filter=lambda _: self.stop_event.is_set(),
              timeout=self.timeout)
        logging.info("ICMP File Server stopped")

    def stop(self):
        """Stop the server."""
        self.stop_event.set()

    def _handle_packet(self, pkt):
        """Process an incoming ICMP packet."""
        if not is_valid_packet(pkt):
            return

        parsed = parse_payload(bytes(pkt[Raw].load))
        if not parsed:
            return

        src_ip = pkt[IP].src
        pkt_type = parsed['type']
        seq = parsed['seq']

        if pkt_type == TYPE_METADATA:
            total, name = decode_metadata(parsed['data'])
            if total is not None:
                self.total_chunks = total
                self.filename = name
                self.received_chunks = {}
                logging.info(
                    "Receiving file: %s (%d chunks)", name, total)
            self._send_ack(src_ip, seq)

        elif pkt_type == TYPE_DATA:
            self.received_chunks[seq] = parsed['data']
            logging.info(
                "Received chunk %d/%d", seq, self.total_chunks)
            self._send_ack(src_ip, seq)

        elif pkt_type == TYPE_FIN:
            self._send_ack(src_ip, seq)
            self._reassemble_file()
            self.stop_event.set()

    def _send_ack(self, dest_ip, seq):
        """Send an ACK packet back to the client."""
        pkt = build_icmp_packet(dest_ip, TYPE_ACK, seq)
        send(pkt, verbose=False)

    def _reassemble_file(self):
        """Reassemble received chunks into a file."""
        if not self.filename:
            logging.error("No filename received, cannot reassemble")
            return

        output_path = os.path.join(self.output_dir, self.filename)
        missing = []
        with open(output_path, 'wb') as f:
            for i in range(1, self.total_chunks + 1):
                if i in self.received_chunks:
                    f.write(self.received_chunks[i])
                else:
                    missing.append(i)

        if missing:
            logging.warning(
                "File saved with %d missing chunks: %s",
                len(missing), missing)
        else:
            logging.info("File saved successfully: %s", output_path)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s')

    parser = argparse.ArgumentParser(
        description='Transfer files through ICMP packets using scapy')
    subparsers = parser.add_subparsers(dest='mode', help='Operating mode')

    client_parser = subparsers.add_parser('client', help='Send a file')
    client_parser.add_argument(
        '--dest', required=True, help='Destination IP address')
    client_parser.add_argument(
        '--file', required=True, help='File path to send')
    client_parser.add_argument(
        '--payload-size', type=int, default=512,
        help='Max ICMP payload size in bytes (default: 512)')
    client_parser.add_argument(
        '--interval', type=float, default=0.05,
        help='Interval between packets in seconds (default: 0.05)')
    client_parser.add_argument(
        '--timeout', type=float, default=2.0,
        help='ACK timeout in seconds (default: 2.0)')
    client_parser.add_argument(
        '--max-retries', type=int, default=5,
        help='Max retransmission attempts per packet (default: 5)')

    server_parser = subparsers.add_parser('server', help='Receive files')
    server_parser.add_argument(
        '--output-dir', default='.',
        help='Directory to save received files (default: .)')
    server_parser.add_argument(
        '--timeout', type=float, default=60,
        help='Server listen timeout in seconds (default: 60)')

    args = parser.parse_args()

    if args.mode == 'client':
        client = ICMPFileClient(
            dest_ip=args.dest,
            payload_size=args.payload_size,
            interval=args.interval,
            timeout=args.timeout,
            max_retries=args.max_retries)
        client.send_file(args.file)

    elif args.mode == 'server':
        server = ICMPFileServer(
            output_dir=args.output_dir,
            timeout=args.timeout)
        server.start()

    else:
        parser.print_help()
