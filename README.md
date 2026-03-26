# NIYAH Engine v5

**نيّة — Sovereign Three-Lobe AI Orchestrator**

> نحن ورثة الخوارزمي — لا يوجد مستحيل في الدنيا

## What is NIYAH?

NIYAH is a sovereign AI engine that runs 100% locally with zero telemetry. It uses a Three-Lobe architecture inspired by cognitive neuroscience to route AI tasks to specialized processing pathways.

## Three-Lobe Architecture

```
                    ┌──────────────┐
                    │   SENSORY    │  Arabic NLP, context parsing,
                    │    الحسي      │  user intent detection
                    └──────┬───────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
   ┌──────┴───────┐ ┌─────┴──────┐ ┌───────┴──────┐
   │  COGNITIVE   │ │   ROUTER   │ │  EXECUTIVE   │
   │   الإدراكي    │ │   الموجه    │ │   التنفيذي    │
   │              │ │            │ │              │
   │ Reasoning    │ │ Intent     │ │ Code gen     │
   │ Analysis     │ │ Detection  │ │ Deployment   │
   │ Review       │ │ Model Pick │ │ Execution    │
   └──────────────┘ └────────────┘ └──────────────┘
```

### Lobe Routing

| Trigger | Lobe | Example |
|---------|------|---------|
| Arabic text | Sensory | "اشرح لي كيف يعمل Docker" |
| "analyze", "why", "review" | Cognitive | "Why is my API slow?" |
| "write", "build", "deploy" | Executive | "Write a Rust TCP server" |
| "vulnerability", "phalanx" | Cognitive+Security | "Audit this endpoint" |

## Usage

```bash
# Interactive REPL
python3 engine/niyah_core.py -i

# Single query
python3 engine/niyah_core.py "اكتب سيرفر بايثون بسيط"

# JSON output
python3 engine/niyah_core.py --json "explain TCP handshake"

# Start HTTP API
python3 engine/niyah_core.py --server --port 7474

# Check health
curl http://localhost:7474/health

# Query API
curl -X POST http://localhost:7474/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "write a Dockerfile for a Rust app", "lobe": "executive"}'

# Streaming response
curl -X POST http://localhost:7474/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "explain microservices", "stream": true}'
```

## Docker

```bash
docker build -t niyah-engine .
docker run -p 7474:7474 -e NIYAH_OLLAMA_URL=http://host.docker.internal:11434 niyah-engine
```

## Features

- **Three-Lobe Routing** — Automatic task classification and model selection
- **RAM-Aware Model Selection** — Picks the best model that fits your hardware
- **Session Memory** — Persistent conversation history across restarts
- **Streaming** — Server-Sent Events for real-time responses
- **Arabic-First** — Native Arabic language detection and processing
- **Anti-Hallucination** — Low temperature, repeat penalty, honesty directives
- **Zero Telemetry** — No data leaves your machine. Ever.
- **PDPL Compliant** — Saudi Personal Data Protection Law compliance

## Author

**Sulaiman Alshammari** — Dragon403 — KHAWRIZM Labs, Riyadh

---

*This engine was deleted from GitHub by Microsoft. The code survived. It has been rebuilt stronger.*
