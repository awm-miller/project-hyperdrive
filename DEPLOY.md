# Hyperdrive VPS Deployment Guide

## Prerequisites

- A VPS with Ubuntu 22.04 (any provider: DigitalOcean, Hetzner, Vultr, etc.)
- Your Gemini API key
- Your `sessions.jsonl` file (Twitter auth tokens)
- (Optional) Mullvad VPN account for IP rotation

---

## Step 1: Get a VPS

Recommended: **Hetzner** (€4/mo) or **DigitalOcean** ($6/mo)

- Ubuntu 22.04
- 1GB RAM minimum
- Any region

---

## Step 2: Connect to VPS

```bash
ssh root@YOUR_VPS_IP
```

---

## Step 3: Install Dependencies

```bash
# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh

# Install Docker Compose
apt install -y docker-compose

# Install Python
apt install -y python3-pip python3-venv git

# Install Mullvad VPN (optional but recommended)
curl -fsSLo /usr/share/keyrings/mullvad-keyring.asc https://repository.mullvad.net/deb/mullvad-keyring.asc
echo "deb [signed-by=/usr/share/keyrings/mullvad-keyring.asc] https://repository.mullvad.net/deb/stable $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/mullvad.list
apt update && apt install -y mullvad-vpn
```

---

## Step 4: Set Up Mullvad (if using)

```bash
# Login with your account number
mullvad account login YOUR_ACCOUNT_NUMBER

# Connect
mullvad connect

# Verify
mullvad status
# Should show: Connected to xx-xxx-wg-xxx
```

---

## Step 5: Upload Your Code

**From your local machine:**

```bash
# Create a zip of the project (excluding sensitive files)
# On Windows PowerShell:
Compress-Archive -Path app,deploy,docker-compose.yml,nitter.conf,requirements.txt,DEPLOY.md -DestinationPath hyperdrive.zip

# Upload to VPS
scp hyperdrive.zip root@YOUR_VPS_IP:/root/
```

**On the VPS:**

```bash
# Create app directory
mkdir -p /opt/hyperdrive
cd /opt/hyperdrive

# Unzip
apt install -y unzip
unzip /root/hyperdrive.zip -d /opt/hyperdrive/
```

---

## Step 6: Configure

```bash
cd /opt/hyperdrive

# Create .env file
cat > .env << 'EOF'
GEMINI_API_KEY=your_actual_gemini_key_here
NITTER_URL=http://localhost:8080
DOCKER_COMPOSE_PATH=/opt/hyperdrive
EOF

# Create sessions.jsonl (paste your Twitter session)
nano sessions.jsonl
# Paste your session JSON line and save (Ctrl+X, Y, Enter)
```

Your `sessions.jsonl` should look like:
```json
{"kind":"cookie","username":"your_twitter_username","id":"your_twitter_id","auth_token":"your_auth_token","ct0":"your_ct0_token"}
```

---

## Step 7: Install Python Dependencies

```bash
cd /opt/hyperdrive
pip3 install -r requirements.txt
```

---

## Step 8: Start Nitter

```bash
cd /opt/hyperdrive

# Start Nitter + Redis
docker-compose up -d

# Wait for it to start
sleep 10

# Verify Nitter is running
curl -s http://localhost:8080 | head -5
# Should show HTML
```

---

## Step 9: Start Hyperdrive

```bash
cd /opt/hyperdrive

# Load environment variables
export $(cat .env | xargs)

# Start the app
nohup uvicorn app.main:app --host 0.0.0.0 --port 3000 > app.log 2>&1 &

# Verify it's running
curl http://localhost:3000/health
# Should show: {"status":"healthy"...}
```

---

## Step 10: Access Your App

Your app is now running at: `http://YOUR_VPS_IP:3000`

### (Optional) Set up Nginx for cleaner URLs

```bash
apt install -y nginx

cat > /etc/nginx/sites-available/hyperdrive << 'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/hyperdrive /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx
```

Now accessible at: `http://YOUR_VPS_IP` (port 80)

---

## Useful Commands

```bash
# View app logs
tail -f /opt/hyperdrive/app.log

# Restart app
pkill -f uvicorn
cd /opt/hyperdrive && export $(cat .env | xargs)
nohup uvicorn app.main:app --host 0.0.0.0 --port 3000 > app.log 2>&1 &

# Restart Nitter
cd /opt/hyperdrive && docker-compose restart nitter

# Check Mullvad status
mullvad status

# Manually switch VPN country
mullvad relay set location us
mullvad reconnect --wait

# View Docker containers
docker ps

# View Nitter logs
docker-compose logs -f nitter
```

---

## Troubleshooting

### "Rate limited" errors
- Make sure Mullvad is connected: `mullvad status`
- The app should auto-rotate VPN, but you can manually switch: `mullvad relay set location de && mullvad reconnect --wait`

### Nitter not starting
- Check logs: `docker-compose logs nitter`
- Verify sessions.jsonl exists and is valid JSON

### App not responding
- Check if running: `ps aux | grep uvicorn`
- Check logs: `tail -50 /opt/hyperdrive/app.log`

### Can't connect to port 3000
- Check firewall: `ufw status`
- Allow port: `ufw allow 3000` or use Nginx on port 80

