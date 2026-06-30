# 🚀 Developer Deployment Guide (Render & Railway)

This guide provides the exact configuration values required to deploy the FastAPI backend (`apps/api`) on **Render** and **Railway**. Since this is a monorepo (containing both frontend and backend), configuring the **Root Directory** correctly is the most critical step.

---

## 🟣 Deploying on Render (Web Service)

Based on your screenshot, you are setting up a "New Web Service" on Render. Here is exactly what you need to fill into the fields:

### Configuration Fields:
- **Root Directory**: `apps/api`
  > *Why?* This tells Render to ignore the frontend and only look inside the `apps/api` folder for the Python code.
- **Build Command**: `pip install -r requirements.txt`
  > *Why?* Installs all FastAPI and SQLAlchemy dependencies.
- **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
  > *Why?* `main` refers to `main.py`, and `app` is the FastAPI instance. The `--host 0.0.0.0` is required by Render so it can route external traffic to your app.

### Environment Variables:
Under the **Environment** tab, add the following:
1. `PYTHON_VERSION`: `3.10.12` *(Highly recommended so Render doesn't use an outdated default Python version).*
2. `DATABASE_URL`: `postgresql+asyncpg://...` *(Your Supabase connection string)*
3. `OLLAMA_BASE_URL`: *(Your AI base URL)*
4. `OLLAMA_MODEL`: *(Your AI model)*
5. `NOTION_API_KEY`: *(Your Notion integration key)*

---

## 🚂 Deploying on Railway (App Service)

You encountered the error: `"Failed to build an image. Please check the build logs for more details."`

**Root Cause of Railway Error:**
By default, Railway scans the root of your GitHub repository. It sees `apps/web/package.json` (Node.js) and `apps/api/requirements.txt` (Python) and gets confused about how to build the app (Nixpacks builder fails). 

To fix this, you must explicitly tell Railway to build **only** the `apps/api` directory.

### How to Fix & Configure Railway:
1. Go to your Railway Dashboard and select your project.
2. Click on your GitHub repo service and go to **Settings**.
3. Scroll down to the **Service** section.
4. Set the **Root Directory** to `/apps/api` (ensure it has the leading slash if Railway requires it, or just `apps/api`).
5. Under **Build**, make sure the **Builder** is set to `Nixpacks`.
6. Under **Deploy**, set the **Start Command** to:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```
7. Go to the **Variables** tab and add the same environment variables as listed in the Render section (especially `DATABASE_URL`).

### Advanced Railway Tip (If it still fails):
If Railway still fails to build, you can force it to recognize Python by creating a file named `Procfile` inside `apps/api` with the following content:
```text
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```
And add a `runtime.txt` inside `apps/api` with:
```text
python-3.10.12
```

---

## 🩺 Debugging Deployments
If your deploy succeeds but the app crashes on startup, it is almost always related to environment variables.
1. Check the **Logs** tab on Render/Railway.
2. Look for `KeyError` or `ValueError`. If you see this, it means one of your required variables from `.env` is missing in the cloud provider's dashboard.
3. Ensure your `DATABASE_URL` starts with `postgresql+asyncpg://` and not just `postgresql://` so that the asynchronous driver works correctly.
