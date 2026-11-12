# Northstar Shop

A responsive ecommerce starter with a FastAPI API, SQLite persistence, and an in-store shopping assistant. The included checkout creates demo orders and reserves stock; it does **not** collect payment or customer accounts.

## Run locally

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000). Interactive API documentation is at `/docs`. The local database is created at `data/store.db` by default.

## Shopping assistant

The assistant works out of the box using the product catalog, shipping, and returns information. To use an OpenAI-compatible chat-completions API, set these environment variables on the server:

```powershell
$env:CHAT_API_URL = "https://api.openai.com/v1"
$env:CHAT_API_KEY = "<your-server-side-api-key>"
$env:CHAT_MODEL = "gpt-4o-mini"
uvicorn app.main:app --reload
```

`CHAT_API_KEY` is never sent to the browser. Do not commit credentials. If a configured provider is unavailable, the chat endpoint returns an error rather than silently claiming the local assistant answered.

## Docker

```powershell
docker build -t northstar-shop:latest .
docker run --rm -p 8000:8000 -v northstar-data:/data northstar-shop:latest
```

Mount `/data` persistently to retain orders and stock across container restarts.

## Kubernetes

Build and publish the image to a registry reachable by your cluster, then update `image` in `k8s/deployment.yaml`:

```powershell
docker build -t YOUR_REGISTRY/northstar-shop:latest .
docker push YOUR_REGISTRY/northstar-shop:latest
kubectl apply -f k8s/configmap.yaml
kubectl create secret generic northstar-chat --from-literal=api-key="YOUR_CHAT_API_KEY"
kubectl apply -f k8s/deployment.yaml
kubectl port-forward service/northstar-shop 8000:80
```

The `northstar-chat` Secret is optional when using the built-in assistant. Set `chat-api-url` in `k8s/configmap.yaml` to the OpenAI-compatible API base URL to enable a remote model. The manifest uses a single replica because SQLite is not a multi-replica database; migrate to PostgreSQL and use a managed database for horizontal scaling/production. Configure an Ingress and TLS for public access.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The API includes `GET /healthz`, product browse/search/filter endpoints, order creation with server-validated prices and stock, and `POST /api/chat`.
