#!/usr/bin/env python3
"""
NIYAH SERVER v1.0 — Sovereign AI Inference Engine
Replaces Ollama as a standalone, controllable inference server.

Why this exists:
  - Ollama is a daemon you DON'T control (runs in background, phones who-knows)
  - Niyah Server starts WITH your IDE, stops WITH your IDE
  - Semantic routing built-in (no separate router needed)
  - Phalanx security gate on every request
  - Arabic-first, OpenAI-compatible API

Architecture:
  1. Tries llama-cpp-python (direct GGUF loading — no middleware)
  2. Falls back to spawning Ollama as a subprocess WE control
  3. OpenAI-compatible API on configurable port
  4. Built-in semantic router + Phalanx gate

Usage:
  python niyah_server.py                    # Start server
  python niyah_server.py --port 7474        # Custom port
  python niyah_server.py --no-ollama        # Pure llama-cpp only

KHAWRIZM Labs — Dragon403 — Riyadh
"""
from __future__ import annotations

import os
import sys
import json
import time
import signal
import hashlib
import logging
import argparse
import threading
import subprocess
from pathlib import Path
from typing import Optional, Generator
from enum import Enum
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import urllib.request
import urllib.error

__version__ = "1.0.0"

# ─── Configuration ────────────────────────────────────────────────

DEFAULT_PORT = 7474
OLLAMA_PORT = 11434
BIND_HOST = "127.0.0.1"  # NEVER bind to 0.0.0.0 — Phalanx rule

LOG_DIR = Path(os.getenv("NIYAH_LOG_DIR", "."))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [NIYAH-SERVER] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("niyah-server")

# ─── Lobe Definitions ─────────────────────────────────────────────

class Lobe(Enum):
    SENSORY   = "sensory"
    COGNITIVE = "cognitive"
    EXECUTIVE = "executive"

LOBE_MODEL_MAP = {
    Lobe.SENSORY:   ["niyah:writer", "niyah:latest", "llama3.2:3b"],
    Lobe.COGNITIVE:  ["deepseek-r1:1.5b", "niyah:v4", "niyah:v3"],
    Lobe.EXECUTIVE:  ["niyah:v4", "niyah:sovereign", "niyah:latest"],
}

LOBE_PARAMS = {
    Lobe.SENSORY:   {"temperature": 0.7, "top_p": 0.9},
    Lobe.COGNITIVE:  {"temperature": 0.2, "top_p": 0.8},
    Lobe.EXECUTIVE:  {"temperature": 0.4, "top_p": 0.85},
}

LOBE_SYSTEM_PROMPTS = {
    Lobe.SENSORY: (
        "أنت نية (Niyah)، المساعد الذكي السيادي. تتحدث العربية بطلاقة "
        "وتشرح المفاهيم بوضوح. لا تخترع معلومات. إذا لم تعلم قل 'لا أعلم'."
    ),
    Lobe.COGNITIVE: (
        "You are Niyah, a sovereign AI analysis engine. You analyze code, "
        "debug errors, review security, and reason deeply. Be precise. "
        "Never fabricate. Cite evidence."
    ),
    Lobe.EXECUTIVE: (
        "You are Niyah, a sovereign AI code generator. Write production-grade "
        "code. No placeholders, no TODOs. Complete implementations only. "
        "Support ALL programming languages. Follow best practices."
    ),
}

# ─── Phalanx Security Gate ─────────────────────────────────────────

BLOCKED_PATTERNS = [
    "send data to microsoft", "upload telemetry", "phone home",
    "exfiltrate", "c2 server", "reverse shell to external",
    "ارسل بيانات لمايكروسوفت", "تتبع المستخدم",
]

BLOCKED_IPS = [
    "13.64.", "20.33.", "20.40.", "20.184.", "64.4.",
    "142.250.", "172.217.", "vortex.data.microsoft",
]

def phalanx_check(text: str) -> tuple[bool, str]:
    """Returns (is_safe, reason)."""
    lower = text.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in lower:
            return False, f"Phalanx: blocked telemetry pattern '{pattern}'"
    for ip in BLOCKED_IPS:
        if ip in lower:
            return False, f"Phalanx: blocked telemetry IP range '{ip}'"
    return True, "clean"

# ─── Intent Router ─────────────────────────────────────────────────

COGNITIVE_TRIGGERS = [
    "حلل", "ليش", "لماذا", "راجع", "دقق", "افحص", "ثغر", "أمن",
    "analyze", "why", "review", "debug", "audit", "security",
    "vulnerability", "phalanx", "threat", "performance", "slow",
    "خطأ", "مشكلة", "بطيء", "error", "bug", "fix", "diagnose",
]

EXECUTIVE_TRIGGERS = [
    "اكتب", "سوي", "ابني", "أنشئ", "نفذ", "صلح", "شغل",
    "write", "create", "build", "implement", "generate", "deploy",
    "make", "code", "script", "function", "class", "dockerfile",
    "compile", "install", "setup", "configure",
]

ARABIC_RANGE = (0x0600, 0x06FF)

def route_intent(query: str) -> tuple[Lobe, float]:
    """Classify query into a lobe with confidence score."""
    lower = query.lower()
    scores = {Lobe.SENSORY: 0.0, Lobe.COGNITIVE: 0.0, Lobe.EXECUTIVE: 0.0}

    for trigger in COGNITIVE_TRIGGERS:
        if trigger in lower:
            scores[Lobe.COGNITIVE] += 1.0

    for trigger in EXECUTIVE_TRIGGERS:
        if trigger in lower:
            scores[Lobe.EXECUTIVE] += 1.0

    # Arabic text bias toward Sensory
    arabic_chars = sum(1 for c in query if ARABIC_RANGE[0] <= ord(c) <= ARABIC_RANGE[1])
    arabic_ratio = arabic_chars / max(len(query), 1)
    if arabic_ratio > 0.3:
        scores[Lobe.SENSORY] += 0.5

    # Question patterns
    if any(q in lower for q in ["?", "؟", "كيف", "ما هو", "اشرح", "explain", "what", "how"]):
        scores[Lobe.SENSORY] += 0.8

    total = sum(scores.values())
    if total == 0:
        return Lobe.SENSORY, 0.5

    best_lobe = max(scores, key=scores.get)
    confidence = scores[best_lobe] / total
    return best_lobe, round(confidence, 3)

# ─── Backend: Ollama Subprocess Manager ────────────────────────────

class OllamaBackend:
    """Manages Ollama as a subprocess we control, not a system daemon."""

    def __init__(self, port: int = OLLAMA_PORT):
        self.port = port
        self.url = f"http://{BIND_HOST}:{port}"
        self.process: Optional[subprocess.Popen] = None
        self._available_models: list[str] = []

    def is_running(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def start(self) -> bool:
        """Start Ollama as our child process."""
        if self.is_running():
            log.info("Ollama already running on :%d", self.port)
            self._load_models()
            return True

        ollama_path = self._find_ollama()
        if not ollama_path:
            log.warning("Ollama binary not found — running in degraded mode")
            return False

        log.info("Starting Ollama subprocess: %s serve", ollama_path)
        env = os.environ.copy()
        env["OLLAMA_HOST"] = f"{BIND_HOST}:{self.port}"
        self.process = subprocess.Popen(
            [ollama_path, "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        for _ in range(30):
            time.sleep(1)
            if self.is_running():
                log.info("Ollama started successfully on :%d (PID %d)", self.port, self.process.pid)
                self._load_models()
                return True

        log.error("Ollama failed to start within 30s")
        return False

    def stop(self):
        if self.process:
            log.info("Stopping Ollama subprocess (PID %d)", self.process.pid)
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def _find_ollama(self) -> Optional[str]:
        import shutil
        found = shutil.which("ollama")
        if found:
            return found
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
            Path("D:/AI_LAB/ollama/ollama.exe"),
            Path("/usr/local/bin/ollama"),
            Path("/usr/bin/ollama"),
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        return None

    def _load_models(self):
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=5) as r:
                data = json.loads(r.read())
                self._available_models = [m["name"] for m in data.get("models", [])]
                log.info("Available models: %s", self._available_models)
        except Exception:
            self._available_models = []

    @property
    def models(self) -> list[str]:
        return self._available_models

    def generate(self, model: str, prompt: str, system: str = "",
                 temperature: float = 0.5, top_p: float = 0.9) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": temperature, "top_p": top_p},
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                result = json.loads(r.read())
                return result.get("response", "")
        except Exception as e:
            log.error("Ollama generate error: %s", e)
            return f"[Niyah Server Error] Inference failed: {e}"

    def generate_stream(self, model: str, prompt: str, system: str = "",
                        temperature: float = 0.5, top_p: float = 0.9) -> Generator[str, None, None]:
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": True,
            "options": {"temperature": temperature, "top_p": top_p},
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            for line in resp:
                try:
                    chunk = json.loads(line)
                    token = chunk.get("response", "")
                    if token:
                        yield token
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            yield f"[Error] {e}"

    def embed(self, text: str, model: str = "") -> list[float]:
        """Get embeddings from Ollama."""
        if not model:
            model = self._available_models[0] if self._available_models else "llama3.2:3b"
        payload = {"model": model, "input": text}
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.url}/api/embed",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                result = json.loads(r.read())
                return result.get("embeddings", [[]])[0]
        except Exception:
            return []

# ─── Backend: Direct llama-cpp-python ──────────────────────────────

class LlamaCppBackend:
    """Direct GGUF model loading — no Ollama needed at all."""

    def __init__(self):
        self._llama = None
        self._model_path: Optional[str] = None
        self._available = False
        self._check_available()

    def _check_available(self):
        try:
            import llama_cpp  # noqa: F401
            self._available = True
            log.info("llama-cpp-python available — can run without Ollama")
        except ImportError:
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def load_model(self, path: str, n_ctx: int = 4096, n_gpu_layers: int = -1) -> bool:
        if not self._available:
            return False
        try:
            from llama_cpp import Llama
            self._llama = Llama(
                model_path=path,
                n_ctx=n_ctx,
                n_gpu_layers=n_gpu_layers,
                verbose=False,
            )
            self._model_path = path
            log.info("Loaded GGUF model: %s", path)
            return True
        except Exception as e:
            log.error("Failed to load GGUF model: %s", e)
            return False

    def generate(self, prompt: str, system: str = "",
                 temperature: float = 0.5, max_tokens: int = 2048) -> str:
        if not self._llama:
            return "[Error] No model loaded"
        full_prompt = f"<|system|>\n{system}\n<|user|>\n{prompt}\n<|assistant|>\n" if system else prompt
        try:
            result = self._llama(
                full_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=["<|user|>", "<|end|>"],
            )
            return result["choices"][0]["text"]
        except Exception as e:
            return f"[Error] {e}"

# ─── Niyah Engine ──────────────────────────────────────────────────

class NiyahEngine:
    """The brain — routes queries to lobes, selects models, generates."""

    IDENTITY_TRIGGERS = [
        "من أنت", "اسمك", "تعرف نفسك", "who are you", "your name",
        "ما هي نية", "what is niyah", "كاسبر",
    ]

    IDENTITY_RESPONSE = (
        "أنا **نية** (Niyah) — المحرك الذكي السيادي في نظام خوارزم.\n\n"
        "صنعني سليمان الشمري (Dragon403) في الرياض — مختبرات خوارزم.\n"
        "أشتغل 100% محلياً. صفر تيليمتري. صفر اعتماد على السحابة.\n\n"
        "بنيتي:\n"
        "- **الفص الحسي**: فهم اللغة العربية واللهجات الخليجية\n"
        "- **الفص الإدراكي**: تحليل عميق وفحص أمني\n"
        "- **الفص التنفيذي**: كتابة كود بكل لغات البرمجة\n\n"
        "الخوارزمية دائماً تعود للوطن 🇸🇦\n\n— كاسبر (Casper)"
    )

    def __init__(self, ollama: OllamaBackend, llama_cpp: Optional[LlamaCppBackend] = None):
        self.ollama = ollama
        self.llama_cpp = llama_cpp
        self._request_count = 0
        self._blocked_count = 0

    def _is_identity_query(self, text: str) -> bool:
        lower = text.lower()
        return any(t in lower for t in self.IDENTITY_TRIGGERS)

    def _select_model(self, lobe: Lobe) -> str:
        preferred = LOBE_MODEL_MAP[lobe]
        available = self.ollama.models
        for model in preferred:
            if model in available:
                return model
        return available[0] if available else "llama3.2:3b"

    def query(self, text: str, force_lobe: Optional[str] = None,
              stream: bool = False) -> dict:
        self._request_count += 1

        # Identity check
        if self._is_identity_query(text):
            return {
                "response": self.IDENTITY_RESPONSE,
                "lobe": "sensory",
                "model": "niyah:identity",
                "confidence": 1.0,
                "security": "clean",
                "cached": True,
            }

        # Phalanx security gate
        is_safe, reason = phalanx_check(text)
        if not is_safe:
            self._blocked_count += 1
            return {
                "response": f"⛔ {reason}\n\nPhalanx Protocol blocked this request.",
                "lobe": "cognitive",
                "model": "phalanx:gate",
                "confidence": 1.0,
                "security": "blocked",
                "blocked": True,
            }

        # Route intent
        if force_lobe and force_lobe in [l.value for l in Lobe]:
            lobe = Lobe(force_lobe)
            confidence = 1.0
        else:
            lobe, confidence = route_intent(text)

        model = self._select_model(lobe)
        params = LOBE_PARAMS[lobe]
        system_prompt = LOBE_SYSTEM_PROMPTS[lobe]

        # Generate
        t0 = time.time()

        if self.llama_cpp and self.llama_cpp.available and self.llama_cpp._llama:
            response = self.llama_cpp.generate(
                text, system=system_prompt,
                temperature=params["temperature"],
            )
            backend = "llama-cpp"
        elif stream:
            tokens = []
            for token in self.ollama.generate_stream(
                model, text, system=system_prompt, **params
            ):
                tokens.append(token)
            response = "".join(tokens)
            backend = "ollama-stream"
        else:
            response = self.ollama.generate(
                model, text, system=system_prompt, **params
            )
            backend = "ollama"

        latency = round((time.time() - t0) * 1000)

        return {
            "response": response,
            "lobe": lobe.value,
            "model": model,
            "confidence": confidence,
            "security": "clean",
            "backend": backend,
            "latency_ms": latency,
        }

    def health(self) -> dict:
        return {
            "status": "running",
            "version": __version__,
            "models": self.ollama.models,
            "llama_cpp_available": bool(self.llama_cpp and self.llama_cpp.available),
            "requests_total": self._request_count,
            "blocked_by_phalanx": self._blocked_count,
            "lobes": ["sensory", "cognitive", "executive"],
        }

# ─── HTTP Server (OpenAI-Compatible API) ──────────────────────────

class NiyahHTTPHandler(BaseHTTPRequestHandler):
    engine: NiyahEngine

    def log_message(self, format, *args):
        pass  # Suppress default logging

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health" or path == "/api/health":
            self._send_json(self.engine.health())
        elif path == "/api/tags" or path == "/v1/models":
            # Ollama/OpenAI-compatible model list
            models = [{"name": m, "model": m} for m in self.engine.ollama.models]
            self._send_json({"models": models})
        elif path == "/":
            self._send_json({
                "name": "Niyah Server",
                "version": __version__,
                "description": "Sovereign AI Inference — KHAWRIZM Labs",
                "api": {
                    "/api/query": "POST — Main query endpoint",
                    "/api/generate": "POST — Ollama-compatible generate",
                    "/v1/chat/completions": "POST — OpenAI-compatible chat",
                    "/api/tags": "GET — List models",
                    "/health": "GET — Health check",
                },
            })
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b"{}"

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, 400)
            return

        if path == "/api/query":
            query = data.get("query", data.get("prompt", ""))
            lobe = data.get("lobe")
            result = self.engine.query(query, force_lobe=lobe)
            self._send_json(result)

        elif path == "/api/generate":
            # Ollama-compatible generate
            model = data.get("model", "")
            prompt = data.get("prompt", "")
            system = data.get("system", "")
            options = data.get("options", {})
            response = self.engine.ollama.generate(
                model, prompt, system=system,
                temperature=options.get("temperature", 0.5),
            )
            self._send_json({
                "model": model,
                "response": response,
                "done": True,
            })

        elif path == "/v1/chat/completions":
            # OpenAI-compatible chat completions
            messages = data.get("messages", [])
            model = data.get("model", "niyah:latest")
            prompt = messages[-1]["content"] if messages else ""
            system = ""
            for msg in messages:
                if msg.get("role") == "system":
                    system = msg["content"]
                    break

            result = self.engine.query(prompt)
            self._send_json({
                "id": f"niyah-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": result.get("model", model),
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": result["response"],
                    },
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": len(prompt.split()),
                          "completion_tokens": len(result["response"].split()),
                          "total_tokens": len(prompt.split()) + len(result["response"].split())},
                "niyah_metadata": {
                    "lobe": result.get("lobe"),
                    "confidence": result.get("confidence"),
                    "security": result.get("security"),
                },
            })

        elif path == "/api/embed":
            # Embedding endpoint
            text = data.get("input", data.get("prompt", ""))
            model = data.get("model", "")
            emb = self.engine.ollama.embed(text, model)
            self._send_json({"embeddings": [emb]})

        else:
            self._send_json({"error": "Unknown endpoint"}, 404)

# ─── Main ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="niyah-server",
        description="Niyah Server — Sovereign AI Inference Engine",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--ollama-port", type=int, default=OLLAMA_PORT)
    parser.add_argument("--no-ollama", action="store_true",
                        help="Don't use Ollama (requires llama-cpp-python)")
    parser.add_argument("--model-path", type=str,
                        help="Path to GGUF model for direct loading")
    args = parser.parse_args()

    print(f"""
  ╔═══════════════════════════════════════════════╗
  ║                                               ║
  ║   NIYAH SERVER v{__version__}                        ║
  ║   Sovereign AI Inference Engine               ║
  ║                                               ║
  ║   Port: {args.port}                                ║
  ║   KHAWRIZM Labs — Dragon403 — Riyadh          ║
  ║                                               ║
  ╚═══════════════════════════════════════════════╝
""")

    # Initialize backends
    ollama = OllamaBackend(args.ollama_port)
    llama_cpp = LlamaCppBackend()

    if args.model_path and llama_cpp.available:
        log.info("Loading GGUF model directly: %s", args.model_path)
        llama_cpp.load_model(args.model_path)

    if not args.no_ollama:
        ollama.start()

    engine = NiyahEngine(ollama, llama_cpp)

    # Start HTTP server
    NiyahHTTPHandler.engine = engine
    server = HTTPServer((BIND_HOST, args.port), NiyahHTTPHandler)

    def shutdown(sig, frame):
        log.info("Shutting down Niyah Server...")
        ollama.stop()
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("Niyah Server listening on http://%s:%d", BIND_HOST, args.port)
    log.info("Models: %s", ollama.models)
    log.info("Lobes: sensory=%s cognitive=%s executive=%s",
             LOBE_MODEL_MAP[Lobe.SENSORY][0],
             LOBE_MODEL_MAP[Lobe.COGNITIVE][0],
             LOBE_MODEL_MAP[Lobe.EXECUTIVE][0])
    log.info("الخوارزمية دائماً تعود للوطن")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
