#!/usr/bin/env python3
"""
P2P VPN using WinTun - Play Minecraft with friends without port forwarding!

This creates a virtual network interface and tunnels traffic through P2P.
Both you and your friend will be on the same "virtual LAN" (10.147.x.x).

Requirements:
1. Download wintun.dll from https://www.wintun.net/ and place in same folder
2. Run as Administrator (required for creating network interfaces)
3. pip install cryptography

Usage:
    Host:   python p2p_vpn.py --host
    Friend: python p2p_vpn.py --connect <host-ip>:<port>
"""

import ctypes
import sys
import os
import struct
import socket
import threading
import argparse
import hashlib
import time
from ctypes import wintypes

# Check admin rights
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if not is_admin():
    print("=" * 60)
    print("  ERROR: This script requires Administrator privileges!")
    print("=" * 60)
    print("\nRight-click on your terminal and 'Run as Administrator'")
    print("Or run: Start-Process powershell -Verb runAs")
    sys.exit(1)

# Add parent for mesh_network import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from mesh_network import MeshNetwork
except ImportError:
    print("Error: mesh_network.py not found in same directory")
    sys.exit(1)

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

# ============= WinTun Interface =============

class WinTun:
    """Wrapper for WinTun driver - creates virtual network adapter"""
    
    def __init__(self):
        # Find wintun.dll
        dll_paths = [
            os.path.join(os.path.dirname(__file__), 'wintun.dll'),
            os.path.join(os.path.dirname(__file__), 'wintun', 'bin', 'amd64', 'wintun.dll'),
            'wintun.dll',
        ]
        
        dll_path = None
        for path in dll_paths:
            if os.path.exists(path):
                dll_path = path
                break
        
        if not dll_path:
            print("=" * 60)
            print("  ERROR: wintun.dll not found!")
            print("=" * 60)
            print("\nDownload from: https://www.wintun.net/")
            print("Extract and place wintun.dll in:", os.path.dirname(__file__))
            print("\nOr use the simpler alternative: p2p_vpn_simple.py")
            sys.exit(1)
        
        self.wintun = ctypes.CDLL(dll_path)
        self._setup_functions()
        self.adapter = None
        self.session = None
        self.running = False
        
    def _setup_functions(self):
        """Setup WinTun function signatures"""
        # WintunCreateAdapter
        self.wintun.WintunCreateAdapter.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
        self.wintun.WintunCreateAdapter.restype = ctypes.c_void_p
        
        # WintunCloseAdapter
        self.wintun.WintunCloseAdapter.argtypes = [ctypes.c_void_p]
        self.wintun.WintunCloseAdapter.restype = None
        
        # WintunStartSession
        self.wintun.WintunStartSession.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        self.wintun.WintunStartSession.restype = ctypes.c_void_p
        
        # WintunEndSession
        self.wintun.WintunEndSession.argtypes = [ctypes.c_void_p]
        self.wintun.WintunEndSession.restype = None
        
        # WintunReceivePacket
        self.wintun.WintunReceivePacket.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        self.wintun.WintunReceivePacket.restype = ctypes.POINTER(ctypes.c_ubyte)
        
        # WintunReleaseReceivePacket
        self.wintun.WintunReleaseReceivePacket.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.wintun.WintunReleaseReceivePacket.restype = None
        
        # WintunAllocateSendPacket
        self.wintun.WintunAllocateSendPacket.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        self.wintun.WintunAllocateSendPacket.restype = ctypes.POINTER(ctypes.c_ubyte)
        
        # WintunSendPacket
        self.wintun.WintunSendPacket.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.wintun.WintunSendPacket.restype = None
        
        # WintunGetReadWaitEvent
        self.wintun.WintunGetReadWaitEvent.argtypes = [ctypes.c_void_p]
        self.wintun.WintunGetReadWaitEvent.restype = wintypes.HANDLE
    
    def create_adapter(self, name="P2PVPN", tunnel_type="P2P"):
        """Create a new WinTun adapter"""
        self.adapter = self.wintun.WintunCreateAdapter(name, tunnel_type, None)
        if not self.adapter:
            raise Exception("Failed to create WinTun adapter. Run as Administrator!")
        return self.adapter
    
    def start_session(self, capacity=0x400000):  # 4MB ring buffer
        """Start a session for sending/receiving packets"""
        if not self.adapter:
            raise Exception("Create adapter first!")
        self.session = self.wintun.WintunStartSession(self.adapter, capacity)
        if not self.session:
            raise Exception("Failed to start WinTun session")
        self.running = True
        return self.session
    
    def receive_packet(self):
        """Receive a packet from the TUN interface"""
        if not self.session:
            return None
        packet_size = wintypes.DWORD()
        packet_ptr = self.wintun.WintunReceivePacket(self.session, ctypes.byref(packet_size))
        if not packet_ptr:
            return None
        # Copy packet data
        data = bytes(packet_ptr[:packet_size.value])
        self.wintun.WintunReleaseReceivePacket(self.session, packet_ptr)
        return data
    
    def send_packet(self, data):
        """Send a packet to the TUN interface"""
        if not self.session:
            return False
        packet_ptr = self.wintun.WintunAllocateSendPacket(self.session, len(data))
        if not packet_ptr:
            return False
        ctypes.memmove(packet_ptr, data, len(data))
        self.wintun.WintunSendPacket(self.session, packet_ptr)
        return True
    
    def get_read_event(self):
        """Get event handle for waiting on packets"""
        if not self.session:
            return None
        return self.wintun.WintunGetReadWaitEvent(self.session)
    
    def close(self):
        """Clean up adapter and session"""
        self.running = False
        if self.session:
            self.wintun.WintunEndSession(self.session)
            self.session = None
        if self.adapter:
            self.wintun.WintunCloseAdapter(self.adapter)
            self.adapter = None


# ============= P2P VPN Main Class =============

class P2PVPN:
    """P2P VPN for LAN gaming"""
    
    def __init__(self, network_name: str, secret: str):
        self.network_name = network_name
        self.secret = secret
        self.mesh = None
        self.tun = None
        self.my_vpn_ip = None
        self.peer_vpn_ips = {}  # mesh_ip -> vpn_ip
        self.running = False
        
        # Generate encryption key from secret
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'p2pvpn_salt_v1',
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
        self.fernet = Fernet(key)
    
    def _assign_vpn_ip(self, mesh_ip: str) -> str:
        """Assign a VPN IP based on mesh IP"""
        # Use last two octets of mesh IP for VPN IP
        # 10.147.x.y where x.y comes from mesh IP
        parts = mesh_ip.split('.')
        return f"10.147.{parts[2]}.{parts[3]}"
    
    def start(self, peer_address: str = None):
        """Start the P2P VPN"""
        print("\n" + "=" * 60)
        print("  P2P VPN for Minecraft - Starting...")
        print("=" * 60)
        
        # Initialize mesh network
        print("\n[1/4] Connecting to P2P mesh network...")
        self.mesh = MeshNetwork(self.network_name, self.secret)
        
        if peer_address:
            # Connect to existing network
            host, port = peer_address.rsplit(':', 1)
            self.mesh.connect_to_peer(host, int(port))
        
        self.mesh.start()
        time.sleep(2)  # Wait for STUN binding
        
        # Assign VPN IP
        self.my_vpn_ip = self._assign_vpn_ip(self.mesh.virtual_ip)
        print(f"    Mesh IP: {self.mesh.virtual_ip}")
        print(f"    VPN IP:  {self.my_vpn_ip}")
        
        # Create WinTun adapter
        print("\n[2/4] Creating virtual network adapter...")
        self.tun = WinTun()
        self.tun.create_adapter("Minecraft P2P", "P2PVPN")
        self.tun.start_session()
        print("    Adapter created: 'Minecraft P2P'")
        
        # Configure IP address using netsh
        print("\n[3/4] Configuring network...")
        os.system(f'netsh interface ip set address "Minecraft P2P" static {self.my_vpn_ip} 255.255.0.0')
        print(f"    IP Address: {self.my_vpn_ip}/16")
        
        # Register message handler
        self.mesh.on_message = self._handle_mesh_message
        
        # Start packet forwarding threads
        print("\n[4/4] Starting packet forwarding...")
        self.running = True
        
        threading.Thread(target=self._tun_to_mesh, daemon=True).start()
        threading.Thread(target=self._peer_discovery, daemon=True).start()
        
        print("\n" + "=" * 60)
        print("  P2P VPN READY!")
        print("=" * 60)
        print(f"\n  Your VPN IP: {self.my_vpn_ip}")
        print(f"  Share this with friend: {self.mesh.external_ip}:{self.mesh.external_port}")
        print("\n  In Minecraft:")
        print("    1. Host opens to LAN")
        print("    2. Friend connects using Direct Connect")
        print(f"    3. Enter: {self.my_vpn_ip}:<port shown in Minecraft>")
        print("\n  Press Ctrl+C to stop")
        print("=" * 60 + "\n")
        
        # Broadcast our presence
        self._broadcast_presence()
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
            self.stop()
    
    def _broadcast_presence(self):
        """Tell other peers our VPN IP"""
        msg = {
            'type': 'vpn_announce',
            'vpn_ip': self.my_vpn_ip,
            'mesh_ip': self.mesh.virtual_ip
        }
        self.mesh.broadcast(msg)
    
    def _handle_mesh_message(self, sender_ip: str, message: dict):
        """Handle messages from mesh network"""
        msg_type = message.get('type')
        
        if msg_type == 'vpn_announce':
            # Peer announcing their VPN IP
            vpn_ip = message.get('vpn_ip')
            mesh_ip = message.get('mesh_ip')
            if vpn_ip and mesh_ip:
                self.peer_vpn_ips[mesh_ip] = vpn_ip
                print(f"[VPN] Peer discovered: {vpn_ip} (mesh: {mesh_ip})")
                # Respond with our info
                self._broadcast_presence()
        
        elif msg_type == 'vpn_packet':
            # Encrypted IP packet from peer
            try:
                encrypted = message.get('data')
                if encrypted:
                    packet = self.fernet.decrypt(encrypted.encode())
                    self.tun.send_packet(packet)
            except Exception as e:
                pass  # Ignore decrypt errors
    
    def _tun_to_mesh(self):
        """Forward packets from TUN interface to mesh network"""
        while self.running:
            try:
                packet = self.tun.receive_packet()
                if packet and len(packet) >= 20:
                    # Parse destination IP from IPv4 header
                    dst_ip = socket.inet_ntoa(packet[16:20])
                    
                    # Find peer by VPN IP
                    target_mesh_ip = None
                    for mesh_ip, vpn_ip in self.peer_vpn_ips.items():
                        if vpn_ip == dst_ip:
                            target_mesh_ip = mesh_ip
                            break
                    
                    if target_mesh_ip:
                        # Encrypt and send via mesh
                        encrypted = self.fernet.encrypt(packet).decode()
                        self.mesh.send_to(target_mesh_ip, {
                            'type': 'vpn_packet',
                            'data': encrypted
                        })
                else:
                    time.sleep(0.001)
            except Exception as e:
                if self.running:
                    time.sleep(0.01)
    
    def _peer_discovery(self):
        """Periodically announce presence to find peers"""
        while self.running:
            self._broadcast_presence()
            time.sleep(10)
    
    def stop(self):
        """Stop the VPN"""
        self.running = False
        if self.tun:
            self.tun.close()
        if self.mesh:
            self.mesh.stop()


# ============= Main =============

def main():
    parser = argparse.ArgumentParser(description='P2P VPN for Minecraft LAN Play')
    parser.add_argument('--host', action='store_true', help='Host a new VPN network')
    parser.add_argument('--connect', type=str, help='Connect to peer (ip:port)')
    parser.add_argument('--network', type=str, default='minecraft-vpn', help='Network name')
    parser.add_argument('--secret', type=str, default='minecraft-secret-123', help='Shared secret')
    
    args = parser.parse_args()
    
    if not args.host and not args.connect:
        print("Usage:")
        print("  Host:   python p2p_vpn.py --host")
        print("  Friend: python p2p_vpn.py --connect <ip:port>")
        print("\nOptional:")
        print("  --network <name>   Network name (default: minecraft-vpn)")
        print("  --secret <key>     Shared secret (default: minecraft-secret-123)")
        sys.exit(1)
    
    vpn = P2PVPN(args.network, args.secret)
    vpn.start(peer_address=args.connect)


if __name__ == '__main__':
    main()
