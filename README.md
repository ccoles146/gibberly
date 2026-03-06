# Gibberly — Live Sermon Translation

Real-time German → English sermon translation via Azure Speech + Web PubSub.

## Quick Start

### 1. Provision Azure resources
See `docs/azure-setup.md`.

### 2. Install dependencies
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure
```bash
cp .env.example .env
# Fill in Azure keys — see docs/azure-setup.md
```

### 4. Run the backend
```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

> **Note:** Set `BACKEND_HOST` in `.env` to your machine's LAN IP (e.g. `192.168.1.100`) — not `0.0.0.0` — so the QR code points to a valid address for phones on the same network.

### 5. Run the console (from a second terminal)
```bash
# Use microphone
python -m console.main --mode mic

# Use audio file
python -m console.main --mode file --file path/to/audio.wav
```

### 6. Listen
Scan the QR code shown in the console, or open the URL in a browser.

## Testing
```bash
pytest tests/ -v
```
