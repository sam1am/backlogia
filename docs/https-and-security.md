# HTTPS & Security

- [HTTPS Access](#https-access)
- [Authentication](#authentication)

---

## HTTPS Access

Enable HTTPS access via a Caddy reverse proxy. This is useful for:
- Using the bookmarklet from HTTPS sites (avoids mixed-content blocking)
- Accessing Backlogia from other devices on your network

### Enable HTTPS

Add to your `.env` file:
```bash
COMPOSE_PROFILES=https
```

Then restart:
```bash
docker compose down && docker compose up -d --build
```

### Access URLs

| URL | Scope |
|-----|-------|
| `https://backlogia.localhost` | Local machine only |
| `https://backlogia.local` | Any device on your network (requires mDNS) |

### Network Access (backlogia.local)

On **macOS**, Docker runs in a VM and can't broadcast mDNS directly. Run this helper script in a separate terminal:
```bash
./scripts/advertise-mdns.sh
```

On **Linux** hosts, mDNS is advertised automatically via Avahi.

### Trusting the Certificate

Caddy generates a self-signed certificate using its own internal CA. Browsers will show a security warning until you trust this CA. Trusting it is **required** for PWA install support (service workers need a valid certificate).

Run the included script to trust the certificate automatically:
```bash
./scripts/trust-caddy-cert.sh
```

This adds Caddy's root CA to your system trust store. Restart your browser afterward. The script supports macOS, Linux, and Windows (via Git Bash).

You can also trust it manually:
- **macOS**: `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ./data/caddy_data/caddy/pki/authorities/local/root.crt`
- **Linux**: Copy `./data/caddy_data/caddy/pki/authorities/local/root.crt` to `/usr/local/share/ca-certificates/` and run `sudo update-ca-certificates`
- **Windows (PowerShell, run as Administrator)**: `certutil -addstore -f Root .\data\caddy_data\caddy\pki\authorities\local\root.crt`

---

## Authentication

Backlogia runs without authentication by default. If you're exposing your instance beyond localhost, you can enable single-user authentication to protect all routes.

### Enable Authentication

Add to your `.env` file:
```bash
ENABLE_AUTH=true
```

Then restart the container (or application). On first visit you'll be prompted to create an owner account — this is the only account allowed on the instance.

| Setting | Default | Description |
|---------|---------|-------------|
| `ENABLE_AUTH` | `false` | Set to `true` to require login |
| `SESSION_EXPIRY_DAYS` | `30` | How long sessions last before requiring re-login |

A session secret key is generated automatically and persisted in the database. You can logout from the Settings page.
