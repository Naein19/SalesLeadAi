<div align="center">
  <h1>🚀 LeadAI Platform</h1>
  <p><strong>AI-Powered Sales Lead Enrichment & CRM Synchronization Platform</strong></p>
  
  [![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org)
  [![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
  [![Next.js](https://img.shields.io/badge/Next.js-14+-black.svg)](https://nextjs.org)
  [![Supabase](https://img.shields.io/badge/Supabase-Database-success.svg)](https://supabase.com)
  [![Render](https://img.shields.io/badge/Render-Deployment-purple.svg)](https://render.com)
  [![Vercel](https://img.shields.io/badge/Vercel-Frontend-black.svg)](https://vercel.com)
</div>

---

LeadAI is an asynchronous, high-throughput backend architecture designed to automatically scrape, enrich, score, and synchronize sales leads into a Notion CRM in real-time. It leverages advanced LLM semantic reasoning to evaluate ICP (Ideal Customer Profile) fit and detect buying signals, removing the need for manual lead qualification.

## 🏗️ Architecture

```mermaid
graph TD
    subgraph Frontend [Next.js Web Application]
        UI[User Interface]
        Upload[CSV Uploader]
    end

    subgraph Backend [FastAPI Asynchronous Pipeline]
        API[API Router]
        Orchestrator[Enrichment Orchestrator]
        Scrapers[Data Scrapers]
        ICP[ICP & Signal Scorer]
        Drafts[Outreach Generator]
        Notion[Notion CRM Sync]
    end

    subgraph External [External Services]
        Groq[Groq API / Llama 3.3 70B]
        NotionDB[Notion Database]
        LinkedIn[LinkedIn Public Web]
    end

    UI <--> API
    Upload --> API
    API --> Orchestrator
    Orchestrator --> Scrapers
    Scrapers <--> LinkedIn
    Orchestrator --> ICP
    ICP <--> Groq
    Orchestrator --> Drafts
    Drafts <--> Groq
    Orchestrator --> Notion
    Notion <--> NotionDB
```

> [!NOTE]
> **Data Lifecycle:** CSV Upload → Asynchronous Background Queue → Parallel Scraping → LLM Semantic Reasoning → Draft Generation → CRM Payload Generation → Notion DB Schema Mapping → Push to Notion.

---

## 🧠 Core Engineering Decisions

### 1. ICP Scoring & Buying Signals
LeadAI abandons primitive keyword matching. Instead, it utilizes **prompt-based semantic reasoning** via Groq's LLM to evaluate complex ICP criteria. 

**Scoring Formula:**
The overall score is a dynamically calculated composite metric. By default, it weights the semantic ICP match heavily while incorporating buying signal momentum:
```
Overall Score = (ICP Semantic Fit * 0.70) + (Buying Signal Momentum * 0.30)
```
*(This weighting is adjustable via environment variables to adapt to different sales pipelines.)*

### 2. Model Choice & Memory Constraints
**No local LLMs are utilized.** LeadAI uses the **Groq API** (specifically `llama-3.3-70b-versatile`). 
This is a **constraint-driven architectural decision**: 
- Free-tier PAAS platforms (like Render or Railway) provide strict memory constraints (often <512MB RAM). 
- Hosting an 8B or 70B parameter model locally would immediately cause Out-Of-Memory (OOM) crashes.
- Utilizing Groq provides instant inference (approx. 800 tokens/sec) with zero memory footprint on the host container, making the application extremely scalable on minimal infrastructure.

### 3. LinkedIn Scraping Strategy
The platform includes raw web scraping for LinkedIn profiles and company pages. 
> [!WARNING]
> **High Failure Rate Expected:** LinkedIn aggressively blocks unauthenticated scrapers. This is an expected environmental constraint, not a bug. 
> **Graceful Degradation:** The orchestrator is designed to handle scraper failures gracefully. If LinkedIn blocks the request, the orchestrator immediately falls back to `"Data not found"` for those specific fields (with a `0` confidence score), allowing the rest of the enrichment pipeline (ICP scoring, Draft Generation, Notion Sync) to succeed without crashing.

---

## 🚀 Deployment Guide

This project is configured for a split deployment: **Render** for the Python backend and **Vercel** for the Next.js frontend.

### Backend (Render)
A `render.yaml` configuration is included at the root of the repository.
1. Connect your GitHub repository to Render.
2. Render will automatically detect the `render.yaml` Blueprint.
3. Configure the following environment variables in the Render dashboard:
   - `DATABASE_URL` (Supabase Postgres connection string using `postgresql+asyncpg://`)
   - `GROQ_API_KEY`
   - `NOTION_API_KEY`
   - `NOTION_DATABASE_ID`

### Frontend (Vercel)
A `vercel.json` is provided to route API calls.
1. Connect the repository to Vercel.
2. Set the **Root Directory** to `apps/web`.
3. Vercel will automatically detect the Next.js framework.
4. Set the following environment variable in Vercel:
   - `NEXT_PUBLIC_API_URL`: Set this to your Render application URL (e.g., `https://leadai-backend.onrender.com`)

---

## 💻 Local Setup & Debugging

### Prerequisites
- Python 3.10+
- Node.js 18+
- Supabase Postgres Database

### 1. Backend Setup
```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in `apps/api`:
```env
DATABASE_URL=postgresql+asyncpg://user:password@host:port/postgres
GROQ_API_KEY=gsk_...
NOTION_API_KEY=ntn_...
NOTION_DATABASE_ID=...
```

Run the FastAPI Server:
```bash
uvicorn main:app --reload --port 8000
```
> [!TIP]
> **Debugging:** For pipeline tracing, run `python apps/api/trace_pipeline.py` to test the enrichment workflow end-to-end without hitting the HTTP router. The system extensively uses `core.logging.log_stage` which outputs JSON-structured logs perfect for Datadog or AWS CloudWatch.

### 2. Frontend Setup
```bash
cd apps/web
npm install
```

Create a `.env.local` file in `apps/web`:
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Run the Next.js Server:
```bash
npm run dev
```

---

## ⏳ Limitations & Future Work

> [!IMPORTANT]
> **Not Implemented due to 6-hour time constraint:**
> Due to strict time limitations during development, the following features were designed but deferred:
> 
> 1. **Pipeline Status View:** A real-time WebSocket or polling UI to watch the background queue process leads individually.
> 2. **ICP Config UI:** The ICP scoring criteria is currently API/Database-only. A visual editor for sales teams to adjust the prompt weighting was deferred.
> 3. **Sequence Builder:** Automated multi-step email drip campaign builder.
> 4. **Email Finder:** Integration with services like Hunter.io or Apollo to guess/verify missing email addresses.
> 5. **Lead Score History:** Tracking the delta of a lead's score over time as they interact with content.
> 6. **Domain-Level Enrichment:** Scraping the lead's company website directly to augment LinkedIn data.
