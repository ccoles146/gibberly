# Azure Setup Guide

You need two Azure resources: **Speech** (for STT + translation + TTS) and **Web PubSub** (to relay audio to listeners). Both can be created in the Azure Portal in about 5 minutes.

## Prerequisites
- Azure account. For nonprofits: apply at https://www.microsoft.com/en-us/nonprofits/azure before this step.

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

## 3. Configure a Hub

1. In the Web PubSub resource, go to **Settings → Hub Settings**.
2. Click **+ Add** → Hub name: `sermon` → **Anonymous connect**: Allow → **Save**.
   - "Anonymous connect" lets listeners connect without a signed token — fine for prototype; lock down for production.

## 4. Populate .env

In the gibberly project root, copy `.env.example` to `.env` and fill in:

```
AZURE_SPEECH_KEY=<KEY 1 from Speech resource>
AZURE_SPEECH_REGION=<region, e.g. westeurope>
AZURE_WEBPUBSUB_CONNECTION_STRING=<connection string from Web PubSub>
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
```

## 5. Verify

Run the backend health check:
```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
curl http://localhost:8000/health
# {"status":"ok"}
```
