# Astra Web Access

Astra uses one browser origin for the desktop, phone, and tablet UI. The Vite
development server listens on the Mac's network interfaces and proxies
relative `/api/...` requests to the local backend at `127.0.0.1:8000`.

## Start, status, and stop

From the repository root:

```bash
./scripts/astra_web_start.sh
./scripts/astra_web_status.sh
./scripts/astra_web_stop.sh
```

The start command prevents duplicate canonical tmux sessions, waits for both
the backend and the frontend `/api/health` proxy, and prints local, LAN, and
available Tailscale URLs. It does not expose the backend directly for normal
browser use.

## Same-Wi-Fi access

Open the printed LAN URL, for example `http://<current-mac-lan-ip>:5173`.
Do not use `127.0.0.1` or `localhost` on a phone or tablet: those names refer
to the phone or tablet itself. Find the current Mac address with:

```bash
ipconfig getifaddr en0 || ipconfig getifaddr en1
curl -sS http://127.0.0.1:5173/api/health
```

The browser should call `/api/health` on the frontend origin, not port 8000.

## Tailscale access

If Tailscale is active, use the printed Tailscale IP or the approved MagicDNS
hostname on port 5173. For a MagicDNS hostname, set its host in the start
environment before launching:

```bash
ASTRA_VITE_ALLOWED_HOSTS=mac-name.tailnet-name.ts.net ./scripts/astra_web_start.sh
```

Keep Astra on the private Tailscale network. Do not add public router ports.

## Configuration

The default browser API base is relative `/api`. For a deliberate direct API
diagnostic only, set `ASTRA_UI_API_BASE_URL`. The Vite proxy target is
`ASTRA_VITE_API_TARGET` and defaults to `http://127.0.0.1:8000`.

Direct cross-origin API access is disabled by default beyond loopback. Add
specific origins with `ASTRA_EXTRA_CORS_ORIGINS` or an explicit
`ASTRA_CORS_ORIGIN_REGEX` only when a controlled diagnostic requires it.

## Troubleshooting

1. Run `./scripts/astra_web_status.sh`.
2. Confirm only one listener exists with `lsof -nP -iTCP:5173 -sTCP:LISTEN` and `lsof -nP -iTCP:8000 -sTCP:LISTEN`.
3. Confirm `curl -sS http://127.0.0.1:5173/api/health` returns JSON.
4. If LAN access fails, verify the Mac and device share Wi-Fi and macOS firewall rules permit the selected private network.
5. If Tailscale access fails, verify `tailscale status`, MagicDNS, and `ASTRA_VITE_ALLOWED_HOSTS`.
6. Restart with the canonical start command instead of starting a second backend or frontend manually.

## Future private web application

For production-like private deployment, use HTTPS and a reverse proxy such as
Caddy or Nginx in front of a static frontend and `/api` backend. Add
authentication, role-based access, secure secret storage, process supervision,
restart-on-failure, health monitoring, backups, audit logging, and separate
development/staging/production environments before a private beta. Do not
publish Astra directly to the public internet from this development setup.
