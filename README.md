# Gibberly — Live Sermon Translation

Real-time sermon translation via Azure Speech + Web PubSub.
Built to solve our own translation problems:

- Keeping track of translation radio sets
- Keeping radio sets operational and sanitised
- Replacing or charging batteries
- Replacing damaged headphones
- Recruiting translators for each language, each week

> Why not use an existing translation app?

Translation apps are a dime-a-dozen but they cannot compete on price because they all use the same AI APIs to do the translation work. Some models are cheaper than others and some are more optimised/efficient than others but the variation is not huge, meaning the price of them all are similar.

They usually have a pay-as-you-go tier that works out around $20 per hour. And then they have their bundles starting at about $50 per month and going up from there.

The biggest cost, is in the audio generation and analysis. Taking the input language and generating text only needs to be done once. Then subsequently each output language needs generating according to demand.

Roughly you're looking at $2 per hour for each language.

> If you build this yourself you're saving 90% over the ready-made versions.

We can do better than that though. If you're a non-profit then you're likely eligible for the Microsoft Non-Profit Azure grant.

Maybe you already use the non-profit **Microsoft 365** grant for your organisation. That one provides some functions for free and some for a good discount. This is similar but needs applying for separately and grants you currently (as of 2026) $2000 to be used across **Azure**.

For a **church**, $2000 will cover more than enough translation for the entire year. Depending on the number of languages, estimates are $500-$1000.

> ⚠️ The $2000 does need applying for each year, otherwise you will pay standard pricing!

---

## Recommended Setup

The recommended deployment runs the backend in Azure and the operator console locally on a Mac or PC. Listeners connect via their phones using a link or QR code — no app install needed.

### 1. Clone the repository

```bash
git clone https://github.com/ccoles/gibberly.git
cd gibberly
```

### 2. Install the Azure CLI

```bash
# macOS
brew install azure-cli

# Linux (Debian/Ubuntu)
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Windows — download the MSI from https://aka.ms/installazurecliwindows
```

Log in:
```bash
az login
```

### 3. Create Azure resources

```bash
# Resource group (choose a region close to your church)
az group create --name gibberly-rg --location germanywestcentral

# Speech resource (STT + TTS)
az cognitiveservices account create \
  --name gibberly-speech \
  --resource-group gibberly-rg \
  --kind SpeechServices \
  --sku S0 \
  --location germanywestcentral

# Web PubSub (free tier — 20k messages/day, enough for weekly sermons)
az webpubsub create \
  --name gibberly-pubsub \
  --resource-group gibberly-rg \
  --sku Free_F1 \
  --location germanywestcentral

# Azure OpenAI (translation + text cleanup)
az cognitiveservices account create \
  --name gibberly-openai \
  --resource-group gibberly-rg \
  --kind OpenAI \
  --sku S0 \
  --location germanywestcentral
```

Deploy the GPT-4o mini model in Azure OpenAI Studio, then retrieve all the keys:

```bash
# Speech key and region
az cognitiveservices account keys list \
  --name gibberly-speech \
  --resource-group gibberly-rg \
  --query key1 -o tsv

# Web PubSub connection string
az webpubsub key show \
  --name gibberly-pubsub \
  --resource-group gibberly-rg \
  --query primaryConnectionString -o tsv

# Azure OpenAI key and endpoint
az cognitiveservices account keys list \
  --name gibberly-openai \
  --resource-group gibberly-rg \
  --query key1 -o tsv

az cognitiveservices account show \
  --name gibberly-openai \
  --resource-group gibberly-rg \
  --query properties.endpoint -o tsv
```

Enable anonymous listener connections on the Web PubSub hub (required for the listener page):

```bash
az webpubsub hub create \
  --name gibberly-pubsub \
  --resource-group gibberly-rg \
  --hub-name sermon \
  --allow-anonymous true
```

> See [docs/azure-setup.md](docs/azure-setup.md) for full portal-based walkthrough and nonprofit grant details.

### 4. Deploy the backend to Azure App Service

```bash
# Check available Python runtimes in your region first
az webapp list-runtimes --os-type linux | grep PYTHON

# Create the App Service plan (B1: ~$13/month, stays awake — no cold-start on Sundays)
az appservice plan create \
  --name gibberly-plan \
  --resource-group gibberly-rg \
  --sku B1 \
  --is-linux \
  --location germanywestcentral

# Deploy the app (zips and uploads the project — ~3 minutes first run)
# Replace PYTHON:3.11 with the latest available version from the step above
az webapp up \
  --name gibberly-backend \
  --resource-group gibberly-rg \
  --plan gibberly-plan \
  --runtime "PYTHON:3.11" \
  --location germanywestcentral

# Enable WebSockets and set the startup command
az webapp config set \
  --name gibberly-backend \
  --resource-group gibberly-rg \
  --startup-file "uvicorn backend.main:app --host 0.0.0.0 --port 8000" \
  --web-sockets-enabled true
```

### 5. Push config to the backend

Replace each placeholder with the keys retrieved in step 3:

```bash
az webapp config appsettings set \
  --name gibberly-backend \
  --resource-group gibberly-rg \
  --settings \
    AZURE_SPEECH_KEY="<KEY 1 from Speech resource>" \
    AZURE_SPEECH_REGION="germanywestcentral" \
    AZURE_WEBPUBSUB_CONNECTION_STRING="<connection string from Web PubSub>" \
    AZURE_OPENAI_ENDPOINT="<endpoint from Azure OpenAI resource>" \
    AZURE_OPENAI_API_KEY="<KEY 1 from Azure OpenAI resource>" \
    AZURE_OPENAI_DEPLOYMENT="gpt-4o-mini" \
    AZURE_OPENAI_REGION="germanywestcentral" \
    BACKEND_HOST="0.0.0.0" \
    BACKEND_PORT="8000"
```

Verify the backend is live:

```bash
curl https://gibberly-backend.azurewebsites.net/health
# {"status":"ok"}
```

### 6. Run the operator console

```bash
cp .env.example .env
# Set GIBBERLY_BACKEND=wss://gibberly-backend.azurewebsites.net
# Set OPERATOR_PORT=9000

python3 operator/serve.py
# Open http://localhost:9000
```

The QR code on the operator page encodes `https://gibberly-backend.azurewebsites.net/listen/live` — this is the stable URL listeners open on their phones each week.

### 7. Redeploy after code changes

```bash
az webapp up --name gibberly-backend --resource-group gibberly-rg
```

App settings are preserved across redeployments.

---

## Managing costs

Stop the App Service between Sundays to avoid paying for idle time:

```bash
az webapp stop  --name gibberly-backend --resource-group gibberly-rg
az webapp start --name gibberly-backend --resource-group gibberly-rg
```

| Resource | Tier | Est. monthly cost |
|---|---|---|
| App Service Plan B1 | Basic | ~$13 |
| Speech S0 | Pay-per-use | ~$1 per sermon hour |
| Azure OpenAI (GPT-4o mini) | Pay-per-use | ~$0.50 per sermon hour |
| Web PubSub | Free | $0 |

For a weekly 1-hour sermon: ~$17/month — well within the nonprofit Azure grant.

---

## How to run locally

You can run both front-end and back-end locally, pointing at the same Azure Speech and Web PubSub resources. Listeners will need to be on the same local network as the machine running the backend.

### Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Fill in Azure keys from docs/azure-setup.md
# Set BACKEND_HOST to your machine's LAN IP (e.g. 192.168.1.100) — not 0.0.0.0 —
# so the QR code points to a valid address for phones on the same network.
# Set GIBBERLY_BACKEND=ws://192.168.1.100:8000
```

### Run the backend

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### Run the operator console (second terminal)

```bash
python3 operator/serve.py
# Open http://localhost:9000
```

### Translate from a file or microphone (alternative — CLI mode)

```bash
# Use microphone
python -m console.main --mode mic

# Use audio file
python -m console.main --mode file --file path/to/audio.wav
```

Scan the QR code shown in the console, or open the URL directly in a browser.

---

## Testing

```bash
pytest tests/ -v
```
