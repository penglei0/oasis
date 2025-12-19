#!/usr/bin/env python
'''
Websocket client/server

python3 -m pip install websockets netifaces -i https://pypi.tuna.tsinghua.edu.cn/simple

'''
import time
import logging
import signal
import sys
import argparse
import netifaces
from websockets.sync.client import connect
from websockets.sync.server import serve

class WebSocketClient:
    """Simple synchronous websocket client using websockets.sync.client."""
    def __init__(self, url: str):
        self.url = url
        self.ws = None

    def connect(self):
        """Establish the connection."""
        self.ws = connect(self.url)

    def send(self, message: str):
        """Send a message."""
        if self.ws:
            self.ws.send(message)

    def recv(self):
        """Receive a message."""
        if self.ws:
            return self.ws.recv()
        return None

    def close(self):
        """Close the connection."""
        if self.ws:
            self.ws.close()


class WebSocketServer:
    """Simple synchronous websocket server using websockets.sync.server."""
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def _echo_handler(self, websocket):
        """Echo back received messages."""
        try:
            for message in websocket:
                logging.info(f"Received: {message}")
                websocket.send(message)
        except Exception as e:
            logging.error(f"Connection error: {e}")

    def start(self):
        """Start the server and block until interrupted."""
        logging.info(f"Starting server on ws://{self.host}:{self.port}")
        with serve(self._echo_handler, self.host, self.port) as server:
            server.serve_forever()

def signal_handler(sig, frame):
    logging.info("Interrupt received, stopping...")
    sys.exit(0)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGINT, signal_handler)
    # Server: websocket.py -s -I eth0
    # Client: websocket.py -c ws://localhost:8765
    argparse_parser = argparse.ArgumentParser(description='WebSocket Client/Server')
    group = argparse_parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-s', '--server', action='store_true', help='Start WebSocket server')
    group.add_argument('-c', '--client', type=str, help='WebSocket client URL to connect to')
    argparse_parser.add_argument('-I', '--interface', type=str, help='Network interface for the server to bind to')
    args = argparse_parser.parse_args()
    if args.server:
        # read bond interface
        host = 'localhost'
        if args.interface:
            addrs = netifaces.ifaddresses(args.interface)
            if netifaces.AF_INET in addrs:
                host = addrs[netifaces.AF_INET][0]['addr']
            else:
                logging.error(f"No IPv4 address found for interface {args.interface}, using localhost")
        logging.info(f"Starting WebSocket server on interface {args.interface} with host {host}")
        server = WebSocketServer(host=host, port=8765)
        server.start()
    elif args.client:
        client = WebSocketClient(url=args.client)
        client.connect()
        logging.info("Connected to server")
        const_test_msg = "Hello, WebSocket Server!"
        try:
            seq = 0
            while True:
                test_msg = f"{const_test_msg} {seq}"
                client.send(test_msg)
                response = client.recv()
                logging.info(f"Received from server: {response}")
                time.sleep(1)
                seq += 1
        finally:
            client.close()
            logging.info("Connection closed")    
    logging.info("websocket APP stopped")