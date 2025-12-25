# P2P STUN Toolkit

A complete STUN server setup and P2P networking toolkit for NAT traversal.

## 🌐 What's Included

### Server Setup
- **Coturn STUN/TURN server configuration** for Ubuntu
- Firewall rules and setup scripts
- Production-ready configs

### Client Applications
- **STUN Test** - Test your STUN server
- **P2P Chat** - Direct peer-to-peer messaging
- **Mesh Network** - ZeroTier-like virtual LAN
- **P2P Games** - Multiplayer games through NAT
- **P2P File Sharing** - Direct file transfers

## 🚀 Quick Start

### 1. Test STUN Server
```bash
python clients/stun_test.py
```

### 2. P2P Chat Between Two Devices

**Device 1:**
```bash
python clients/p2p_chat.py --mode server
```

**Device 2:**
```bash
python clients/p2p_chat.py --mode client --peer-ip <IP> --peer-port <PORT>
```

### 3. Mesh Network (ZeroTier-like)

**Host:**
```bash
python clients/mesh_network.py -n "my-network" -s "secret123"
```

**Join:**
```bash
python clients/mesh_network.py -n "my-network" -s "secret123" -c <IP:PORT>
```

## 📁 Project Structure

```
p2p-stun-toolkit/
├── server/
│   ├── turnserver.conf      # Coturn configuration
│   ├── install.sh           # Ubuntu setup script
│   └── README.md            # Server setup guide
├── clients/
│   ├── stun_test.py         # STUN server tester
│   ├── p2p_chat.py          # Simple P2P chat
│   ├── mesh_network.py      # Virtual LAN
│   ├── p2p_game.py          # P2P games
│   └── p2p_fileshare.py     # File sharing
├── docs/
│   └── NAT_TYPES.md         # NAT traversal explanation
└── README.md
```

## 🔧 Server Requirements

- Ubuntu 20.04+ or Debian 11+
- Public IP address
- Ports 3478-3479 (UDP/TCP) open

## 📱 Client Requirements

- Python 3.8+
- `pip install cryptography`

## 🔍 Check Your NAT Type First!

Before using P2P features, check your NAT type using [go-nats](https://github.com/pion/go-nats):

```bash
# Install
go install github.com/pion/go-nats@latest

# Or build from source
git clone https://github.com/pion/go-nats
cd go-nats
go build

# Run with your STUN server
./go-nats -s 84.247.170.241:3478
```

Example output:
```json
{
  "isNatted": true,
  "mappingBehavior": 0,
  "filteringBehavior": 2,
  "portPreservation": true,
  "natType": "Port-restricted cone NAT",
  "externalIP": "213.230.82.108"
}
```

> ⏱️ Note: Depending on your NAT type, detection may take ~8 seconds.

## 🌍 NAT Compatibility

| NAT Type | P2P Support | go-nats filteringBehavior |
|----------|-------------|---------------------------|
| Full Cone | ✅ Full | 0 |
| Restricted Cone | ✅ Full | 1 |
| Port-Restricted Cone | ✅ Full | 2 |
| Symmetric | ⚠️ Limited (needs TURN relay) | 3 |

## 🔐 Security Features

- **Fernet/AES encryption** for mesh network
- **No authentication** on STUN (public, like Google's)
- Optional **TURN authentication** for relay

## 📖 How It Works

```
┌─────────────┐                    ┌─────────────┐
│  Client A   │                    │  Client B   │
│  Behind NAT │                    │  Behind NAT │
└──────┬──────┘                    └──────┬──────┘
       │                                  │
       │  1. STUN Request                 │
       ├─────────────────┐                │
       │                 ▼                │
       │         ┌──────────────┐         │
       │         │ STUN Server  │         │
       │         │ 84.247.170.241│        │
       │         └──────────────┘         │
       │                 │                │
       │  2. Returns     │                │
       │  External IP    │                │
       ◄─────────────────┘                │
       │                                  │
       │  3. Exchange IPs (via signaling) │
       ├──────────────────────────────────►
       │                                  │
       │  4. UDP Hole Punching            │
       ◄──────────────────────────────────►
       │                                  │
       │  5. Direct P2P Connection! 🎉    │
       ◄══════════════════════════════════►
```

## 🎮 Use Cases

- **Gaming** - Host multiplayer games without port forwarding
- **File Sharing** - Transfer files directly between devices
- **Chat** - Private encrypted messaging
- **VPN Alternative** - Create virtual LANs for remote work
- **IoT** - Connect devices behind different NATs

## 📝 License

MIT License - Use freely!

## 🤝 Contributing

Pull requests welcome! Ideas:
- Voice/Video chat
- Screen sharing
- More games
- Mobile apps
