# Mac mini local deployment

## 1. Prepare Python

Install Python 3.10+ on the Mac mini. Then open Terminal and enter this project folder.

```bash
cd /path/to/PPI
cp .env.example .env
nano .env
```

Fill `.env` with the real Feishu and LorealGPT credentials. Keep `.env` only on the Mac mini.

## 2. Start backend

```bash
cd /path/to/PPI
chmod +x start_backend_mac.sh
./start_backend_mac.sh
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## 3. Start frontend

Open a second Terminal window:

```bash
cd /path/to/PPI
chmod +x start_frontend_mac.sh
./start_frontend_mac.sh
```

Frontend URL on the Mac mini:

```text
http://127.0.0.1:5173/ppi-feishu-entry.html
```

If Feishu is opened from another computer, replace `127.0.0.1` in the frontend URL with the Mac mini LAN IP.

## 4. Feishu Base Extension URL

For the local default setup:

```text
http://127.0.0.1:5173/ppi-feishu-entry.html?backend=http://127.0.0.1:8000/run-ppi&token=dev-token-change-me
```

For access from other computers on the same LAN, use the Mac mini IP:

```text
http://MAC_MINI_IP:5173/ppi-feishu-entry.html?backend=http://MAC_MINI_IP:8000/run-ppi&token=YOUR_TRIGGER_TOKEN
```

Set `PPI_TRIGGER_TOKEN` in `.env` and use the same token in the URL.
