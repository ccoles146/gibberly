# Azure Setup Guide

You need three things: **Speech** resource (STT + translation + TTS), **Web PubSub** resource (relay audio to listeners), and an **App Service** to run the backend. All can be created in the Azure Portal or via the Azure CLI.

## Prerequisites

- Azure account. For nonprofits: apply at https://www.microsoft.com/en-us/nonprofits/azure before this step.
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) installed and logged in:
  ```bash
  curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
  az login
  ```

---

## 1. Create a Speech Resource

1. Go to https://portal.azure.com → **Create a resource** → search **Speech**.
2. Select **Speech** (Microsoft) → **Create**.
3. Fill in:
   - **Subscription**: your subscription
   - **Resource group**: create new, name it `gibberly-rg`
   - **Region**: `West Europe` (or nearest to your church)
   - **Name**: `gibberly-speech`
   - **Pricing tier**: `S0` (Free tier F0 is limited to 5 hrs/month — use S0 for real use)
4. Click **Review + create** → **Create**.
5. Once deployed, go to the resource → **Keys and Endpoint**.
6. Copy **KEY 1** and **Location/Region** (e.g. `westeurope`).

---

## 2. Create a Web PubSub Resource

1. **Create a resource** → search **Web PubSub** → **Create**.
2. Fill in:
   - **Resource group**: `gibberly-rg`
   - **Resource name**: `gibberly-pubsub`
   - **Region**: same as Speech
   - **Pricing tier**: **Free** (supports 20k messages/day, 1 unit — sufficient for prototype)
3. Click **Review + create** → **Create**.
4. Once deployed, go to the resource → **Settings → Keys**.
5. Copy the **Connection string** (Primary).

---

## 3. Configure a Hub

1. In the Web PubSub resource, go to **Settings → Hub Settings**.
2. Click **+ Add** → Hub name: `sermon` → **Anonymous connect**: Allow → **Save**.
   - "Anonymous connect" lets listeners connect without a signed token — fine for prototype; lock down for production.

---

## 4. Deploy the Backend to Azure App Service

Run these commands from the project root (`~/gibberly`):

```bash
cd ~/gibberly

# Deploy — creates App Service Plan + Web App, zips and uploads the project
# First run takes ~3 minutes. Subsequent runs are faster.
az webapp up \
  --name gibberly-backend \
  --resource-group gibberly-rg \
  --runtime "PYTHON:3.11" \
  --sku B1 \
  --os-type linux \
  --location westeurope
```

> **Note:** The app runs on Python 3.11 on App Service (3.13 is not yet available). The code is fully compatible with 3.11.

Set the startup command so App Service knows to use uvicorn:

```bash
az webapp config set \
  --name gibberly-backend \
  --resource-group gibberly-rg \
  --startup-file "uvicorn backend.main:app --host 0.0.0.0 --port 8000"
```

Set the environment variables (replace the placeholder values):

```bash
az webapp config appsettings set \
  --name gibberly-backend \
  --resource-group gibberly-rg \
  --settings \
    AZURE_SPEECH_KEY="<KEY 1 from Speech resource>" \
    AZURE_SPEECH_REGION="westeurope" \
    AZURE_WEBPUBSUB_CONNECTION_STRING="<connection string from Web PubSub>" \
    BACKEND_HOST="0.0.0.0" \
    BACKEND_PORT="8000"
```

Verify the backend is live:

```bash
curl https://gibberly-backend.azurewebsites.net/health
# {"status":"ok"}
```

Your backend URLs will be:
- **Health check**: `https://gibberly-backend.azurewebsites.net/health`
- **Listener page**: `https://gibberly-backend.azurewebsites.net/listen/live`
- **WebSocket**: `wss://gibberly-backend.azurewebsites.net/ws/stream`

---

## 5. Configure the Operator Console

Edit `operator/config.js` to point at the Azure backend:

```js
window.GIBBERLY_BACKEND = "wss://gibberly-backend.azurewebsites.net";
```

The operator console is a static HTML page — no separate deployment needed. Open it directly in Chrome or Safari on the operator's Mac:

```bash
cd ~/gibberly/operator
python3 -m http.server 9000
# Open http://localhost:9000 in browser
```

> **getUserMedia note:** The device audio pipeline requires a secure context (`https://` or `localhost`). Opening `http://localhost:9000` satisfies this. The file test mode works without any server.

The QR code on the page encodes `https://gibberly-backend.azurewebsites.net/listen/live` — this is the stable URL listeners use every week. Print it or stick it on the mixing desk.

---

## 6. Redeploy After Code Changes

After any code change, redeploy with the same command (run from `~/gibberly`):

```bash
az webapp up \
  --name gibberly-backend \
  --resource-group gibberly-rg
```

App settings (env vars) are preserved across redeployments.

---

## 7. Costs

| Resource | Tier | Est. monthly cost |
|---|---|---|
| App Service Plan B1 | Basic | ~$13 |
| Speech S0 | Pay-per-use | ~$1 per hour of audio |
| Web PubSub | Free | $0 |

For a weekly 1-hour sermon: ~$17/month total, well within the nonprofit Azure grant.

To stop billing between Sundays:
```bash
az webapp stop --name gibberly-backend --resource-group gibberly-rg
az webapp start --name gibberly-backend --resource-group gibberly-rg
```

---

## Troubleshooting

**Backend returns 500 / crashes on start:**
```bash
# Check live logs
az webapp log tail --name gibberly-backend --resource-group gibberly-rg
```
Most likely cause: missing or wrong environment variable.

**WebSocket connection refused from operator console:**
- Confirm `config.js` uses `wss://` (not `ws://`) for the Azure URL.
- App Service only accepts WebSocket on port 443 (wss).

**`/listen/live` returns 503 (No live session):**
- Normal when no session is running. Start a session from the operator console.

**`az webapp up` fails with "Runtime not supported":**
```bash
# List available Python runtimes
az webapp list-runtimes --os-type linux | grep PYTHON
```
Use the latest available Python 3.x version in the `--runtime` flag.
