import unittest
import struct
import os
import tempfile
from unittest.mock import patch
from scapy.all import IP, ICMP, Raw

from src.tools.icmp_file_transfer import (
    MAGIC, HEADER_SIZE, ICMP_IDENT,
    ICMP_ECHO_REQUEST, ICMP_ECHO_REPLY,
    TYPE_METADATA, TYPE_DATA, TYPE_ACK, TYPE_FIN,
    build_payload, parse_payload, encode_metadata, decode_metadata,
    is_valid_packet, build_icmp_packet, sanitize_filename,
    suppress_kernel_icmp_echo,
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

    def test_decode_invalid_utf8(self):
        data = struct.pack('!I', 5) + b'\xff\xfe'
        total, name = decode_metadata(data)
        self.assertIsNone(total)
        self.assertIsNone(name)


class TestSanitizeFilename(unittest.TestCase):

    def test_simple_filename(self):
        self.assertEqual(sanitize_filename('test.txt'), 'test.txt')

    def test_path_traversal(self):
        self.assertIsNone(sanitize_filename('../etc/passwd'))

    def test_absolute_path(self):
        self.assertIsNone(sanitize_filename('/etc/passwd'))

    def test_dotdot_in_name(self):
        self.assertIsNone(sanitize_filename('..secret'))

    def test_empty_name(self):
        self.assertIsNone(sanitize_filename(''))

    def test_windows_path(self):
        self.assertIsNone(sanitize_filename('..\\secret.txt'))


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

    def test_default_echo_request(self):
        pkt = build_icmp_packet('10.0.0.1', TYPE_DATA, 1)
        self.assertEqual(pkt[ICMP].type, ICMP_ECHO_REQUEST)

    def test_echo_reply_type(self):
        pkt = build_icmp_packet(
            '10.0.0.1', TYPE_ACK, 1, icmp_type=ICMP_ECHO_REPLY)
        self.assertEqual(pkt[ICMP].type, ICMP_ECHO_REPLY)


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

    def test_ack_listener_parses_ack(self):
        """Verify _listen_for_acks correctly sets event on valid ACK."""
        client = ICMPFileClient(
            dest_ip='10.0.0.1', timeout=0.1, max_retries=1)
        client.expected_ack_seq = 5

        ack_payload = build_payload(TYPE_ACK, 5)
        ack_pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                   / ICMP(type=0, id=ICMP_IDENT)
                   / Raw(load=ack_payload))

        def fake_sniff(**kwargs):
            kwargs['prn'](ack_pkt)

        with patch('src.tools.icmp_file_transfer.sniff',
                   side_effect=fake_sniff):
            client._listen_for_acks()

        self.assertTrue(client.ack_event.is_set())

    def test_ack_listener_ignores_wrong_seq(self):
        """Verify _listen_for_acks ignores ACK with wrong seq."""
        client = ICMPFileClient(
            dest_ip='10.0.0.1', timeout=0.1, max_retries=1)
        client.expected_ack_seq = 5

        ack_payload = build_payload(TYPE_ACK, 99)
        ack_pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                   / ICMP(type=0, id=ICMP_IDENT)
                   / Raw(load=ack_payload))

        def fake_sniff(**kwargs):
            kwargs['prn'](ack_pkt)

        with patch('src.tools.icmp_file_transfer.sniff',
                   side_effect=fake_sniff):
            client._listen_for_acks()

        self.assertFalse(client.ack_event.is_set())


class TestICMPFileServer(unittest.TestCase):

    @patch('src.tools.icmp_file_transfer.send')
    def test_progressive_write(self, mock_send):
        """Verify chunks are written progressively in order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            server = ICMPFileServer(output_dir=tmpdir)

            # Send metadata
            meta = encode_metadata(3, 'test.txt')
            meta_pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                        / ICMP(type=8, id=ICMP_IDENT)
                        / Raw(load=build_payload(TYPE_METADATA, 0, meta)))
            server._handle_packet(meta_pkt)

            # Send chunks 1, 2, 3 in order
            for i, chunk in enumerate([b'Hello, ', b'World', b'!'], 1):
                pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                       / ICMP(type=8, id=ICMP_IDENT)
                       / Raw(load=build_payload(TYPE_DATA, i, chunk)))
                server._handle_packet(pkt)

            # After chunk 3, write_cursor should be 4
            self.assertEqual(server.write_cursor, 4)

            # Send FIN
            fin_pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                       / ICMP(type=8, id=ICMP_IDENT)
                       / Raw(load=build_payload(TYPE_FIN, 4)))
            server._handle_packet(fin_pkt)

            output_path = os.path.join(tmpdir, 'test.txt')
            self.assertTrue(os.path.exists(output_path))
            with open(output_path, 'rb') as f:
                self.assertEqual(f.read(), b'Hello, World!')

    @patch('src.tools.icmp_file_transfer.send')
    def test_out_of_order_chunks_buffered(self, mock_send):
        """Verify out-of-order chunks are buffered until gap is filled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            server = ICMPFileServer(output_dir=tmpdir)

            meta = encode_metadata(3, 'ooo.bin')
            meta_pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                        / ICMP(type=8, id=ICMP_IDENT)
                        / Raw(load=build_payload(TYPE_METADATA, 0, meta)))
            server._handle_packet(meta_pkt)

            # Send chunk 2 before chunk 1
            pkt2 = (IP(src='10.0.0.1', dst='10.0.0.2')
                    / ICMP(type=8, id=ICMP_IDENT)
                    / Raw(load=build_payload(TYPE_DATA, 2, b'BB')))
            server._handle_packet(pkt2)
            # Chunk 2 buffered but not written yet
            self.assertEqual(server.write_cursor, 1)
            self.assertIn(2, server.received_chunks)

            # Now send chunk 1 — both 1 and 2 should flush
            pkt1 = (IP(src='10.0.0.1', dst='10.0.0.2')
                    / ICMP(type=8, id=ICMP_IDENT)
                    / Raw(load=build_payload(TYPE_DATA, 1, b'AA')))
            server._handle_packet(pkt1)
            self.assertEqual(server.write_cursor, 3)
            self.assertEqual(len(server.received_chunks), 0)

            # Send chunk 3 and FIN
            pkt3 = (IP(src='10.0.0.1', dst='10.0.0.2')
                    / ICMP(type=8, id=ICMP_IDENT)
                    / Raw(load=build_payload(TYPE_DATA, 3, b'CC')))
            server._handle_packet(pkt3)

            fin_pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                       / ICMP(type=8, id=ICMP_IDENT)
                       / Raw(load=build_payload(TYPE_FIN, 4)))
            server._handle_packet(fin_pkt)

            output_path = os.path.join(tmpdir, 'ooo.bin')
            with open(output_path, 'rb') as f:
                self.assertEqual(f.read(), b'AABBCC')

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
            self.assertIsNotNone(server.output_file)
            mock_send.assert_called_once()
            # Cleanup
            if server.output_file:
                server.output_file.close()

    @patch('src.tools.icmp_file_transfer.send')
    def test_invalid_metadata_no_ack(self, mock_send):
        """Verify invalid metadata does not trigger an ACK."""
        server = ICMPFileServer()
        payload = build_payload(TYPE_METADATA, 0, b'\x00')
        pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
               / ICMP(type=8, id=ICMP_IDENT)
               / Raw(load=payload))
        server._handle_packet(pkt)
        mock_send.assert_not_called()

    @patch('src.tools.icmp_file_transfer.send')
    def test_path_traversal_rejected(self, mock_send):
        """Verify path traversal filenames are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            server = ICMPFileServer(output_dir=tmpdir)
            meta = encode_metadata(1, '../evil.txt')
            payload = build_payload(TYPE_METADATA, 0, meta)
            pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                   / ICMP(type=8, id=ICMP_IDENT)
                   / Raw(load=payload))
            server._handle_packet(pkt)
            self.assertIsNone(server.filename)
            mock_send.assert_not_called()

    @patch('src.tools.icmp_file_transfer.send')
    def test_handle_data_packet(self, mock_send):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = ICMPFileServer(output_dir=tmpdir)
            server.total_chunks = 2
            server.filename = 'data.bin'
            output_path = os.path.join(tmpdir, 'data.bin')
            server.output_file = open(output_path, 'wb')

            payload = build_payload(TYPE_DATA, 1, b'chunk1')
            pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                   / ICMP(type=8, id=ICMP_IDENT)
                   / Raw(load=payload))
            server._handle_packet(pkt)

            self.assertEqual(server.write_cursor, 2)
            mock_send.assert_called_once()
            server.output_file.close()

    @patch('src.tools.icmp_file_transfer.send')
    def test_handle_fin_closes_file(self, mock_send):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = ICMPFileServer(output_dir=tmpdir)
            server.total_chunks = 1
            server.filename = 'fin_test.txt'
            output_path = os.path.join(tmpdir, 'fin_test.txt')
            server.output_file = open(output_path, 'wb')
            server.received_chunks = {1: b'data'}

            payload = build_payload(TYPE_FIN, 2)
            pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                   / ICMP(type=8, id=ICMP_IDENT)
                   / Raw(load=payload))
            server._handle_packet(pkt)

            self.assertTrue(server.stop_event.is_set())
            self.assertIsNone(server.output_file)
            with open(output_path, 'rb') as f:
                self.assertEqual(f.read(), b'data')

    @patch('src.tools.icmp_file_transfer.send')
    def test_ignores_invalid_packet(self, mock_send):
        server = ICMPFileServer()
        pkt = IP(dst="127.0.0.1") / ICMP(type=8, id=0x0000) / Raw(load=b'garbage')
        server._handle_packet(pkt)
        mock_send.assert_not_called()

    @patch('src.tools.icmp_file_transfer.send')
    def test_ack_uses_echo_reply(self, mock_send):
        """Verify ACK packets use ICMP echo-reply (type=0)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            server = ICMPFileServer(output_dir=tmpdir)
            meta = encode_metadata(1, 'ack_test.bin')
            payload = build_payload(TYPE_METADATA, 0, meta)
            pkt = (IP(src='10.0.0.1', dst='10.0.0.2')
                   / ICMP(type=8, id=ICMP_IDENT)
                   / Raw(load=payload))
            server._handle_packet(pkt)

            sent_pkt = mock_send.call_args[0][0]
            self.assertEqual(sent_pkt[ICMP].type, ICMP_ECHO_REPLY)
            if server.output_file:
                server.output_file.close()

    @patch('src.tools.icmp_file_transfer.sniff')
    @patch('src.tools.icmp_file_transfer.suppress_kernel_icmp_echo')
    def test_server_suppresses_kernel_icmp(self, mock_suppress, mock_sniff):
        """Verify server suppresses kernel echo replies on start."""
        mock_suppress.return_value = '0'
        with tempfile.TemporaryDirectory() as tmpdir:
            server = ICMPFileServer(output_dir=tmpdir, timeout=0)
            server.start()
        # Called twice: suppress on start, restore on stop
        self.assertEqual(mock_suppress.call_count, 2)
        mock_suppress.assert_any_call(True)
        # prev was '0' (not suppressed), so restore with False
        mock_suppress.assert_any_call(False)


class TestSuppressKernelIcmpEcho(unittest.TestCase):

    @patch('subprocess.run')
    @patch('builtins.open',
           unittest.mock.mock_open(read_data='0\n'))
    def test_suppress_sets_sysctl(self, mock_run):
        result = suppress_kernel_icmp_echo(True)
        self.assertEqual(result, '0')
        mock_run.assert_called_once()
        args = mock_run.call_args
        self.assertIn('net.ipv4.icmp_echo_ignore_all=1',
                       args[0][0])

    @patch('subprocess.run')
    @patch('builtins.open',
           unittest.mock.mock_open(read_data='1\n'))
    def test_restore_clears_sysctl(self, mock_run):
        result = suppress_kernel_icmp_echo(False)
        self.assertEqual(result, '1')
        mock_run.assert_called_once()
        args = mock_run.call_args
        self.assertIn('net.ipv4.icmp_echo_ignore_all=0',
                       args[0][0])

    @patch('builtins.open', side_effect=OSError("permission denied"))
    def test_returns_none_on_failure(self, mock_open):
        result = suppress_kernel_icmp_echo(True)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
