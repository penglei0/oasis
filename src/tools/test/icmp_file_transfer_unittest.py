import unittest
import struct
import os
import tempfile
from unittest.mock import patch, MagicMock
from scapy.all import IP, ICMP, Raw

from src.tools.icmp_file_transfer import (
    MAGIC, HEADER_SIZE, ICMP_IDENT,
    TYPE_METADATA, TYPE_DATA, TYPE_ACK, TYPE_FIN,
    build_payload, parse_payload, encode_metadata, decode_metadata,
    is_valid_packet, build_icmp_packet,
    ICMPFileClient, ICMPFileServer
)


class TestBuildPayload(unittest.TestCase):

    def test_build_data_payload(self):
        data = b'hello world'
        payload = build_payload(TYPE_DATA, 1, data)
        self.assertEqual(payload[:4], MAGIC)
        self.assertEqual(payload[9:], data)
        self.assertEqual(len(payload), HEADER_SIZE + len(data))

    def test_build_ack_payload(self):
        payload = build_payload(TYPE_ACK, 5)
        self.assertEqual(len(payload), HEADER_SIZE)
        self.assertEqual(payload[:4], MAGIC)

    def test_build_fin_payload(self):
        payload = build_payload(TYPE_FIN, 10)
        self.assertEqual(len(payload), HEADER_SIZE)

    def test_build_metadata_payload(self):
        meta = encode_metadata(3, 'test.txt')
        payload = build_payload(TYPE_METADATA, 0, meta)
        self.assertTrue(payload.startswith(MAGIC))
        self.assertEqual(len(payload), HEADER_SIZE + len(meta))


class TestParsePayload(unittest.TestCase):

    def test_parse_valid_data_payload(self):
        payload = build_payload(TYPE_DATA, 42, b'test data')
        result = parse_payload(payload)
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], TYPE_DATA)
        self.assertEqual(result['seq'], 42)
        self.assertEqual(result['data'], b'test data')

    def test_parse_too_short(self):
        self.assertIsNone(parse_payload(b'\x00\x00'))

    def test_parse_empty(self):
        self.assertIsNone(parse_payload(b''))

    def test_parse_wrong_magic(self):
        payload = b'XXXX' + struct.pack('!BI', TYPE_DATA, 1)
        self.assertIsNone(parse_payload(payload))

    def test_parse_empty_data_field(self):
        payload = build_payload(TYPE_ACK, 0)
        result = parse_payload(payload)
        self.assertIsNotNone(result)
        self.assertEqual(result['data'], b'')

    def test_roundtrip_all_types(self):
        for pkt_type in [TYPE_METADATA, TYPE_DATA, TYPE_ACK, TYPE_FIN]:
            for seq in [0, 1, 100, 65535]:
                data = os.urandom(64)
                payload = build_payload(pkt_type, seq, data)
                result = parse_payload(payload)
                self.assertEqual(result['type'], pkt_type)
                self.assertEqual(result['seq'], seq)
                self.assertEqual(result['data'], data)


class TestMetadataEncoding(unittest.TestCase):

    def test_encode_decode_roundtrip(self):
        encoded = encode_metadata(10, 'test_file.bin')
        total, name = decode_metadata(encoded)
        self.assertEqual(total, 10)
        self.assertEqual(name, 'test_file.bin')

    def test_decode_short_data(self):
        total, name = decode_metadata(b'\x00')
        self.assertIsNone(total)
        self.assertIsNone(name)

    def test_encode_zero_chunks(self):
        encoded = encode_metadata(0, 'empty.txt')
        total, name = decode_metadata(encoded)
        self.assertEqual(total, 0)
        self.assertEqual(name, 'empty.txt')


class TestIsValidPacket(unittest.TestCase):

    def test_valid_packet(self):
        payload = build_payload(TYPE_DATA, 1, b'test')
        pkt = IP(dst="127.0.0.1") / ICMP(type=8, id=ICMP_IDENT) / Raw(load=payload)
        self.assertTrue(is_valid_packet(pkt))

    def test_wrong_icmp_id(self):
        payload = build_payload(TYPE_DATA, 1, b'test')
        pkt = IP(dst="127.0.0.1") / ICMP(type=8, id=0x0000) / Raw(load=payload)
        self.assertFalse(is_valid_packet(pkt))

    def test_no_raw_layer(self):
        pkt = IP(dst="127.0.0.1") / ICMP(type=8, id=ICMP_IDENT)
        self.assertFalse(is_valid_packet(pkt))

    def test_wrong_magic(self):
        pkt = IP(dst="127.0.0.1") / ICMP(type=8, id=ICMP_IDENT) / Raw(load=b'XXXXabcdefgh')
        self.assertFalse(is_valid_packet(pkt))

    def test_payload_too_short(self):
        pkt = IP(dst="127.0.0.1") / ICMP(type=8, id=ICMP_IDENT) / Raw(load=b'OA')
        self.assertFalse(is_valid_packet(pkt))


class TestBuildIcmpPacket(unittest.TestCase):

    def test_packet_has_correct_layers(self):
        pkt = build_icmp_packet('10.0.0.1', TYPE_DATA, 5, b'hello')
        self.assertTrue(pkt.haslayer(IP))
        self.assertTrue(pkt.haslayer(ICMP))
        self.assertTrue(pkt.haslayer(Raw))

    def test_packet_icmp_id(self):
        pkt = build_icmp_packet('10.0.0.1', TYPE_DATA, 1, b'x')
        self.assertEqual(pkt[ICMP].id, ICMP_IDENT)

    def test_packet_dest_ip(self):
        pkt = build_icmp_packet('192.168.1.100', TYPE_ACK, 0)
        self.assertEqual(pkt[IP].dst, '192.168.1.100')

    def test_packet_payload_parseable(self):
        pkt = build_icmp_packet('10.0.0.1', TYPE_DATA, 7, b'data')
        parsed = parse_payload(bytes(pkt[Raw].load))
        self.assertEqual(parsed['type'], TYPE_DATA)
        self.assertEqual(parsed['seq'], 7)
        self.assertEqual(parsed['data'], b'data')


class TestICMPFileClient(unittest.TestCase):

    @patch('src.tools.icmp_file_transfer.sniff')
    @patch('src.tools.icmp_file_transfer.send')
    def test_send_file_small(self, mock_send, mock_sniff):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            f.write(b'Hello, World!')
            temp_path = f.name

        try:
            client = ICMPFileClient(
                dest_ip='192.168.1.1', payload_size=512,
                timeout=0.1, max_retries=1)

            def auto_ack(pkt, **kwargs):
                client.ack_event.set()
            mock_send.side_effect = auto_ack

            client.send_file(temp_path)
            # metadata + 1 data chunk + FIN = 3 sends
            self.assertEqual(mock_send.call_count, 3)
        finally:
            os.unlink(temp_path)

    @patch('src.tools.icmp_file_transfer.sniff')
    @patch('src.tools.icmp_file_transfer.send')
    def test_send_file_multiple_chunks(self, mock_send, mock_sniff):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as f:
            f.write(b'A' * 100)
            temp_path = f.name

        try:
            client = ICMPFileClient(
                dest_ip='10.0.0.2', payload_size=20,
                timeout=0.1, max_retries=1, interval=0)

            def auto_ack(pkt, **kwargs):
                client.ack_event.set()
            mock_send.side_effect = auto_ack

            client.send_file(temp_path)
            # payload_size=20, header=9, data_per_chunk=11
            # ceil(100 / 11) = 10 chunks
            # sends = 1 metadata + 10 data + 1 FIN = 12
            self.assertEqual(mock_send.call_count, 12)
        finally:
            os.unlink(temp_path)

    @patch('src.tools.icmp_file_transfer.sniff')
    @patch('src.tools.icmp_file_transfer.send')
    def test_send_file_with_small_buffer(self, mock_send, mock_sniff):
        """Verify streaming works with a buffer smaller than total chunks."""
        with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as f:
            f.write(b'B' * 100)
            temp_path = f.name

        try:
            client = ICMPFileClient(
                dest_ip='10.0.0.2', payload_size=20,
                timeout=0.1, max_retries=1, interval=0,
                buffer_size=3)

            sent_data = []

            def auto_ack(pkt, **kwargs):
                if pkt.haslayer(Raw):
                    parsed = parse_payload(bytes(pkt[Raw].load))
                    if parsed and parsed['type'] == TYPE_DATA:
                        sent_data.append(parsed['data'])
                client.ack_event.set()
            mock_send.side_effect = auto_ack

            client.send_file(temp_path)
            # Same 10 chunks, but loaded 3 at a time
            # sends = 1 metadata + 10 data + 1 FIN = 12
            self.assertEqual(mock_send.call_count, 12)
            # Verify all data was sent correctly
            self.assertEqual(b''.join(sent_data), b'B' * 100)
        finally:
            os.unlink(temp_path)

    def test_payload_size_too_small(self):
        with self.assertRaises(ValueError):
            ICMPFileClient(dest_ip='10.0.0.1', payload_size=5)

    @patch('src.tools.icmp_file_transfer.sniff')
    @patch('src.tools.icmp_file_transfer.send')
    def test_retry_on_timeout(self, mock_send, mock_sniff):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            f.write(b'x')
            temp_path = f.name

        try:
            client = ICMPFileClient(
                dest_ip='10.0.0.1', timeout=0.05, max_retries=3)

            mock_send.side_effect = lambda pkt, **kw: None

            with self.assertRaises(TimeoutError):
                client.send_file(temp_path)
            # First packet (metadata) retried 3 times
            self.assertEqual(mock_send.call_count, 3)
        finally:
            os.unlink(temp_path)


class TestICMPFileServer(unittest.TestCase):

    @patch('src.tools.icmp_file_transfer.send')
    def test_reassemble_file(self, mock_send):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = ICMPFileServer(output_dir=tmpdir)
            server.total_chunks = 2
            server.filename = 'test.txt'
            server.received_chunks = {1: b'Hello, ', 2: b'World!'}

            server._reassemble_file()

            output_path = os.path.join(tmpdir, 'test.txt')
            self.assertTrue(os.path.exists(output_path))
            with open(output_path, 'rb') as f:
                self.assertEqual(f.read(), b'Hello, World!')

    @patch('src.tools.icmp_file_transfer.send')
    def test_handle_metadata_packet(self, mock_send):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = ICMPFileServer(output_dir=tmpdir)
            meta = encode_metadata(3, 'test.bin')
            payload = build_payload(TYPE_METADATA, 0, meta)
            pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                   / ICMP(type=8, id=ICMP_IDENT)
                   / Raw(load=payload))

            server._handle_packet(pkt)

            self.assertEqual(server.filename, 'test.bin')
            self.assertEqual(server.total_chunks, 3)
            mock_send.assert_called_once()

    @patch('src.tools.icmp_file_transfer.send')
    def test_handle_data_packet(self, mock_send):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = ICMPFileServer(output_dir=tmpdir)
            server.total_chunks = 2
            server.filename = 'data.bin'

            payload = build_payload(TYPE_DATA, 1, b'chunk1')
            pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                   / ICMP(type=8, id=ICMP_IDENT)
                   / Raw(load=payload))
            server._handle_packet(pkt)

            self.assertEqual(server.received_chunks[1], b'chunk1')
            mock_send.assert_called_once()

    @patch('src.tools.icmp_file_transfer.send')
    def test_handle_fin_triggers_reassembly(self, mock_send):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = ICMPFileServer(output_dir=tmpdir)
            server.total_chunks = 1
            server.filename = 'fin_test.txt'
            server.received_chunks = {1: b'data'}

            payload = build_payload(TYPE_FIN, 2)
            pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                   / ICMP(type=8, id=ICMP_IDENT)
                   / Raw(load=payload))
            server._handle_packet(pkt)

            self.assertTrue(server.stop_event.is_set())
            output_path = os.path.join(tmpdir, 'fin_test.txt')
            self.assertTrue(os.path.exists(output_path))
            with open(output_path, 'rb') as f:
                self.assertEqual(f.read(), b'data')

    @patch('src.tools.icmp_file_transfer.send')
    def test_ignores_invalid_packet(self, mock_send):
        server = ICMPFileServer()
        pkt = IP(dst="127.0.0.1") / ICMP(type=8, id=0x0000) / Raw(load=b'garbage')
        server._handle_packet(pkt)
        mock_send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
