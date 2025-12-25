#!/usr/bin/env python3
"""
P2P Connection Test using STUN
Run this on two different devices/networks to test NAT traversal

Usage:
  Device 1: python p2p_stun_test.py --mode server
  Device 2: python p2p_stun_test.py --mode client --peer-ip <IP> --peer-port <PORT>
"""

import asyncio
import socket
import struct
import os
import sys
import argparse
import json
from datetime import datetime

STUN_SERVER = "84.247.170.241"
STUN_PORT = 3478
MAGIC_COOKIE = 0x2112A442

def create_stun_request():
    msg_type = 0x0001  # Binding Request
    msg_length = 0
    transaction_id = os.urandom(12)
    header = struct.pack('!HHI', msg_type, msg_length, MAGIC_COOKIE) + transaction_id
    return header, transaction_id

def parse_stun_response(data, transaction_id):
    if len(data) < 20:
        return None
    
    msg_type, msg_length, magic = struct.unpack('!HHI', data[:8])
    if data[8:20] != transaction_id:
        return None
    
    result = {}
    offset = 20
    while offset < 20 + msg_length:
        if offset + 4 > len(data):
            break
        attr_type, attr_length = struct.unpack('!HH', data[offset:offset+4])
        attr_value = data[offset+4:offset+4+attr_length]
        
        if attr_type == 0x0020:  # XOR-MAPPED-ADDRESS
            xor_port = struct.unpack('!H', attr_value[2:4])[0] ^ (MAGIC_COOKIE >> 16)
            xor_ip = struct.unpack('!I', attr_value[4:8])[0] ^ MAGIC_COOKIE
            result['ip'] = socket.inet_ntoa(struct.pack('!I', xor_ip))
            result['port'] = xor_port
        
        offset += 4 + attr_length + (4 - attr_length % 4) % 4
    
    return result

async def get_external_address(sock):
    """Get external IP and port via STUN"""
    request, transaction_id = create_stun_request()
    
    loop = asyncio.get_event_loop()
    await loop.sock_sendto(sock, request, (STUN_SERVER, STUN_PORT))
    
    try:
        data, _ = await asyncio.wait_for(
            loop.sock_recvfrom(sock, 1024),
            timeout=5
        )
        return parse_stun_response(data, transaction_id)
    except asyncio.TimeoutError:
        return None

async def run_server_mode(local_port):
    """Server mode - wait for peer connections"""
    print(f"\n🚀 P2P STUN Test - SERVER MODE")
    print("=" * 50)
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', local_port))
    sock.setblocking(False)
    
    print(f"✅ Listening on local port: {local_port}")
    
    # Get external address via STUN
    print(f"🔍 Contacting STUN server: {STUN_SERVER}:{STUN_PORT}")
    external = await get_external_address(sock)
    
    if not external:
        print("❌ Failed to get external address from STUN")
        return
    
    print(f"\n📋 Your External Address:")
    print(f"   IP:   {external['ip']}")
    print(f"   Port: {external['port']}")
    
    print(f"\n📱 Share this with the other device:")
    print(f"   python p2p_stun_test.py --mode client --peer-ip {external['ip']} --peer-port {external['port']}")
    
    print(f"\n⏳ Waiting for peer connection...")
    print("-" * 50)
    
    loop = asyncio.get_event_loop()
    
    # Keep refreshing STUN binding and wait for peer
    while True:
        try:
            # Refresh STUN binding every 25 seconds
            refresh_task = asyncio.create_task(asyncio.sleep(25))
            recv_task = asyncio.create_task(
                asyncio.wait_for(loop.sock_recvfrom(sock, 1024), timeout=30)
            )
            
            done, pending = await asyncio.wait(
                {refresh_task, recv_task},
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in pending:
                task.cancel()
            
            if recv_task in done:
                try:
                    data, addr = recv_task.result()
                    msg = data.decode('utf-8', errors='ignore')
                    
                    if msg.startswith("HELLO:"):
                        peer_name = msg.split(":")[1]
                        print(f"\n🎉 CONNECTED! Peer: {peer_name} from {addr[0]}:{addr[1]}")
                        
                        # Send response
                        response = f"ACK:Server-{datetime.now().strftime('%H:%M:%S')}"
                        await loop.sock_sendto(sock, response.encode(), addr)
                        print(f"✅ Sent acknowledgment to peer")
                        
                        # Chat mode
                        print(f"\n💬 Chat mode (type messages, Ctrl+C to exit):")
                        await chat_loop(sock, addr)
                        break
                    else:
                        print(f"📨 Received from {addr}: {msg}")
                except:
                    pass
            else:
                # Refresh STUN binding
                await get_external_address(sock)
                print(".", end="", flush=True)
                
        except Exception as e:
            print(f"\nError: {e}")

async def run_client_mode(peer_ip, peer_port, local_port):
    """Client mode - connect to peer"""
    print(f"\n🚀 P2P STUN Test - CLIENT MODE")
    print("=" * 50)
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', local_port))
    sock.setblocking(False)
    
    print(f"✅ Local port: {local_port}")
    
    # Get our external address
    print(f"🔍 Getting external address via STUN...")
    external = await get_external_address(sock)
    
    if external:
        print(f"   Our external: {external['ip']}:{external['port']}")
    
    print(f"\n🔗 Connecting to peer: {peer_ip}:{peer_port}")
    
    loop = asyncio.get_event_loop()
    peer_addr = (peer_ip, peer_port)
    
    # Send connection attempts (hole punching)
    for attempt in range(10):
        msg = f"HELLO:Client-{datetime.now().strftime('%H:%M:%S')}"
        await loop.sock_sendto(sock, msg.encode(), peer_addr)
        print(f"   Attempt {attempt + 1}/10 - Sent HELLO")
        
        try:
            data, addr = await asyncio.wait_for(
                loop.sock_recvfrom(sock, 1024),
                timeout=2
            )
            msg = data.decode('utf-8', errors='ignore')
            
            if msg.startswith("ACK:"):
                print(f"\n🎉 CONNECTED! Server: {msg.split(':')[1]} at {addr[0]}:{addr[1]}")
                
                # Chat mode
                print(f"\n💬 Chat mode (type messages, Ctrl+C to exit):")
                await chat_loop(sock, addr)
                return True
                
        except asyncio.TimeoutError:
            continue
    
    print(f"\n❌ Could not connect to peer after 10 attempts")
    print("   This may be due to:")
    print("   - Symmetric NAT on either end")
    print("   - Firewall blocking UDP")
    print("   - Incorrect peer address")
    return False

async def chat_loop(sock, peer_addr):
    """Simple chat between peers"""
    loop = asyncio.get_event_loop()
    
    async def receive_messages():
        while True:
            try:
                data, addr = await loop.sock_recvfrom(sock, 1024)
                msg = data.decode('utf-8', errors='ignore')
                print(f"\n📨 Peer: {msg}")
                print("You: ", end="", flush=True)
            except:
                break
    
    # Start receiver
    recv_task = asyncio.create_task(receive_messages())
    
    try:
        while True:
            # Simple input (blocking, but works for demo)
            print("You: ", end="", flush=True)
            msg = await loop.run_in_executor(None, input)
            if msg.lower() in ('quit', 'exit', 'q'):
                break
            await loop.sock_sendto(sock, msg.encode(), peer_addr)
    except KeyboardInterrupt:
        pass
    finally:
        recv_task.cancel()
    
    print("\n👋 Chat ended")

def main():
    global STUN_SERVER
    
    parser = argparse.ArgumentParser(description='P2P STUN Connection Test')
    parser.add_argument('--mode', choices=['server', 'client'], required=True,
                        help='Run as server (wait for connection) or client (connect to peer)')
    parser.add_argument('--peer-ip', help='Peer external IP (client mode only)')
    parser.add_argument('--peer-port', type=int, help='Peer external port (client mode only)')
    parser.add_argument('--local-port', type=int, default=12345, help='Local UDP port (default: 12345)')
    parser.add_argument('--stun-server', default=STUN_SERVER, help=f'STUN server (default: {STUN_SERVER})')
    
    args = parser.parse_args()
    STUN_SERVER = args.stun_server
    
    if args.mode == 'client':
        if not args.peer_ip or not args.peer_port:
            print("❌ Client mode requires --peer-ip and --peer-port")
            sys.exit(1)
        asyncio.run(run_client_mode(args.peer_ip, args.peer_port, args.local_port))
    else:
        asyncio.run(run_server_mode(args.local_port))

if __name__ == "__main__":
    main()
