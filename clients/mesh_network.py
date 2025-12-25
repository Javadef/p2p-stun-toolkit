#!/usr/bin/env python3
"""
P2P Mesh Network - ZeroTier-like Virtual LAN
Creates encrypted P2P connections between peers using STUN hole punching

Features:
- STUN-based NAT traversal
- Encrypted communication (Fernet)
- Virtual IP assignment
- Peer discovery via signaling server
- Auto-reconnection
"""

import asyncio
import socket
import struct
import os
import sys
import json
import hashlib
import base64
import time
from datetime import datetime
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Configuration
STUN_SERVER = "84.247.170.241"
STUN_PORT = 3478
MAGIC_COOKIE = 0x2112A442

@dataclass
class Peer:
    peer_id: str
    virtual_ip: str
    external_ip: str
    external_port: int
    last_seen: float
    connected: bool = False

class MeshNetwork:
    def __init__(self, network_id: str, network_secret: str, local_port: int = 0):
        self.network_id = network_id
        self.network_secret = network_secret
        self.local_port = local_port
        
        # Generate node ID from network secret + random
        self.node_id = hashlib.sha256(f"{network_secret}{os.urandom(8).hex()}".encode()).hexdigest()[:16]
        
        # Derive encryption key from network secret
        self.cipher = self._create_cipher(network_secret)
        
        # Virtual IP (10.mesh.x.x network)
        self.virtual_ip = self._generate_virtual_ip()
        
        # Peer management
        self.peers: Dict[str, Peer] = {}
        self.sock: Optional[socket.socket] = None
        self.external_ip: Optional[str] = None
        self.external_port: Optional[int] = None
        
        # Callbacks
        self.on_peer_connected = None
        self.on_peer_disconnected = None
        self.on_message = None
        
    def _create_cipher(self, secret: str) -> Fernet:
        """Create Fernet cipher from network secret"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'p2p_mesh_network',
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
        return Fernet(key)
    
    def _generate_virtual_ip(self) -> str:
        """Generate virtual IP from node ID"""
        # Use hash of node_id to generate consistent IP
        h = hashlib.md5(self.node_id.encode()).digest()
        return f"10.{self.network_id_hash()}.{h[0]}.{h[1]}"
    
    def network_id_hash(self) -> int:
        """Get network ID as number for IP generation"""
        return hashlib.md5(self.network_id.encode()).digest()[0]
    
    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data for network transmission"""
        return self.cipher.encrypt(data)
    
    def decrypt(self, data: bytes) -> bytes:
        """Decrypt data from network"""
        return self.cipher.decrypt(data)
    
    async def start(self):
        """Start the mesh network node"""
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', self.local_port))
        self.sock.settimeout(1.0)  # 1 second timeout for recvfrom
        
        self.local_port = self.sock.getsockname()[1]
        
        # Get external address via STUN
        external = await self._stun_request()
        if external:
            self.external_ip = external['ip']
            self.external_port = external['port']
        
        print(f"🌐 Mesh Network Started")
        print(f"   Network: {self.network_id}")
        print(f"   Node ID: {self.node_id}")
        print(f"   Virtual IP: {self.virtual_ip}")
        print(f"   External: {self.external_ip}:{self.external_port}")
        
        # Start background tasks
        asyncio.create_task(self._receive_loop())
        asyncio.create_task(self._keepalive_loop())
        
    async def _stun_request(self) -> Optional[dict]:
        """Get external IP via STUN"""
        msg_type = 0x0001
        transaction_id = os.urandom(12)
        header = struct.pack('!HHI', msg_type, 0, MAGIC_COOKIE) + transaction_id
        
        loop = asyncio.get_event_loop()
        # Use run_in_executor for UDP sendto (works on all platforms)
        await loop.run_in_executor(None, lambda: self.sock.sendto(header, (STUN_SERVER, STUN_PORT)))
        
        try:
            # Use run_in_executor for UDP recvfrom
            data, _ = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self.sock.recvfrom(1024)), timeout=5
            )
            
            offset = 20
            msg_length = struct.unpack('!H', data[2:4])[0]
            
            while offset < 20 + msg_length:
                attr_type, attr_length = struct.unpack('!HH', data[offset:offset+4])
                attr_value = data[offset+4:offset+4+attr_length]
                
                if attr_type == 0x0020:  # XOR-MAPPED-ADDRESS
                    xor_port = struct.unpack('!H', attr_value[2:4])[0] ^ (MAGIC_COOKIE >> 16)
                    xor_ip = struct.unpack('!I', attr_value[4:8])[0] ^ MAGIC_COOKIE
                    return {
                        'ip': socket.inet_ntoa(struct.pack('!I', xor_ip)),
                        'port': xor_port
                    }
                offset += 4 + attr_length + (4 - attr_length % 4) % 4
        except:
            pass
        return None
    
    async def _receive_loop(self):
        """Main receive loop"""
        loop = asyncio.get_event_loop()
        
        while True:
            try:
                # Use run_in_executor for UDP recvfrom (works on all platforms)
                data, addr = await loop.run_in_executor(None, lambda: self.sock.recvfrom(65535))
                await self._handle_packet(data, addr)
            except Exception as e:
                await asyncio.sleep(0.1)
    
    async def _handle_packet(self, data: bytes, addr: Tuple[str, int]):
        """Handle incoming packet"""
        try:
            # Try to decrypt (mesh traffic)
            decrypted = self.decrypt(data)
            msg = json.loads(decrypted.decode())
            
            msg_type = msg.get('type')
            
            if msg_type == 'hello':
                await self._handle_hello(msg, addr)
            elif msg_type == 'hello_ack':
                await self._handle_hello_ack(msg, addr)
            elif msg_type == 'keepalive':
                await self._handle_keepalive(msg, addr)
            elif msg_type == 'data':
                await self._handle_data(msg, addr)
            elif msg_type == 'discover':
                await self._handle_discover(msg, addr)
                
        except Exception as e:
            # Not mesh traffic or decryption failed
            pass
    
    async def _handle_hello(self, msg: dict, addr: Tuple[str, int]):
        """Handle peer hello"""
        peer_id = msg['node_id']
        virtual_ip = msg['virtual_ip']
        
        # Add/update peer
        self.peers[peer_id] = Peer(
            peer_id=peer_id,
            virtual_ip=virtual_ip,
            external_ip=addr[0],
            external_port=addr[1],
            last_seen=time.time(),
            connected=True
        )
        
        # Send acknowledgment
        ack = {
            'type': 'hello_ack',
            'node_id': self.node_id,
            'virtual_ip': self.virtual_ip,
            'peers': [asdict(p) for p in self.peers.values()]
        }
        await self._send_to(ack, addr)
        
        print(f"✅ Peer connected: {virtual_ip} ({peer_id[:8]}...)")
        
        if self.on_peer_connected:
            self.on_peer_connected(self.peers[peer_id])
    
    async def _handle_hello_ack(self, msg: dict, addr: Tuple[str, int]):
        """Handle hello acknowledgment"""
        peer_id = msg['node_id']
        virtual_ip = msg['virtual_ip']
        
        self.peers[peer_id] = Peer(
            peer_id=peer_id,
            virtual_ip=virtual_ip,
            external_ip=addr[0],
            external_port=addr[1],
            last_seen=time.time(),
            connected=True
        )
        
        # Learn about other peers
        for peer_data in msg.get('peers', []):
            if peer_data['peer_id'] != self.node_id and peer_data['peer_id'] not in self.peers:
                # Try to connect to discovered peer
                asyncio.create_task(self.connect_to_peer(
                    peer_data['external_ip'],
                    peer_data['external_port']
                ))
        
        print(f"✅ Connected to peer: {virtual_ip} ({peer_id[:8]}...)")
        
        if self.on_peer_connected:
            self.on_peer_connected(self.peers[peer_id])
    
    async def _handle_keepalive(self, msg: dict, addr: Tuple[str, int]):
        """Handle keepalive"""
        peer_id = msg['node_id']
        if peer_id in self.peers:
            self.peers[peer_id].last_seen = time.time()
            self.peers[peer_id].external_ip = addr[0]
            self.peers[peer_id].external_port = addr[1]
    
    async def _handle_data(self, msg: dict, addr: Tuple[str, int]):
        """Handle data message"""
        if self.on_message:
            self.on_message(msg.get('from_ip'), msg.get('data'))
    
    async def _handle_discover(self, msg: dict, addr: Tuple[str, int]):
        """Handle peer discovery request"""
        response = {
            'type': 'discover_response',
            'node_id': self.node_id,
            'virtual_ip': self.virtual_ip,
            'peers': [asdict(p) for p in self.peers.values()]
        }
        await self._send_to(response, addr)
    
    async def _keepalive_loop(self):
        """Send keepalives and check peer timeouts"""
        while True:
            await asyncio.sleep(10)
            
            # Refresh STUN binding
            external = await self._stun_request()
            if external:
                self.external_ip = external['ip']
                self.external_port = external['port']
            
            # Send keepalives
            keepalive = {
                'type': 'keepalive',
                'node_id': self.node_id,
                'virtual_ip': self.virtual_ip
            }
            
            for peer_id, peer in list(self.peers.items()):
                if time.time() - peer.last_seen > 60:
                    # Peer timeout
                    print(f"❌ Peer disconnected: {peer.virtual_ip}")
                    if self.on_peer_disconnected:
                        self.on_peer_disconnected(peer)
                    del self.peers[peer_id]
                else:
                    await self._send_to(keepalive, (peer.external_ip, peer.external_port))
    
    async def _send_to(self, msg: dict, addr: Tuple[str, int]):
        """Send encrypted message to address"""
        data = json.dumps(msg).encode()
        encrypted = self.encrypt(data)
        loop = asyncio.get_event_loop()
        # Use run_in_executor for UDP sendto (works on all platforms)
        await loop.run_in_executor(None, lambda: self.sock.sendto(encrypted, addr))
    
    async def connect_to_peer(self, ip: str, port: int):
        """Initiate connection to a peer"""
        hello = {
            'type': 'hello',
            'node_id': self.node_id,
            'virtual_ip': self.virtual_ip,
            'network_id': self.network_id
        }
        
        # Send multiple hello packets (hole punching)
        for _ in range(5):
            await self._send_to(hello, (ip, port))
            await asyncio.sleep(0.5)
    
    async def send(self, virtual_ip: str, data: any):
        """Send data to a peer by virtual IP"""
        for peer in self.peers.values():
            if peer.virtual_ip == virtual_ip:
                msg = {
                    'type': 'data',
                    'from_ip': self.virtual_ip,
                    'data': data
                }
                await self._send_to(msg, (peer.external_ip, peer.external_port))
                return True
        return False
    
    async def broadcast(self, data: any):
        """Broadcast data to all peers"""
        msg = {
            'type': 'data',
            'from_ip': self.virtual_ip,
            'data': data
        }
        for peer in self.peers.values():
            await self._send_to(msg, (peer.external_ip, peer.external_port))
    
    def get_peers(self) -> list:
        """Get list of connected peers"""
        return list(self.peers.values())


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='P2P Mesh Network')
    parser.add_argument('--network', '-n', default='my-network', help='Network name')
    parser.add_argument('--secret', '-s', default='shared-secret-123', help='Network secret')
    parser.add_argument('--port', '-p', type=int, default=0, help='Local port')
    parser.add_argument('--connect', '-c', help='Connect to peer (ip:port)')
    
    args = parser.parse_args()
    
    # Create mesh network
    mesh = MeshNetwork(args.network, args.secret, args.port)
    
    # Set callbacks
    def on_message(from_ip, data):
        print(f"\n📨 [{from_ip}]: {data}")
        print("You: ", end="", flush=True)
    
    mesh.on_message = on_message
    
    # Start network
    await mesh.start()
    
    # Connect to peer if specified
    if args.connect:
        ip, port = args.connect.split(':')
        print(f"\n🔗 Connecting to {ip}:{port}...")
        await mesh.connect_to_peer(ip, int(port))
    else:
        print(f"\n📱 Share with friends:")
        print(f"   python mesh_network.py -n {args.network} -s {args.secret} -c {mesh.external_ip}:{mesh.external_port}")
    
    print(f"\n💬 Chat mode (type to send to all peers):")
    print("-" * 50)
    
    # Chat loop
    loop = asyncio.get_event_loop()
    while True:
        try:
            print("You: ", end="", flush=True)
            msg = await loop.run_in_executor(None, input)
            
            if msg.lower() == '/peers':
                print(f"\n📋 Connected peers:")
                for p in mesh.get_peers():
                    print(f"   {p.virtual_ip} - {p.external_ip}:{p.external_port}")
            elif msg.lower() == '/quit':
                break
            elif msg:
                await mesh.broadcast(msg)
        except KeyboardInterrupt:
            break
    
    print("\n👋 Goodbye!")


if __name__ == "__main__":
    asyncio.run(main())
