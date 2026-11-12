# Northstar Shop

A responsive FastAPI ecommerce starter with five account features: customer sign-in, persistent shopping carts, order history and status tracking, product reviews, and an admin dashboard. SQLite stores accounts, carts, products, and orders; MongoDB stores product reviews. The included checkout creates demo orders and reserves stock, but does **not** process payments.

Order references and statuses are for in-app tracking only; no shipping-carrier integration is included.

## Run locally

The easiest way to run both the app and MongoDB is Docker Compose:

```powershell
$env:ADMIN_EMAIL = "admin@example.com" # optional: enables the admin dashboard
$env:ADMIN_PASSWORD = "choose-a-long-password"
docker compose up --build
```

Open [http://localhost:8000](http://localhost:8000). SQLite data and MongoDB data are persisted in named volumes.

To run the Python app directly, start MongoDB separately (for example, `docker compose up -d mongodb`), then:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:MONGO_URI = "mongodb://localhost:27017/northstar"
$env:COOKIE_SECURE = "false"
$env:ADMIN_EMAIL = "admin@example.com"
$env:ADMIN_PASSWORD = "choose-a-long-password"
uvicorn app.main:app --reload
```

`MONGO_URI` is needed for product reviews; the rest of the app uses SQLite and can run without MongoDB, but review endpoints will return `503` until MongoDB is configured. Set both `ADMIN_EMAIL` and `ADMIN_PASSWORD` to create/promote the store administrator on startup; omit both to disable admin access. Interactive API documentation is at `/docs`. The local SQLite database is created at `data/store.db`.

Passwords are stored as PBKDF2 hashes. Login sessions use an HttpOnly cookie and expire after 30 days. Set `COOKIE_SECURE=true` when serving the app over HTTPS.

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
docker compose up --build
```

Compose starts MongoDB and the app together. Mount the app's `/data` volume and MongoDB's `/data/db` volume persistently to retain data across container restarts.

## Kubernetes

Build and publish the image to a registry reachable by your cluster, then update `image` in `k8s/deployment.yaml`:

```powershell
docker build -t YOUR_REGISTRY/northstar-shop:latest .
docker push YOUR_REGISTRY/northstar-shop:latest
kubectl apply -f k8s/configmap.yaml
$env:MONGO_USER = "northstaradmin"
$env:MONGO_PASSWORD = "URL_SAFE_RANDOM_PASSWORD"
$env:ADMIN_PASSWORD = "CHOOSE_A_LONG_PASSWORD"
$mongoUri = "mongodb://{0}:{1}@northstar-mongodb:27017/northstar?authSource=admin" -f $env:MONGO_USER, $env:MONGO_PASSWORD
kubectl create secret generic northstar-mongodb-credentials --from-literal="username=$env:MONGO_USER" --from-literal="password=$env:MONGO_PASSWORD"
kubectl create secret generic northstar-app --from-literal="mongo-uri=$mongoUri"
kubectl create secret generic northstar-admin --from-literal="email=admin@example.com" --from-literal="password=$env:ADMIN_PASSWORD"
kubectl apply -f k8s/mongodb.yaml
kubectl apply -f k8s/deployment.yaml
kubectl port-forward service/northstar-shop 8000:80
```

Create strong, URL-safe MongoDB credentials and set `$env:MONGO_USER`, `$env:MONGO_PASSWORD`, and `$env:ADMIN_PASSWORD` before creating Secrets. Do not commit secrets. The optional `northstar-admin` Secret enables the admin dashboard; omit it to disable admin access. The optional `northstar-chat` Secret is only needed for a remote chatbot API. Set `COOKIE_SECURE` to `"true"` in `k8s/deployment.yaml` when TLS is enabled at the Ingress; it is `"false"` by default so the documented HTTP port-forward works. Configure an Ingress and TLS for public access. The app deployment stays at one replica because its transactional store is SQLite; MongoDB runs as a single-replica StatefulSet in this starter.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The API includes product browse/search/filter, account registration and login, customer cart and order endpoints, product reviews, admin product/order management, and `POST /api/chat`. Tests use an isolated fake MongoDB collection for review behavior, so the suite does not require a running MongoDB server.
