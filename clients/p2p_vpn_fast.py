#!/usr/bin/env python3
"""
P2P VPN FAST - Optimized for low latency gaming

This is a simplified version that sends packets directly via UDP
without double encryption or JSON overhead.

Usage:
    Host:   python p2p_vpn_fast.py --host
    Friend: python p2p_vpn_fast.py --connect <host-ip>:<port>
"""

import ctypes
import sys
import os
import struct
import socket
import threading
import argparse
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
    print("  ERROR: Run as Administrator!")
    print("=" * 60)
    sys.exit(1)

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

# STUN for NAT traversal
STUN_SERVER = "84.247.170.241"
STUN_PORT = 3478
MAGIC_COOKIE = 0x2112A442


class WinTun:
    """Minimal WinTun wrapper"""
    
    def __init__(self):
        dll_path = os.path.join(os.path.dirname(__file__), 'wintun.dll')
        if not os.path.exists(dll_path):
            print("ERROR: wintun.dll not found!")
            sys.exit(1)
        
        self.wintun = ctypes.CDLL(dll_path)
        self._setup()
        self.adapter = None
        self.session = None
        
    def _setup(self):
        self.wintun.WintunCreateAdapter.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
        self.wintun.WintunCreateAdapter.restype = ctypes.c_void_p
        self.wintun.WintunCloseAdapter.argtypes = [ctypes.c_void_p]
        self.wintun.WintunStartSession.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        self.wintun.WintunStartSession.restype = ctypes.c_void_p
        self.wintun.WintunEndSession.argtypes = [ctypes.c_void_p]
        self.wintun.WintunReceivePacket.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        self.wintun.WintunReceivePacket.restype = ctypes.POINTER(ctypes.c_ubyte)
        self.wintun.WintunReleaseReceivePacket.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.wintun.WintunAllocateSendPacket.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        self.wintun.WintunAllocateSendPacket.restype = ctypes.POINTER(ctypes.c_ubyte)
        self.wintun.WintunSendPacket.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    
    def create(self, name="P2P VPN"):
        self.adapter = self.wintun.WintunCreateAdapter(name, "P2P", None)
        if not self.adapter:
            raise Exception("Failed to create adapter")
        self.session = self.wintun.WintunStartSession(self.adapter, 0x400000)
        if not self.session:
            raise Exception("Failed to start session")
    
    def recv(self):
        size = wintypes.DWORD()
        ptr = self.wintun.WintunReceivePacket(self.session, ctypes.byref(size))
        if not ptr:
            return None
        data = bytes(ptr[:size.value])
        self.wintun.WintunReleaseReceivePacket(self.session, ptr)
        return data
    
    def send(self, data):
        ptr = self.wintun.WintunAllocateSendPacket(self.session, len(data))
        if ptr:
            ctypes.memmove(ptr, data, len(data))
            self.wintun.WintunSendPacket(self.session, ptr)
    
    def close(self):
        if self.session:
            self.wintun.WintunEndSession(self.session)
        if self.adapter:
            self.wintun.WintunCloseAdapter(self.adapter)


def stun_get_external(sock):
    """Get external IP:port via STUN"""
    txn_id = os.urandom(12)
    msg = struct.pack('!HHI', 0x0001, 0, MAGIC_COOKIE) + txn_id
    
    try:
        sock.sendto(msg, (STUN_SERVER, STUN_PORT))
        sock.settimeout(3)
        data, _ = sock.recvfrom(1024)
        sock.settimeout(0.001)  # Fast non-blocking for game packets
        
        offset = 20
        msg_len = struct.unpack('!H', data[2:4])[0]
        
        while offset < 20 + msg_len:
            attr_type, attr_len = struct.unpack('!HH', data[offset:offset+4])
            attr_val = data[offset+4:offset+4+attr_len]
            
            if attr_type == 0x0020:  # XOR-MAPPED-ADDRESS
                port = struct.unpack('!H', attr_val[2:4])[0] ^ (MAGIC_COOKIE >> 16)
                ip = struct.unpack('!I', attr_val[4:8])[0] ^ MAGIC_COOKIE
                return socket.inet_ntoa(struct.pack('!I', ip)), port
            
            offset += 4 + attr_len + (4 - attr_len % 4) % 4
    except:
        pass
    return None, None


class FastVPN:
    """Ultra-low latency P2P VPN"""
    
    def __init__(self, secret="minecraft"):
        # Single encryption layer
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'fastvpn',
            iterations=50000,  # Reduced iterations for speed
        )
        key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
        self.cipher = Fernet(key)
        
        self.sock = None
        self.tun = None
        self.peer_addr = None
        self.my_vpn_ip = None
        self.peer_vpn_ip = None
        self.running = False
        
        # Packet stats
        self.packets_sent = 0
        self.packets_recv = 0
    
    def start_host(self):
        """Start as host"""
        print("\n[FastVPN] Starting as HOST...")
        
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', 0))
        
        # Get external address
        ext_ip, ext_port = stun_get_external(self.sock)
        if not ext_ip:
            print("[ERROR] STUN failed!")
            return
        
        # Setup TUN
        self.tun = WinTun()
        self.tun.create("Minecraft LAN")
        
        # Assign VPN IPs
        self.my_vpn_ip = "10.147.1.1"
        self.peer_vpn_ip = "10.147.1.2"
        
        os.system(f'netsh interface ip set address "Minecraft LAN" static {self.my_vpn_ip} 255.255.255.0')
        
        print(f"\n{'='*50}")
        print(f"  VPN Ready!")
        print(f"  Your VPN IP: {self.my_vpn_ip}")
        print(f"{'='*50}")
        print(f"\n  Friend runs:")
        print(f"  python p2p_vpn_fast.py --connect {ext_ip}:{ext_port}")
        print(f"\n  Then in Minecraft, Open to LAN")
        print(f"  Friend connects to: {self.my_vpn_ip}:<LAN port>")
        print(f"{'='*50}\n")
        
        self.running = True
        
        # Wait for peer
        print("[*] Waiting for friend to connect...")
        self.sock.settimeout(60)
        try:
            while not self.peer_addr:
                try:
                    data, addr = self.sock.recvfrom(2048)
                    decrypted = self.cipher.decrypt(data)
                    if decrypted == b'HELLO':
                        self.peer_addr = addr
                        # Send response with peer's VPN IP
                        self.sock.sendto(self.cipher.encrypt(b'WELCOME:' + self.peer_vpn_ip.encode()), addr)
                        print(f"[+] Friend connected from {addr[0]}:{addr[1]}")
                        print(f"[+] Friend's VPN IP: {self.peer_vpn_ip}")
                except socket.timeout:
                    print("[!] Timeout waiting for friend")
                    return
        except Exception as e:
            print(f"[!] Error: {e}")
            return
        
        self.sock.settimeout(0.001)
        self._run_loops()
    
    def start_client(self, host_addr):
        """Connect to host"""
        print(f"\n[FastVPN] Connecting to {host_addr}...")
        
        host_ip, host_port = host_addr.rsplit(':', 1)
        host_port = int(host_port)
        
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', 0))
        
        # Do STUN to punch hole
        stun_get_external(self.sock)
        
        # Setup TUN
        self.tun = WinTun()
        self.tun.create("Minecraft LAN")
        
        self.peer_addr = (host_ip, host_port)
        
        # Send hello (multiple times for hole punching)
        print("[*] Punching NAT hole...")
        self.sock.settimeout(5)
        
        for i in range(10):
            self.sock.sendto(self.cipher.encrypt(b'HELLO'), self.peer_addr)
            try:
                data, addr = self.sock.recvfrom(2048)
                decrypted = self.cipher.decrypt(data)
                if decrypted.startswith(b'WELCOME:'):
                    self.my_vpn_ip = decrypted.split(b':')[1].decode()
                    self.peer_vpn_ip = "10.147.1.1"
                    print(f"[+] Connected!")
                    break
            except socket.timeout:
                continue
        else:
            print("[!] Failed to connect - NAT may be too strict")
            return
        
        os.system(f'netsh interface ip set address "Minecraft LAN" static {self.my_vpn_ip} 255.255.255.0')
        
        print(f"\n{'='*50}")
        print(f"  Connected!")
        print(f"  Your VPN IP: {self.my_vpn_ip}")
        print(f"  Host VPN IP: {self.peer_vpn_ip}")
        print(f"{'='*50}")
        print(f"\n  In Minecraft Direct Connect:")
        print(f"  {self.peer_vpn_ip}:<LAN port host showed>")
        print(f"{'='*50}\n")
        
        self.running = True
        self.sock.settimeout(0.001)
        self._run_loops()
    
    def _run_loops(self):
        """Run send/receive loops"""
        
        # TUN -> UDP (send to peer)
        def tun_to_udp():
            while self.running:
                try:
                    pkt = self.tun.recv()
                    if pkt and self.peer_addr:
                        encrypted = self.cipher.encrypt(pkt)
                        self.sock.sendto(encrypted, self.peer_addr)
                        self.packets_sent += 1
                except:
                    pass
        
        # UDP -> TUN (receive from peer)
        def udp_to_tun():
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(65535)
                    if addr == self.peer_addr:
                        pkt = self.cipher.decrypt(data)
                        if len(pkt) >= 20:  # Valid IP packet
                            self.tun.send(pkt)
                            self.packets_recv += 1
                except socket.timeout:
                    pass
                except:
                    pass
        
        # Stats display
        def show_stats():
            while self.running:
                time.sleep(5)
                print(f"[Stats] Sent: {self.packets_sent} | Recv: {self.packets_recv}")
        
        t1 = threading.Thread(target=tun_to_udp, daemon=True)
        t2 = threading.Thread(target=udp_to_tun, daemon=True)
        t3 = threading.Thread(target=show_stats, daemon=True)
        
        t1.start()
        t2.start()
        t3.start()
        
        print("[*] VPN running. Press Ctrl+C to stop.\n")
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[*] Shutting down...")
            self.running = False
            self.tun.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', action='store_true')
    parser.add_argument('--connect', type=str)
    parser.add_argument('--secret', default='minecraft-fast')
    args = parser.parse_args()
    
    if not args.host and not args.connect:
        print("Usage:")
        print("  Host:   python p2p_vpn_fast.py --host")
        print("  Client: python p2p_vpn_fast.py --connect <ip:port>")
        sys.exit(1)
    
    vpn = FastVPN(args.secret)
    
    if args.host:
        vpn.start_host()
    else:
        vpn.start_client(args.connect)


if __name__ == '__main__':
    main()
