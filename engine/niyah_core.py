#!/usr/bin/env python3
"""
NIYAH ENGINE v5 — Sovereign Three-Lobe AI Orchestrator
KHAWRIZM Labs — Dragon403 — Riyadh

Three-Lobe Architecture:
  - SENSORY:   Arabic NLP, user input parsing, context awareness
  - COGNITIVE: Deep reasoning, analysis, chain-of-thought
  - EXECUTIVE: Code generation, task execution, system control

Arabic-First · Sovereign · Zero Telemetry · Local-Only
"""
from __future__ import annotations
import os, sys, json, time, logging, argparse, hashlib, threading
from dataclasses import dataclass, field, asdict
from typing import Optional, Generator
from enum import Enum
from pathlib import Path
from collections import defaultdict
import urllib.request
import urllib.error

__version__ = "5.0.0"

# ─── Configuration ──────────────────────────────────────────────────
NIYAH_PARAMS = {
    "temperature": 0.3,
    "frequency_penalty": 0.5,
    "presence_penalty": 0.3,
    "max_tokens": 4096,
    "top_p": 0.85,
    "repeat_penalty": 1.15,
    "directive_ar": "لا تخترع معلومات. إذا لم تعلم قل لا أعلم. أجب بالعربية أولاً.",
    "directive_en": "Never fabricate. Say 'I don't know' if uncertain. Be precise and concise."
}

OLLAMA_URL = os.getenv("NIYAH_OLLAMA_URL", "http://127.0.0.1:11434")
LOG_DIR    = Path(os.getenv("NIYAH_LOG_DIR", "/var/log/niyah"))
DATA_DIR   = Path(os.getenv("NIYAH_DATA_DIR", "/var/lib/niyah"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [NIYAH:%(name)s] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "niyah.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("core")

# ─── Enums & Data Classes ──────────────────────────────────────────
class Lobe(Enum):
    EXECUTIVE = "executive"
    SENSORY   = "sensory"
    COGNITIVE = "cognitive"

class TaskType(Enum):
    CHAT     = "chat"
    CODE     = "code"
    ANALYZE  = "analyze"
    TRANSLATE = "translate"
    SYSTEM   = "system"
    SECURITY = "security"

@dataclass
class LobeConfig:
    primary_model: str
    fallback_model: str
    system_prompt: str
    temperature: float
    max_tokens: int

@dataclass
class NiyahRequest:
    query: str
    lobe: Optional[Lobe] = None
    task_type: Optional[TaskType] = None
    context: list[dict] = field(default_factory=list)
    session_id: str = ""
    stream: bool = False

@dataclass
class NiyahResponse:
    text: str
    lobe: Lobe
    model: str
    latency_ms: int = 0
    tokens_used: int = 0
    sovereign: bool = True
    session_id: str = ""
    task_type: str = ""

    def to_json(self) -> str:
        d = asdict(self)
        d["lobe"] = self.lobe.value
        return json.dumps(d, ensure_ascii=False, indent=2)

# ─── Ollama Client with Retry & Streaming ──────────────────────────
class OllamaClient:
    def __init__(self, url: str = OLLAMA_URL, timeout: int = 120):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self._model_cache: list[str] = []
        self._cache_time: float = 0

    def models(self) -> list[str]:
        if self._model_cache and (time.time() - self._cache_time) < 30:
            return self._model_cache
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=5) as r:
                data = json.loads(r.read())
                self._model_cache = [m["name"] for m in data.get("models", [])]
                self._cache_time = time.time()
                return self._model_cache
        except Exception as e:
            log.warning(f"Cannot reach Ollama: {e}")
            return self._model_cache or []

    def generate(self, model: str, prompt: str, system: str = "",
                 temperature: float = 0.3, max_tokens: int = 4096) -> str:
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "top_p": NIYAH_PARAMS["top_p"],
                "repeat_penalty": NIYAH_PARAMS["repeat_penalty"],
            }
        }).encode()

        req = urllib.request.Request(
            f"{self.url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read())
                    return data.get("response", "")
            except urllib.error.URLError as e:
                log.warning(f"Ollama attempt {attempt+1}/3 failed: {e}")
                if attempt < 2:
                    time.sleep(1 * (attempt + 1))
        return ""

    def generate_stream(self, model: str, prompt: str,
                        system: str = "") -> Generator[str, None, None]:
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": True,
            "options": {
                "temperature": NIYAH_PARAMS["temperature"],
                "num_predict": NIYAH_PARAMS["max_tokens"],
            }
        }).encode()

        req = urllib.request.Request(
            f"{self.url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                for line in r:
                    if line.strip():
                        chunk = json.loads(line)
                        if "response" in chunk:
                            yield chunk["response"]
                        if chunk.get("done"):
                            break
        except Exception as e:
            log.error(f"Stream error: {e}")
            yield f"[Stream error: {e}]"

    def health(self) -> dict:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=3) as r:
                models = json.loads(r.read()).get("models", [])
                return {
                    "status": "online",
                    "models": len(models),
                    "url": self.url
                }
        except Exception:
            return {"status": "offline", "models": 0, "url": self.url}

# ─── Session Memory ────────────────────────────────────────────────
class SessionMemory:
    """Persistent session storage — conversations survive restarts."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.dir = data_dir / "sessions"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    def _path(self, sid: str) -> Path:
        safe = hashlib.sha256(sid.encode()).hexdigest()[:16]
        return self.dir / f"{safe}.json"

    def load(self, sid: str) -> list[dict]:
        with self._lock:
            if sid in self._cache:
                return self._cache[sid]
            p = self._path(sid)
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    self._cache[sid] = data
                    return data
                except Exception:
                    return []
            return []

    def save(self, sid: str, messages: list[dict]):
        with self._lock:
            messages = messages[-50:]
            self._cache[sid] = messages
            self._path(sid).write_text(
                json.dumps(messages, ensure_ascii=False, indent=1),
                encoding="utf-8"
            )

    def append(self, sid: str, role: str, content: str):
        msgs = self.load(sid)
        msgs.append({"role": role, "content": content, "ts": time.time()})
        self.save(sid, msgs)

# ─── Language Detection ────────────────────────────────────────────
class LanguageDetector:
    ARABIC_RANGE = range(0x0600, 0x06FF + 1)

    @staticmethod
    def detect(text: str) -> str:
        if not text:
            return "en"
        ar_count = sum(1 for c in text if ord(c) in LanguageDetector.ARABIC_RANGE)
        ratio = ar_count / max(len(text.replace(" ", "")), 1)
        return "ar" if ratio > 0.15 else "en"

    @staticmethod
    def is_arabic(text: str) -> bool:
        return LanguageDetector.detect(text) == "ar"

# ─── Lobe Router ───────────────────────────────────────────────────
class LobeRouter:
    """Routes queries to the appropriate lobe based on intent analysis."""

    COGNITIVE_TRIGGERS = {
        "en": ["analyze", "explain", "compare", "design", "why", "how does",
               "architecture", "trade-off", "evaluate", "reason", "think",
               "debug", "review", "audit", "threat model"],
        "ar": ["حلل", "اشرح", "قارن", "صمم", "لماذا", "كيف", "فكر",
               "راجع", "دقق", "افحص"]
    }
    EXECUTIVE_TRIGGERS = {
        "en": ["write", "create", "build", "implement", "fix", "deploy",
               "generate", "code", "script", "install", "run", "execute",
               "compile", "push", "commit"],
        "ar": ["اكتب", "أنشئ", "ابني", "نفذ", "صلح", "شغل", "ارفع"]
    }
    SECURITY_TRIGGERS = {
        "en": ["vulnerability", "exploit", "cve", "pentest", "scan",
               "firewall", "phalanx", "telemetry", "block"],
        "ar": ["ثغرة", "اختراق", "فحص", "جدار", "حماية"]
    }

    @staticmethod
    def route(query: str) -> tuple[Lobe, TaskType]:
        lang = LanguageDetector.detect(query)
        q = query.lower()

        for trigger in LobeRouter.SECURITY_TRIGGERS.get(lang, []):
            if trigger in q:
                return Lobe.COGNITIVE, TaskType.SECURITY

        for trigger in LobeRouter.COGNITIVE_TRIGGERS.get(lang, []):
            if trigger in q:
                return Lobe.COGNITIVE, TaskType.ANALYZE

        for trigger in LobeRouter.EXECUTIVE_TRIGGERS.get(lang, []):
            if trigger in q:
                return Lobe.EXECUTIVE, TaskType.CODE

        if lang == "ar":
            return Lobe.SENSORY, TaskType.CHAT

        return Lobe.EXECUTIVE, TaskType.CHAT

# ─── Model Selector ────────────────────────────────────────────────
class ModelSelector:
    """RAM-aware model selection with lobe-specific preferences."""

    MODEL_PRIORITY = [
        {"name": "niyah:sovereign", "ram_gb": 5.5, "lobes": [Lobe.COGNITIVE]},
        {"name": "niyah:writer",    "ram_gb": 3.5, "lobes": [Lobe.SENSORY]},
        {"name": "niyah:v4",        "ram_gb": 3.5, "lobes": [Lobe.EXECUTIVE, Lobe.SENSORY]},
        {"name": "niyah:v3",        "ram_gb": 3.5, "lobes": [Lobe.EXECUTIVE, Lobe.SENSORY]},
        {"name": "deepseek-r1:8b",  "ram_gb": 12,  "lobes": [Lobe.COGNITIVE]},
        {"name": "deepseek-r1:1.5b","ram_gb": 3.5, "lobes": [Lobe.COGNITIVE, Lobe.EXECUTIVE]},
        {"name": "llama3.2:3b",     "ram_gb": 5.0, "lobes": [Lobe.EXECUTIVE]},
        {"name": "llama3:8b",       "ram_gb": 12,  "lobes": [Lobe.COGNITIVE]},
    ]

    def __init__(self, available_models: list[str], max_ram_gb: float = 16.0):
        self.available = set(available_models)
        self.max_ram = max_ram_gb

    def select(self, lobe: Lobe) -> str:
        for m in self.MODEL_PRIORITY:
            if (m["name"] in self.available and
                m["ram_gb"] <= self.max_ram and
                lobe in m["lobes"]):
                return m["name"]
        for m in self.MODEL_PRIORITY:
            if m["name"] in self.available and m["ram_gb"] <= self.max_ram:
                return m["name"]
        return list(self.available)[0] if self.available else "deepseek-r1:1.5b"

# ─── Main Engine ───────────────────────────────────────────────────
class NiyahEngine:
    IDENTITY = {
        "en": (
            "I am NIYAH (نيّة) — the Sovereign AI Engine built by Sulaiman Alshammari "
            "at KHAWRIZM Labs, Riyadh. I use a Three-Lobe architecture (Sensory, "
            "Cognitive, Executive) for Arabic-first, zero-telemetry AI. I am NOT "
            "ChatGPT, Claude, Gemini, or any corporate AI. I run 100% locally."
        ),
        "ar": (
            "أنا نيّة (NIYAH) — محرك ذكاء اصطناعي سيادي من مختبرات الخوارزمي، الرياض. "
            "أعمل بمنهجية الفصوص الثلاثة (حسي، إدراكي، تنفيذي). أنا لست ChatGPT ولا "
            "Claude ولا Gemini. أعمل 100% محلياً بدون أي بيانات ترسل للخارج."
        )
    }

    ID_TRIGGERS = {
        "are you", "r u", "who are you", "what are you",
        "related to", "gemini", "claude", "gpt", "chatgpt", "copilot",
        "هل أنت", "هل انت", "من صنعك", "من أنت", "من انت",
        "ايش انت", "مين انت"
    }

    LOBE_PROMPTS = {
        Lobe.SENSORY: (
            "أنت NIYAH — الفص الحسي. تخصصك: فهم اللغة العربية، تحليل السياق، "
            "الترجمة، وفهم نية المستخدم. أجب بالعربية بشكل طبيعي ودقيق. "
            "لا تخترع معلومات أبداً."
        ),
        Lobe.COGNITIVE: (
            "You are NIYAH — Cognitive Lobe. Your specialty: deep reasoning, "
            "chain-of-thought analysis, architecture design, code review, "
            "security auditing, and comparative analysis. Think step by step. "
            "Never fabricate information. If uncertain, say so."
        ),
        Lobe.EXECUTIVE: (
            "You are NIYAH — Executive Lobe. Your specialty: code generation, "
            "task execution, system commands, deployment scripts, and building. "
            "Write clean, production-grade code. Use TypeScript, Python, Rust, "
            "or Bash as appropriate. No telemetry. Local-first. Saudi context "
            "(PDPL, NCA-ECC, Vision 2030). Sign as نية (Niyah Engine)."
        ),
    }

    def __init__(self, ollama_url: str = OLLAMA_URL, max_ram_gb: float = 16.0):
        self.ollama = OllamaClient(ollama_url)
        self.memory = SessionMemory()
        self.router = LobeRouter()
        self.lang_detect = LanguageDetector()

        models = self.ollama.models()
        self.selector = ModelSelector(models, max_ram_gb)
        self._active_model = self.selector.select(Lobe.EXECUTIVE)

        log.info(f"NIYAH v{__version__} initialized | models={len(models)} | "
                 f"default={self._active_model}")

    def _is_identity_query(self, text: str) -> bool:
        lower = text.lower()
        return any(trigger in lower for trigger in self.ID_TRIGGERS)

    def query(self, req: NiyahRequest) -> NiyahResponse:
        t0 = time.time()
        lang = self.lang_detect.detect(req.query)
        sid = req.session_id or "default"

        if self._is_identity_query(req.query):
            return NiyahResponse(
                text=self.IDENTITY[lang],
                lobe=Lobe.EXECUTIVE,
                model="niyah-identity",
                latency_ms=int((time.time() - t0) * 1000),
                session_id=sid,
                task_type="identity"
            )

        lobe, task_type = self.router.route(req.query)
        if req.lobe:
            lobe = req.lobe
        if req.task_type:
            task_type = req.task_type

        model = self.selector.select(lobe)
        system_prompt = self.LOBE_PROMPTS[lobe]

        history = self.memory.load(sid) if sid != "default" else req.context or []
        ctx_lines = []
        for m in history[-8:]:
            role = "User" if m.get("role") == "user" else "NIYAH"
            ctx_lines.append(f"{role}: {m.get('content', '')}")

        full_prompt = "\n".join(ctx_lines + [f"User: {req.query}", "NIYAH:"])

        try:
            text = self.ollama.generate(
                model=model,
                prompt=full_prompt,
                system=system_prompt,
                temperature=NIYAH_PARAMS["temperature"],
                max_tokens=NIYAH_PARAMS["max_tokens"]
            )
            text = text.strip()
            if not text:
                text = "لا أعلم." if lang == "ar" else "I don't have enough information."
        except Exception as e:
            log.error(f"Generation failed: {e}")
            text = f"خطأ في الاتصال بـ Ollama: {e}" if lang == "ar" else f"Ollama error: {e}"

        if sid != "default":
            self.memory.append(sid, "user", req.query)
            self.memory.append(sid, "assistant", text)

        latency = int((time.time() - t0) * 1000)
        log.info(f"[{lobe.value}] model={model} latency={latency}ms "
                 f"task={task_type.value} lang={lang}")

        return NiyahResponse(
            text=text,
            lobe=lobe,
            model=model,
            latency_ms=latency,
            sovereign=True,
            session_id=sid,
            task_type=task_type.value
        )

    def query_stream(self, req: NiyahRequest) -> Generator[str, None, None]:
        lobe, _ = self.router.route(req.query)
        if req.lobe:
            lobe = req.lobe
        model = self.selector.select(lobe)
        system_prompt = self.LOBE_PROMPTS[lobe]

        yield from self.ollama.generate_stream(
            model=model,
            prompt=f"User: {req.query}\nNIYAH:",
            system=system_prompt
        )

    def health(self) -> dict:
        ollama_health = self.ollama.health()
        return {
            "engine": "niyah",
            "version": __version__,
            "ollama": ollama_health,
            "default_model": self._active_model,
            "sovereign": True
        }

# ─── HTTP API Server ───────────────────────────────────────────────
def _run_server(engine: NiyahEngine, port: int):
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class NiyahHandler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _json_response(self, code: int, data: dict):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            if self.path == "/health":
                self._json_response(200, engine.health())
            elif self.path == "/api/models":
                self._json_response(200, {"models": engine.ollama.models()})
            elif self.path == "/api/version":
                self._json_response(200, {
                    "engine": "niyah",
                    "version": __version__,
                    "codename": "Dragon"
                })
            else:
                self._json_response(404, {"error": "not found"})

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
            except Exception:
                self._json_response(400, {"error": "invalid JSON"})
                return

            if self.path == "/api/query":
                lobe = None
                if body.get("lobe"):
                    try:
                        lobe = Lobe[body["lobe"].upper()]
                    except KeyError:
                        pass

                task_type = None
                if body.get("task_type"):
                    try:
                        task_type = TaskType[body["task_type"].upper()]
                    except KeyError:
                        pass

                req = NiyahRequest(
                    query=body.get("query", ""),
                    lobe=lobe,
                    task_type=task_type,
                    context=body.get("context", []),
                    session_id=body.get("session_id", ""),
                    stream=body.get("stream", False)
                )

                if req.stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self._cors()
                    self.end_headers()
                    for chunk in engine.query_stream(req):
                        self.wfile.write(f"data: {json.dumps({'text': chunk})}\n\n".encode())
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                else:
                    resp = engine.query(req)
                    self._json_response(200, json.loads(resp.to_json()))

            elif self.path == "/api/generate":
                req = NiyahRequest(
                    query=body.get("prompt", body.get("query", "")),
                    context=body.get("context", [])
                )
                resp = engine.query(req)
                self._json_response(200, json.loads(resp.to_json()))
            else:
                self._json_response(404, {"error": "not found"})

    server = HTTPServer(("0.0.0.0", port), NiyahHandler)
    log.info(f"NIYAH API v{__version__} → http://0.0.0.0:{port}")
    log.info(f"Endpoints: /health, /api/query, /api/generate, /api/models, /api/version")
    server.serve_forever()

# ─── Interactive REPL ──────────────────────────────────────────────
def _repl(engine: NiyahEngine):
    print(f"\n  ╔═══════════════════════════════════════╗")
    print(f"  ║  NIYAH v{__version__}                        ║")
    print(f"  ║  Model: {engine._active_model:<28s} ║")
    print(f"  ║  Type 'exit' or Ctrl+C to quit        ║")
    print(f"  ╚═══════════════════════════════════════╝\n")

    session_id = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    while True:
        try:
            q = input("  You: ").strip()
            if not q:
                continue
            if q.lower() in ("exit", "quit", "خروج"):
                break

            resp = engine.query(NiyahRequest(
                query=q,
                session_id=session_id
            ))
            print(f"\n  NIYAH [{resp.lobe.value} · {resp.model} · {resp.latency_ms}ms]:")
            print(f"  {resp.text}\n")

        except (KeyboardInterrupt, EOFError):
            break

    print("\n  نيّة — خروج (Niyah — Exit)\n")

# ─── CLI ───────────────────────────────────────────────────────────
def cli():
    p = argparse.ArgumentParser(
        prog="niyah",
        description="NIYAH Engine v5 — Sovereign Three-Lobe AI"
    )
    p.add_argument("query", nargs="?", help="Query to process")
    p.add_argument("--lobe", choices=["executive", "sensory", "cognitive"])
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.add_argument("--models", action="store_true", help="List available models")
    p.add_argument("--health", action="store_true", help="Check engine health")
    p.add_argument("-i", "--interactive", action="store_true", help="Interactive REPL")
    p.add_argument("--server", action="store_true", help="Start HTTP API server")
    p.add_argument("--port", type=int, default=7474, help="API server port")
    p.add_argument("--ollama-url", default=OLLAMA_URL, help="Ollama endpoint URL")
    p.add_argument("--max-ram", type=float, default=16.0, help="Max RAM in GB")
    p.add_argument("--version", action="version", version=f"NIYAH v{__version__}")
    args = p.parse_args()

    engine = NiyahEngine(ollama_url=args.ollama_url, max_ram_gb=args.max_ram)

    if args.models:
        models = engine.ollama.models()
        print(f"\n  Available models ({len(models)}):")
        for m in models:
            print(f"  • {m}")
        return

    if args.health:
        h = engine.health()
        print(json.dumps(h, indent=2, ensure_ascii=False))
        return

    if args.server:
        _run_server(engine, args.port)
        return

    if args.interactive:
        _repl(engine)
        return

    if args.query:
        lobe = Lobe[args.lobe.upper()] if args.lobe else None
        resp = engine.query(NiyahRequest(query=args.query, lobe=lobe))
        if args.json:
            print(resp.to_json())
        else:
            print(f"\n[NIYAH:{resp.lobe.value}:{resp.model}:{resp.latency_ms}ms]")
            print(resp.text)
    else:
        p.print_help()

if __name__ == "__main__":
    cli()
