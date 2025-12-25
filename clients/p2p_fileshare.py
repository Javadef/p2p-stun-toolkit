#!/usr/bin/env python3
"""
P2P File Sharing using Mesh Network
Share files directly with friends without a server!
"""

import asyncio
import os
import sys
import json
import base64
import hashlib
from pathlib import Path
from mesh_network import MeshNetwork
from typing import Dict, Optional

CHUNK_SIZE = 32000  # ~32KB chunks (fits in UDP packet after encryption)


class P2PFileShare:
    def __init__(self, mesh: MeshNetwork, download_dir: str = "./downloads"):
        self.mesh = mesh
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        
        # Track ongoing transfers
        self.incoming: Dict[str, dict] = {}  # file_id -> {chunks, total, name, size}
        self.shared_files: Dict[str, str] = {}  # file_id -> path
        
        # Override message handler
        self._original_handler = mesh.on_message
        mesh.on_message = self._handle_message
    
    def _handle_message(self, from_ip: str, data):
        if isinstance(data, dict) and data.get('app') == 'fileshare':
            msg_type = data.get('type')
            
            if msg_type == 'file_offer':
                self._on_file_offer(from_ip, data)
            elif msg_type == 'file_request':
                asyncio.create_task(self._on_file_request(from_ip, data))
            elif msg_type == 'file_chunk':
                self._on_file_chunk(from_ip, data)
            elif msg_type == 'file_list':
                self._on_file_list(from_ip, data)
        elif self._original_handler:
            self._original_handler(from_ip, data)
    
    async def share_file(self, filepath: str):
        """Share a file with all peers"""
        path = Path(filepath)
        if not path.exists():
            print(f"❌ File not found: {filepath}")
            return
        
        file_id = hashlib.md5(f"{path.name}{path.stat().st_size}{os.urandom(4).hex()}".encode()).hexdigest()[:16]
        self.shared_files[file_id] = str(path.absolute())
        
        # Broadcast file offer
        await self.mesh.broadcast({
            'app': 'fileshare',
            'type': 'file_offer',
            'file_id': file_id,
            'name': path.name,
            'size': path.stat().st_size
        })
        
        print(f"📤 Sharing: {path.name} ({self._format_size(path.stat().st_size)})")
        print(f"   File ID: {file_id}")
    
    def _on_file_offer(self, from_ip: str, data: dict):
        """Handle incoming file offer"""
        file_id = data.get('file_id')
        name = data.get('name')
        size = data.get('size')
        
        print(f"\n📥 File offered from {from_ip}:")
        print(f"   Name: {name}")
        print(f"   Size: {self._format_size(size)}")
        print(f"   To download: /download {file_id}")
        
        # Store offer info
        self.incoming[file_id] = {
            'from': from_ip,
            'name': name,
            'size': size,
            'chunks': {},
            'total_chunks': (size + CHUNK_SIZE - 1) // CHUNK_SIZE
        }
    
    async def request_file(self, file_id: str):
        """Request a file from peer"""
        if file_id not in self.incoming:
            print(f"❌ Unknown file ID: {file_id}")
            return
        
        info = self.incoming[file_id]
        print(f"⬇️ Requesting: {info['name']}...")
        
        # Request file
        await self.mesh.send(info['from'], {
            'app': 'fileshare',
            'type': 'file_request',
            'file_id': file_id
        })
    
    async def _on_file_request(self, from_ip: str, data: dict):
        """Handle file request - send file chunks"""
        file_id = data.get('file_id')
        
        if file_id not in self.shared_files:
            return
        
        filepath = self.shared_files[file_id]
        print(f"📤 Sending file to {from_ip}...")
        
        with open(filepath, 'rb') as f:
            chunk_num = 0
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                
                await self.mesh.send(from_ip, {
                    'app': 'fileshare',
                    'type': 'file_chunk',
                    'file_id': file_id,
                    'chunk_num': chunk_num,
                    'data': base64.b64encode(chunk).decode(),
                    'is_last': len(chunk) < CHUNK_SIZE
                })
                
                chunk_num += 1
                await asyncio.sleep(0.01)  # Small delay to not overwhelm
        
        print(f"✅ File sent: {chunk_num} chunks")
    
    def _on_file_chunk(self, from_ip: str, data: dict):
        """Handle incoming file chunk"""
        file_id = data.get('file_id')
        chunk_num = data.get('chunk_num')
        chunk_data = base64.b64decode(data.get('data'))
        is_last = data.get('is_last', False)
        
        if file_id not in self.incoming:
            return
        
        info = self.incoming[file_id]
        info['chunks'][chunk_num] = chunk_data
        
        # Progress
        received = len(info['chunks'])
        total = info['total_chunks']
        pct = (received / total) * 100 if total > 0 else 0
        print(f"\r⬇️ Downloading {info['name']}: {pct:.1f}% ({received}/{total})", end='')
        
        # Check if complete
        if is_last or received >= total:
            self._save_file(file_id)
    
    def _save_file(self, file_id: str):
        """Save completed file"""
        info = self.incoming[file_id]
        filepath = self.download_dir / info['name']
        
        # Sort chunks and write
        with open(filepath, 'wb') as f:
            for i in sorted(info['chunks'].keys()):
                f.write(info['chunks'][i])
        
        print(f"\n✅ Downloaded: {filepath}")
        del self.incoming[file_id]
    
    async def list_shared(self):
        """List all shared files"""
        print("\n📂 Your shared files:")
        for file_id, path in self.shared_files.items():
            p = Path(path)
            print(f"   [{file_id}] {p.name} ({self._format_size(p.stat().st_size)})")
    
    async def request_list(self):
        """Request file list from peers"""
        await self.mesh.broadcast({
            'app': 'fileshare',
            'type': 'file_list_request'
        })
    
    def _on_file_list(self, from_ip: str, data: dict):
        """Handle file list from peer"""
        files = data.get('files', [])
        print(f"\n📂 Files from {from_ip}:")
        for f in files:
            print(f"   [{f['id']}] {f['name']} ({self._format_size(f['size'])})")
    
    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='P2P File Sharing')
    parser.add_argument('--network', '-n', default='file-share', help='Network name')
    parser.add_argument('--secret', '-s', default='share-secret-123', help='Network secret')
    parser.add_argument('--port', '-p', type=int, default=0, help='Local port')
    parser.add_argument('--connect', '-c', help='Connect to peer (ip:port)')
    parser.add_argument('--download-dir', '-d', default='./downloads', help='Download directory')
    
    args = parser.parse_args()
    
    # Create mesh network
    mesh = MeshNetwork(args.network, args.secret, args.port)
    await mesh.start()
    
    # Create file share
    fs = P2PFileShare(mesh, args.download_dir)
    
    # Connect to peer if specified
    if args.connect:
        ip, port = args.connect.split(':')
        print(f"\n🔗 Connecting to {ip}:{port}...")
        await mesh.connect_to_peer(ip, int(port))
        await asyncio.sleep(2)
    else:
        print(f"\n📱 Share with friends:")
        print(f"   python p2p_fileshare.py -n {args.network} -s {args.secret} -c {mesh.external_ip}:{mesh.external_port}")
    
    print("\n" + "="*50)
    print("📁 P2P FILE SHARING")
    print("="*50)
    print("Commands:")
    print("  /share <path>      - Share a file")
    print("  /download <id>     - Download a file")
    print("  /list              - List your shared files")
    print("  /peers             - Show connected peers")
    print("  /quit              - Exit")
    print("="*50)
    
    loop = asyncio.get_event_loop()
    while True:
        try:
            cmd = await loop.run_in_executor(None, input, "\n> ")
            
            if cmd.startswith('/share '):
                path = cmd.split(' ', 1)[1].strip()
                await fs.share_file(path)
            
            elif cmd.startswith('/download '):
                file_id = cmd.split(' ', 1)[1].strip()
                await fs.request_file(file_id)
            
            elif cmd.startswith('/list'):
                await fs.list_shared()
            
            elif cmd.startswith('/peers'):
                print("\n📋 Connected peers:")
                for p in mesh.get_peers():
                    print(f"   {p.virtual_ip} - {p.external_ip}:{p.external_port}")
            
            elif cmd.startswith('/quit'):
                break
            
            elif cmd.strip():
                await mesh.broadcast(cmd)
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
    
    print("\n👋 Goodbye!")


if __name__ == "__main__":
    asyncio.run(main())
