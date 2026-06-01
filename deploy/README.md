# AlgoForge — Hostinger VPS Deployment

This folder contains everything you need to self-host AlgoForge on your
**Hostinger VPS at 72.60.103.235** (or any Ubuntu/Debian VPS with a static IP).

## Why self-host?
Zerodha Kite Connect enforces an **IP allowlist** per developer app. Emergent's
preview environment uses a shared egress IP that's already taken by another
developer's app — Kite won't let you register the same IP twice. A self-hosted
VPS gives you a dedicated outbound IP you control.

---

## One-time setup

### 1. SSH into the VPS
```bash
ssh root@72.60.103.235
```

### 2. Install Docker
```bash
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker --version          # verify
docker compose version    # verify
```

### 3. Clone the repo
First push from Emergent → "Save to GitHub" → e.g. `dkshaikdxb-dev/AlgoForge`. Then:
```bash
cd /opt
git clone https://github.com/dkshaikdxb-dev/AlgoForge.git
cd AlgoForge
```

### 4. (Recommended) Point a domain at the VPS
Buy/use a domain (e.g. `algoforge.example.com`), point an A record at
`72.60.103.235`. **You need HTTPS** because the cookie-auth flow sets
`Secure; SameSite=Lax` cookies — plain HTTP will silently drop them.

Simplest path: put **Cloudflare** in front (free tier).
- Add the domain in Cloudflare.
- Create A record `algoforge → 72.60.103.235`, orange-cloud (proxied).
- TLS terminates at Cloudflare; backend stays HTTP internally.

Alternatively, use **Certbot** on the VPS itself (terminate TLS at Nginx). The
included `nginx.conf` already does `:80` only; add a `:443` server block if you
take this route.

### 5. Configure environment
```bash
cd /opt/AlgoForge/deploy
cp .env.production.example .env.production
nano .env.production       # fill in REACT_APP_BACKEND_URL, JWT_SECRET, ENCRYPTION_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
```

> **CRITICAL**: generate fresh secrets — don't copy the Emergent ones.
> ```
> python3 -c "import secrets; print(secrets.token_urlsafe(64))"     # JWT_SECRET
> python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # ENCRYPTION_KEY
> ```

### 6. Boot the stack
```bash
docker compose --env-file .env.production up -d --build
docker compose ps
docker compose logs -f backend     # watch boot logs
```

If healthy, hit `https://your-domain` in a browser — you should see the
AlgoForge login page.

### 7. Seed the first admin
```bash
docker compose exec backend python scripts/promote_admin.py your-email@domain.com
```
(Register the account first via the UI, then promote it.)

### 8. Update Kite developer console
- **Redirect URL**: `https://your-domain/api/brokers/zerodha/oauth/callback`
- **Postback URL** (optional, real-time order updates):
  `https://your-domain/api/brokers/zerodha/postback?token=<your-postback-secret>`
- **Allowed IPs**: `72.60.103.235`

Run the OAuth wizard at `/brokers` exactly the same way you did on the
preview environment. The wizard works identically — it just uses your
VPS's IP now, which Kite accepts.

---

## Day-2 ops

### Update from GitHub
```bash
cd /opt/AlgoForge
git pull
cd deploy
docker compose --env-file .env.production up -d --build
```

### Logs
```bash
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs --tail 100 mongo
```

### Mongo backups
```bash
docker compose exec mongo mongodump --archive=/data/db/backup-$(date +%F).archive --db algoforge
docker cp $(docker compose ps -q mongo):/data/db/backup-$(date +%F).archive ./backups/
```

### Firewall (UFW recommended)
```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

---

## Continuing development on Emergent

Keep using the Emergent preview for AI-assisted development. Save-to-GitHub
when ready → `git pull && docker compose up -d --build` on the VPS to roll
forward.

Per-environment notes:
- **Emergent preview** → `LLM_PROVIDER=emergent`, uses `EMERGENT_LLM_KEY`.
- **VPS production** → `LLM_PROVIDER=direct`, uses your OpenAI + Anthropic keys.

The code automatically picks the right provider based on `LLM_PROVIDER`, so the
same commit runs in both places.
