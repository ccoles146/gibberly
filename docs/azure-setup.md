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

## 3. Create an Azure OpenAI Resource

1. **Create a resource** → search **Azure OpenAI** → **Create**.
2. Fill in:
   - **Resource group**: `gibberly-rg`
   - **Region**: `West Europe` (match your Speech resource region for lowest latency)
   - **Name**: `gibberly-openai`
   - **Pricing tier**: `S0`
3. Click **Review + create** → **Create**.
4. Once deployed, go to the resource → **Keys and Endpoint**.
5. Copy **KEY 1** → `AZURE_OPENAI_API_KEY` and **Endpoint** → `AZURE_OPENAI_ENDPOINT`.

**Deploy the model:**

6. Go to **Azure OpenAI Studio** (link in the resource overview) → **Deployments** → **+ Create**.
7. Select model: `gpt-4o-mini` → Deployment name: `gpt-4o-mini` → **Deploy**.
8. Set `AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini` in `.env`.

---

## 4. Create an Azure Translator Resource

1. **Create a resource** → search **Translator** → **Create**.
2. Fill in:
   - **Resource group**: `gibberly-rg`
   - **Region**: `West Europe`
   - **Name**: `gibberly-translator`
   - **Pricing tier**: `Free F0` (2M chars/month) or `S1` for production
3. Click **Review + create** → **Create**.
4. Once deployed, go to the resource → **Keys and Endpoint**.
5. Copy **KEY 1** → `AZURE_TRANSLATOR_KEY`. Region is `westeurope` → `AZURE_TRANSLATOR_REGION=westeurope`.

> **Note:** The Translator endpoint is always `https://api.cognitive.microsofttranslator.com` regardless of resource region — no need to copy it.

---

## 5. Configure a Hub

1. In the Web PubSub resource, go to **Settings → Hub Settings**.
2. Click **+ Add** → Hub name: `sermon` → **Anonymous connect**: Allow → **Save**.
   - "Anonymous connect" lets listeners connect without a signed token — fine for prototype; lock down for production.

---

## 6. Deploy the Backend to Azure App Service

Run these commands from the project root (`~/gibberly`):

```bash
cd ~/gibberly

# Step 1 — create the App Service Plan (B1: ~$13/month, stays responsive, can be stopped between Sundays)
az appservice plan create \
  --name gibberly-plan \
  --resource-group gibberly-rg \
  --sku B1 \
  --is-linux \
  --location germanywestcentral

# Step 2 — deploy the app (zips and uploads the project, ~3 minutes first run)
az webapp up \
  --name gibberly-backend \
  --resource-group gibberly-rg \
  --plan gibberly-plan \
  --runtime "PYTHON:3.11" \
  --location germanywestcentral
```

> **Why B1 and not Free?** The Free tier (F1) has a 60 CPU-min/day cap and goes to sleep after inactivity — the first WebSocket on Sunday would time out while it wakes. B1 stays responsive. Stop it between Sundays to save cost: `az webapp stop/start --name gibberly-backend --resource-group gibberly-rg`

Set the startup command and enable WebSocket support (disabled by default):

```bash
az webapp config set \
  --name gibberly-backend \
  --resource-group gibberly-rg \
  --startup-file "uvicorn backend.main:app --host 0.0.0.0 --port 8000" \
  --web-sockets-enabled true
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
    AZURE_OPENAI_ENDPOINT="<endpoint from Azure OpenAI resource>" \
    AZURE_OPENAI_API_KEY="<KEY 1 from Azure OpenAI resource>" \
    AZURE_OPENAI_DEPLOYMENT="gpt-4o-mini" \
    AZURE_TRANSLATOR_KEY="<KEY 1 from Translator resource>" \
    AZURE_TRANSLATOR_REGION="westeurope" \
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

## 7. Configure the Operator Console

The operator console is a static HTML page that runs locally on the Mac. It reads its backend URL from `.env` via `operator/serve.py`.

Add `GIBBERLY_BACKEND` to your `.env` file (copy from `.env.example` if you haven't already):

```
GIBBERLY_BACKEND=wss://gibberly-backend.azurewebsites.net
OPERATOR_PORT=9000
```

Then start the console:

```bash
cd ~/gibberly
python3 operator/serve.py
# Open http://localhost:9000 in browser
```

`serve.py` writes the correct backend URL into `config.js` automatically on each start — no manual file editing needed.

> **getUserMedia note:** The device audio pipeline (Dante / DeckLink) requires a secure context (`https://` or `localhost`). `http://localhost:9000` satisfies this. File test mode works without any server.

The QR code on the page encodes `https://gibberly-backend.azurewebsites.net/listen/live` — this is the stable URL listeners use every week. Print it or stick it on the mixing desk.

---

## 8. Redeploy After Code Changes

After any code change, redeploy with the same command (run from `~/gibberly`):

```bash
az webapp up \
  --name gibberly-backend \
  --resource-group gibberly-rg
```

App settings (env vars) are preserved across redeployments.

---

## 9. Costs

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

**WebSocket connection refused / operator console stays "connecting":**
- Confirm WebSockets are enabled: `az webapp config set --name gibberly-backend --resource-group gibberly-rg --web-sockets-enabled true`
- Confirm `.env` has `GIBBERLY_BACKEND=wss://…` (not `ws://`) and that you restarted `serve.py` after editing `.env`.
- App Service only accepts WebSocket on port 443 (wss).

**`/listen/live` returns 503 (No live session):**
- Normal when no session is running. Start a session from the operator console.

**`az webapp up` fails with "Runtime not supported":**
```bash
# List available Python runtimes
az webapp list-runtimes --os-type linux | grep PYTHON
```
Use the latest available Python 3.x version in the `--runtime` flag.

**Container crashes with `libpython3.11.so.1.0: cannot open shared object file`:**
Azure's Oryx build image uses Python 3.11 to compile the `antenv` virtualenv, even when you specify `PYTHON:3.13` as the runtime. The resulting `.so` files link against `libpython3.11.so.1.0` which is absent in the 3.13 runtime container. **Use `PYTHON:3.11`** — it matches the build image and is fully supported.
