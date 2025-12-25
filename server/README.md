# STUN Server Setup Guide

## Quick Install (Ubuntu)

```bash
sudo bash install.sh
```

## Manual Installation

### 1. Install Coturn
```bash
sudo apt-get update
sudo apt-get install -y coturn
```

### 2. Enable Service
```bash
sudo sed -i 's/#TURNSERVER_ENABLED=1/TURNSERVER_ENABLED=1/' /etc/default/coturn
```

### 3. Configure
Copy `turnserver.conf` to `/etc/turnserver.conf` and edit:
- Replace `84.247.170.241` with your server's public IP
- Adjust other settings as needed

### 4. Open Firewall
```bash
# UFW
sudo ufw allow 3478/udp
sudo ufw allow 3478/tcp
sudo ufw allow 3479/udp
sudo ufw allow 3479/tcp

# Or iptables
sudo iptables -A INPUT -p udp --dport 3478 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 3479 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 3478 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 3479 -j ACCEPT
```

### 5. Start Service
```bash
sudo systemctl restart coturn
sudo systemctl enable coturn
```

### 6. Verify
```bash
sudo systemctl status coturn
```

## Full RFC 5780 Support

For complete NAT behavior discovery (like Google's STUN), you need **two public IP addresses**:

```conf
listening-ip=IP_ADDRESS_1
listening-ip=IP_ADDRESS_2
```

With only one IP, basic STUN works but CHANGE-REQUEST tests won't function.

## Adding TURN Relay

To enable TURN (relay for symmetric NAT):

1. Remove `stun-only` from config
2. Add authentication:
```conf
lt-cred-mech
user=myuser:mypassword
```

3. Restart: `sudo systemctl restart coturn`

## TLS/DTLS (Secure)

For encrypted connections:

1. Get SSL certificate (Let's Encrypt):
```bash
sudo certbot certonly --standalone -d stun.yourdomain.com
```

2. Add to config:
```conf
tls-listening-port=5349
cert=/etc/letsencrypt/live/stun.yourdomain.com/fullchain.pem
pkey=/etc/letsencrypt/live/stun.yourdomain.com/privkey.pem
```

3. Remove `no-tls` and `no-dtls`

## Troubleshooting

### Check logs
```bash
journalctl -u coturn -f
```

### Test locally
```bash
apt-get install stun-client
stun localhost
```

### Check ports
```bash
ss -tulnp | grep turnserver
```

### Common Issues

| Issue | Solution |
|-------|----------|
| Port already in use | Stop other services on 3478 |
| Permission denied | Check proc-user/proc-group |
| No response | Check firewall rules |
| RFC5780 not working | Need 2 public IPs |
