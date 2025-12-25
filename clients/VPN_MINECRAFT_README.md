# P2P VPN for Minecraft - Setup Guide

## Quick Start

### Step 1: Download WinTun Driver
1. Go to https://www.wintun.net/
2. Download the latest release
3. Extract `wintun.dll` (from `bin/amd64/` folder) to `clients/` folder

### Step 2: Run as Administrator
**IMPORTANT**: Right-click PowerShell → "Run as Administrator"

### Step 3: Start VPN

**Player 1 (Host):**
```powershell
cd C:\Users\Java\p2p-stun-toolkit
.\.venv\Scripts\python.exe clients\p2p_vpn.py --host
```

You'll see output like:
```
P2P VPN READY!
Your VPN IP: 10.147.1.5
Share this with friend: 84.123.45.67:12345
```

**Player 2 (Friend):**
```powershell
python p2p_vpn.py --connect 84.123.45.67:12345
```

### Step 4: Play Minecraft!

**Host:**
1. Open Minecraft
2. Start a singleplayer world
3. Press Esc → "Open to LAN"
4. Note the port number (e.g., 52345)

**Friend:**
1. Open Minecraft
2. Multiplayer → Direct Connect
3. Enter: `10.147.1.5:52345` (Host's VPN IP + LAN port)
4. Join!

## Options

```
--host              Start as host
--connect <ip:port> Connect to host
--network <name>    Custom network name (both players must match)
--secret <key>      Custom secret key (both players must match)
```

## Troubleshooting

### "wintun.dll not found"
Download from https://www.wintun.net/ and place in `clients/` folder

### "Access Denied" / "Run as Administrator"
Right-click terminal → Run as Administrator

### "Connection Failed"
- Both players need compatible NAT types
- Try having the other person host
- Check if STUN server (84.247.170.241:3478) is reachable

### "Can't see LAN world"
1. Make sure VPN IPs are in same subnet (10.147.x.x)
2. Check Windows Firewall - allow Minecraft through
3. Disable any VPNs (ZeroTier, Hamachi, etc.)

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                        PLAYER 1                              │
│  ┌───────────┐    ┌─────────────┐    ┌──────────────────┐  │
│  │ Minecraft │───▶│ WinTun TAP  │───▶│  P2P Mesh Net    │──┼──┐
│  │  Server   │    │ 10.147.1.5  │    │  (STUN Punched)  │  │  │
│  └───────────┘    └─────────────┘    └──────────────────┘  │  │
└─────────────────────────────────────────────────────────────┘  │
                                                                  │
                            Internet (Direct P2P)                 │
                                                                  │
┌─────────────────────────────────────────────────────────────┐  │
│                        PLAYER 2                              │  │
│  ┌───────────┐    ┌─────────────┐    ┌──────────────────┐  │  │
│  │ Minecraft │◀───│ WinTun TAP  │◀───│  P2P Mesh Net    │◀─┼──┘
│  │  Client   │    │ 10.147.1.6  │    │  (STUN Punched)  │  │
│  └───────────┘    └─────────────┘    └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

1. WinTun creates a virtual network adapter
2. Minecraft thinks it's on a real LAN (10.147.0.0/16)
3. IP packets are encrypted and sent over P2P mesh
4. STUN hole-punching bypasses NAT (no port forwarding needed!)

## Comparison to Other Solutions

| Feature | P2P VPN | Hamachi | ZeroTier |
|---------|---------|---------|----------|
| Port Forwarding | ❌ No | ❌ No | ❌ No |
| Account Required | ❌ No | ✅ Yes | ✅ Yes |
| Relay Servers | ❌ No | ✅ Yes | ✅ Yes |
| Privacy | ✅ Direct | ⚠️ Via LogMeIn | ⚠️ Via ZT |
| Latency | ⭐ Best | Good | Good |
| Works on Strict NAT | ⚠️ Maybe | ✅ Yes | ✅ Yes |
