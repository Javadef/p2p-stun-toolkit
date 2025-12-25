#!/usr/bin/env python3
"""
STUN Client Test - Tests your STUN server
Usage: python stun_test.py [stun_server] [port]
"""

import asyncio
import socket
import struct
import os
import sys

# STUN Message Types
BINDING_REQUEST = 0x0001
BINDING_RESPONSE = 0x0101

# STUN Attributes
MAPPED_ADDRESS = 0x0001
XOR_MAPPED_ADDRESS = 0x0020
SOFTWARE = 0x8022

MAGIC_COOKIE = 0x2112A442

def create_stun_request():
    """Create a STUN Binding Request"""
    msg_type = BINDING_REQUEST
    msg_length = 0
    magic_cookie = MAGIC_COOKIE
    transaction_id = os.urandom(12)
    
    header = struct.pack('!HHI', msg_type, msg_length, magic_cookie) + transaction_id
    return header, transaction_id

def parse_stun_response(data, transaction_id):
    """Parse STUN Binding Response"""
    if len(data) < 20:
        return None, "Response too short"
    
    msg_type, msg_length, magic = struct.unpack('!HHI', data[:8])
    resp_transaction_id = data[8:20]
    
    if resp_transaction_id != transaction_id:
        return None, "Transaction ID mismatch"
    
    if msg_type != BINDING_RESPONSE:
        return None, f"Unexpected message type: {msg_type}"
    
    # Parse attributes
    result = {}
    offset = 20
    while offset < 20 + msg_length:
        if offset + 4 > len(data):
            break
        attr_type, attr_length = struct.unpack('!HH', data[offset:offset+4])
        attr_value = data[offset+4:offset+4+attr_length]
        
        if attr_type == XOR_MAPPED_ADDRESS:
            family = attr_value[1]
            xor_port = struct.unpack('!H', attr_value[2:4])[0] ^ (MAGIC_COOKIE >> 16)
            if family == 0x01:  # IPv4
                xor_ip_bytes = struct.unpack('!I', attr_value[4:8])[0] ^ MAGIC_COOKIE
                xor_ip = socket.inet_ntoa(struct.pack('!I', xor_ip_bytes))
                result['external_ip'] = xor_ip
                result['external_port'] = xor_port
        
        elif attr_type == MAPPED_ADDRESS:
            family = attr_value[1]
            port = struct.unpack('!H', attr_value[2:4])[0]
            if family == 0x01:  # IPv4
                ip = socket.inet_ntoa(attr_value[4:8])
                result['mapped_ip'] = ip
                result['mapped_port'] = port
        
        elif attr_type == SOFTWARE:
            result['server_software'] = attr_value.decode('utf-8', errors='ignore').strip('\x00')
        
        # Move to next attribute (4-byte aligned)
        offset += 4 + attr_length + (4 - attr_length % 4) % 4
    
    return result, None

async def test_stun_server(server, port=3478, timeout=5):
    """Test STUN server and return external IP"""
    print(f"\n🔍 Testing STUN server: {server}:{port}")
    print("-" * 50)
    
    try:
        # Create UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.setblocking(False)
        
        # Create and send STUN request
        request, transaction_id = create_stun_request()
        
        loop = asyncio.get_event_loop()
        await loop.sock_sendto(sock, request, (server, port))
        print(f"✅ Sent STUN Binding Request")
        
        # Wait for response
        try:
            data, addr = await asyncio.wait_for(
                loop.sock_recvfrom(sock, 1024),
                timeout=timeout
            )
            print(f"✅ Received response from {addr[0]}:{addr[1]}")
            
            # Parse response
            result, error = parse_stun_response(data, transaction_id)
            if error:
                print(f"❌ Error: {error}")
                return None
            
            print(f"\n📋 Results:")
            if 'external_ip' in result:
                print(f"   External IP:   {result['external_ip']}")
                print(f"   External Port: {result['external_port']}")
            if 'server_software' in result:
                print(f"   Server:        {result['server_software']}")
            
            return result
            
        except asyncio.TimeoutError:
            print(f"❌ Timeout - No response from server")
            return None
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return None
    finally:
        sock.close()

async def compare_stun_servers():
    """Compare multiple STUN servers"""
    servers = [
        ("84.247.170.241", 3478, "Your Server"),
        ("stun.l.google.com", 19302, "Google"),
        ("stun1.l.google.com", 19302, "Google 1"),
    ]
    
    results = []
    for server, port, name in servers:
        print(f"\n{'='*50}")
        print(f"📡 {name}")
        result = await test_stun_server(server, port)
        if result:
            results.append((name, result))
    
    # Summary
    print(f"\n{'='*50}")
    print("📊 SUMMARY")
    print("="*50)
    for name, result in results:
        ip = result.get('external_ip', 'N/A')
        port = result.get('external_port', 'N/A')
        print(f"  {name:15} → {ip}:{port}")
    
    if results:
        ips = set(r.get('external_ip') for _, r in results)
        if len(ips) == 1:
            print(f"\n✅ All servers report same external IP: {ips.pop()}")
        else:
            print(f"\n⚠️  Different IPs detected (possible symmetric NAT)")

async def main():
    if len(sys.argv) > 1:
        server = sys.argv[1]
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 3478
        await test_stun_server(server, port)
    else:
        await compare_stun_servers()

if __name__ == "__main__":
    asyncio.run(main())
