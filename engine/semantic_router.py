#!/usr/bin/env python3
"""
NIYAH SEMANTIC ROUTER v2 — Intent Classification via Embeddings
Uses Ollama's local embedding API — zero extra downloads needed.

Unlike keyword matching (v1), this understands MEANING:
  "سوي لي سكريبت بايثون" → Executive (even without "write")
  "ياخي الـ API بطيئة ليش" → Cognitive (even without "analyze")

Three-layer classification:
  Layer 1: Ollama Embedding similarity (semantic)
  Layer 2: Arabic root morphology (linguistic)
  Layer 3: Phalanx security gate (sovereign)

KHAWRIZM Labs — Dragon403 — Riyadh
"""
from __future__ import annotations
import json, time, math, hashlib
from typing import Optional
from enum import Enum
from pathlib import Path
import urllib.request
import urllib.error

__version__ = "2.0.0"

OLLAMA_URL = "http://127.0.0.1:11434"

class Lobe(Enum):
    SENSORY   = "sensory"
    COGNITIVE = "cognitive"
    EXECUTIVE = "executive"

class SecurityVerdict(Enum):
    CLEAN    = "clean"
    BLOCKED  = "blocked"
    FLAGGED  = "flagged"

# ─── Lobe Training Examples ───────────────────────────────────────
# Each lobe has ~40 examples in Arabic + English + mixed
# The router learns MEANING, not keywords

LOBE_EXAMPLES = {
    Lobe.SENSORY: [
        # Arabic understanding, translation, explanation
        "اشرح لي كيف يعمل هذا", "كيف يعمل Docker", "ما هو Kubernetes",
        "ترجم هذا النص للعربي", "فهمني الكود هذا", "عطني مثال بسيط",
        "شلون أسوي هالشي", "والله أبغى أعرف", "وضح لي المفهوم",
        "ما معنى polymorphism", "اشرح الـ async await", "كيف أبدأ بالبرمجة",
        "explain this concept", "what is machine learning", "how does TCP work",
        "what does this error mean", "summarize this article", "describe the architecture",
        "teach me about databases", "what are design patterns", "help me understand React",
        "شرح مبسط للـ API", "كيف أتعلم Rust", "وش الفرق بين Docker و VM",
        "فهمني الـ three-lobe architecture", "اشرح لي نظام التشغيل",
        "كيف يشتغل الـ scheduler", "ما هي الخوارزميات", "عطني شرح للـ blockchain",
        "explain quantum computing simply", "what is zero knowledge proof",
        "describe how neural networks learn", "how does DNS resolution work",
        "ايش يعني sovereign computing", "كيف يحمي Phalanx الخصوصية",
    ],
    Lobe.COGNITIVE: [
        # Analysis, debugging, security, review, reasoning
        "حلل هذا الكود وقلي المشاكل", "ليش الـ API بطيئة", "لماذا يتوقف البرنامج",
        "راجع الكود هذا", "دقق في الأخطاء", "افحص الثغرات الأمنية",
        "ما السبب في هذا الخطأ", "كيف أصلح هذا الباق", "قارن بين الطريقتين",
        "هل هذا الكود آمن", "تحليل أمني للـ endpoint", "audit the security",
        "analyze this vulnerability", "why is this slow", "debug this error",
        "review this pull request", "find the bug in this code", "compare React vs Vue",
        "what's wrong with this architecture", "evaluate the performance",
        "check for SQL injection", "is this PDPL compliant", "threat model this API",
        "scan for XSS vulnerabilities", "pentest this endpoint", "review the firewall rules",
        "ليش الميموري ممتلئة", "حلل الـ network traffic", "راجع إعدادات Phalanx",
        "افحص الـ logs عن أي تسريب", "قيم أداء الـ scheduler", "تحليل جنائي رقمي",
        "هل في تيليمتري مخفية", "دقق في شهادات SSL", "راجع سياسة الـ CORS",
        "analyze memory leak", "profile CPU usage", "evaluate algorithm complexity",
        "assess data sovereignty compliance", "audit authentication flow",
    ],
    Lobe.EXECUTIVE: [
        # Code generation, building, deployment, execution
        "اكتب كود بايثون", "سوي لي سكريبت", "أنشئ API بالـ FastAPI",
        "ابني صفحة ويب", "نفذ هذا التصميم", "صلح الكود", "شغل الأمر",
        "اكتب Dockerfile", "سوي لي deploy script", "ابني قاعدة بيانات",
        "write a Python function", "create a REST API", "build a React component",
        "implement the algorithm", "generate a Bash script", "fix this code",
        "deploy to production", "write unit tests", "create a Docker compose",
        "build a CLI tool", "implement authentication", "write a Makefile",
        "سوي كلاس بالـ Rust", "اكتب kernel module بالـ C", "ابني P2P server",
        "أنشئ مشروع Vite جديد", "سوي GitHub Actions workflow", "اكتب migration SQL",
        "generate TypeScript types", "create a WebSocket server", "write a cron job",
        "implement rate limiting", "build a file upload API", "create an OAuth flow",
        "write a Terraform config", "generate Nginx config", "implement caching layer",
        "compile the kernel module", "push to production", "execute the migration",
    ],
}

# ─── Arabic Root Morphology ───────────────────────────────────────
# Maps Arabic roots to lobe affinity (avoids needing tashaphyne library)

ARABIC_ROOTS = {
    # Sensory roots (understanding, explaining)
    "شرح": Lobe.SENSORY, "فهم": Lobe.SENSORY, "ترجم": Lobe.SENSORY,
    "وصف": Lobe.SENSORY, "بين": Lobe.SENSORY, "وضح": Lobe.SENSORY,
    "عرف": Lobe.SENSORY, "درس": Lobe.SENSORY, "علم": Lobe.SENSORY,
    # Cognitive roots (analysis, reasoning)
    "حلل": Lobe.COGNITIVE, "فحص": Lobe.COGNITIVE, "دقق": Lobe.COGNITIVE,
    "راجع": Lobe.COGNITIVE, "قارن": Lobe.COGNITIVE, "قيم": Lobe.COGNITIVE,
    "صلح": Lobe.COGNITIVE, "اختبر": Lobe.COGNITIVE, "حقق": Lobe.COGNITIVE,
    "افحص": Lobe.COGNITIVE, "شخص": Lobe.COGNITIVE,
    # Executive roots (creation, action)
    "كتب": Lobe.EXECUTIVE, "بنى": Lobe.EXECUTIVE, "أنشأ": Lobe.EXECUTIVE,
    "نفذ": Lobe.EXECUTIVE, "سوى": Lobe.EXECUTIVE, "شغل": Lobe.EXECUTIVE,
    "رفع": Lobe.EXECUTIVE, "حمل": Lobe.EXECUTIVE, "ركب": Lobe.EXECUTIVE,
    "صنع": Lobe.EXECUTIVE, "ولد": Lobe.EXECUTIVE,
}

# ─── Phalanx Security Patterns ────────────────────────────────────

TELEMETRY_PATTERNS = [
    "send data to", "upload to microsoft", "phone home", "telemetry endpoint",
    "track user", "analytics beacon", "ارسل بيانات", "تتبع المستخدم",
    "exfiltrate", "c2 server", "reverse shell to external",
]

SOVEREIGN_BLOCKED_IPS = [
    "13.64.", "20.33.", "20.40.", "20.184.", "64.4.",
    "142.250.", "172.217.", "vortex.data.microsoft",
]

# ─── Embedding Cache ──────────────────────────────────────────────

class EmbeddingCache:
    """Caches Ollama embeddings to avoid re-computing for known examples."""

    def __init__(self, cache_dir: Path = Path("/tmp/niyah-emb-cache")):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._mem_cache: dict[str, list[float]] = {}

    def _key(self, text: str, model: str) -> str:
        return hashlib.sha256(f"{model}:{text}".encode()).hexdigest()[:16]

    def get(self, text: str, model: str) -> list[float] | None:
        key = self._key(text, model)
        if key in self._mem_cache:
            return self._mem_cache[key]
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text())
                self._mem_cache[key] = data
                return data
            except Exception:
                pass
        return None

    def put(self, text: str, model: str, embedding: list[float]):
        key = self._key(text, model)
        self._mem_cache[key] = embedding
        try:
            path = self.cache_dir / f"{key}.json"
            path.write_text(json.dumps(embedding))
        except Exception:
            pass

# ─── Ollama Embedding Client ─────────────────────────────────────

class OllamaEmbedder:
    """Gets embeddings from Ollama's /api/embed endpoint."""

    def __init__(self, url: str = OLLAMA_URL, model: str = ""):
        self.url = url.rstrip("/")
        self.model = model or self._pick_embed_model()
        self.cache = EmbeddingCache()

    def _pick_embed_model(self) -> str:
        """Auto-detect best available embedding model."""
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=3) as r:
                models = [m["name"] for m in json.loads(r.read()).get("models", [])]
        except Exception:
            models = []

        # Prefer dedicated embedding models, fall back to any available LLM
        for preferred in ["nomic-embed-text", "mxbai-embed-large",
                          "all-minilm", "bge-m3", "snowflake-arctic-embed"]:
            for m in models:
                if preferred in m:
                    return m

        # Fall back to any available model (Ollama can generate embeddings from any)
        for m in models:
            if "niyah" in m or "llama" in m or "deepseek" in m:
                return m

        return "nomic-embed-text"

    def embed(self, text: str) -> list[float]:
        cached = self.cache.get(text, self.model)
        if cached:
            return cached

        payload = json.dumps({"model": self.model, "input": text}).encode()
        req = urllib.request.Request(
            f"{self.url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
                emb = data.get("embeddings", [[]])[0]
                if emb:
                    self.cache.put(text, self.model, emb)
                    return emb
        except Exception:
            pass
        return []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

# ─── Math Utilities ───────────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

# ─── Semantic Router ──────────────────────────────────────────────

class NiyahSemanticRouter:
    """
    Three-layer intent classifier:
      Layer 1: Embedding similarity (semantic understanding)
      Layer 2: Arabic root morphology (linguistic boost)
      Layer 3: Phalanx security gate (sovereign protection)
    """

    def __init__(self, ollama_url: str = OLLAMA_URL):
        self.embedder = OllamaEmbedder(ollama_url)
        self._lobe_embeddings: dict[str, list[list[float]]] = {}
        self._initialized = False

    def initialize(self):
        """Pre-compute embeddings for all training examples."""
        if self._initialized:
            return

        print(f"[NIYAH ROUTER v2] Initializing semantic router with {self.embedder.model}...")
        t0 = time.time()

        for lobe in Lobe:
            examples = LOBE_EXAMPLES[lobe]
            embeddings = self.embedder.embed_batch(examples)
            self._lobe_embeddings[lobe.value] = [e for e in embeddings if e]

        elapsed = time.time() - t0
        total = sum(len(v) for v in self._lobe_embeddings.values())
        print(f"[NIYAH ROUTER v2] Ready — {total} examples embedded in {elapsed:.1f}s")
        self._initialized = True

    # ── Layer 1: Semantic Embedding Similarity ────────────────────

    def _semantic_scores(self, query: str) -> dict[str, float]:
        if not self._initialized:
            self.initialize()

        q_emb = self.embedder.embed(query)
        if not q_emb:
            return {l.value: 0.0 for l in Lobe}

        scores = {}
        for lobe_name, emb_list in self._lobe_embeddings.items():
            if not emb_list:
                scores[lobe_name] = 0.0
                continue
            sims = [cosine_similarity(q_emb, e) for e in emb_list]
            # Use top-3 average for robustness
            top_k = sorted(sims, reverse=True)[:3]
            scores[lobe_name] = sum(top_k) / len(top_k) if top_k else 0.0

        return scores

    # ── Layer 2: Arabic Root Morphology ───────────────────────────

    def _arabic_root_boost(self, query: str) -> dict[str, float]:
        boost = {l.value: 0.0 for l in Lobe}
        words = query.split()

        for word in words:
            clean = word.strip(".,!?؟،؛\"'()[]{}»«")
            for root, lobe in ARABIC_ROOTS.items():
                if root in clean or clean in root:
                    boost[lobe.value] += 0.08
                    break

        # Dialect detection boost for Sensory
        gulf_markers = ["ياخي", "وش", "شلون", "كذا", "ابغى", "تبغى",
                        "والله", "يالله", "خلاص", "طيب", "بس"]
        if any(m in query for m in gulf_markers):
            boost[Lobe.SENSORY.value] += 0.05

        return boost

    # ── Layer 3: Phalanx Security Gate ────────────────────────────

    def _phalanx_check(self, query: str) -> SecurityVerdict:
        lower = query.lower()

        for pattern in TELEMETRY_PATTERNS:
            if pattern in lower:
                return SecurityVerdict.BLOCKED

        for ip in SOVEREIGN_BLOCKED_IPS:
            if ip in lower:
                return SecurityVerdict.FLAGGED

        return SecurityVerdict.CLEAN

    # ── Main Classification ───────────────────────────────────────

    def classify(self, query: str,
                 force_lobe: str | None = None) -> dict:
        t0 = time.time()

        if not query.strip():
            return {"lobe": Lobe.SENSORY.value, "confidence": 0.0,
                    "reason": "empty_query"}

        # Manual override
        if force_lobe and force_lobe in [l.value for l in Lobe]:
            return {"lobe": force_lobe, "confidence": 1.0,
                    "reason": "manual_override"}

        # Layer 3: Security check first
        security = self._phalanx_check(query)
        if security == SecurityVerdict.BLOCKED:
            return {
                "lobe": Lobe.COGNITIVE.value,
                "confidence": 1.0,
                "security": "BLOCKED_BY_PHALANX",
                "reason": "Telemetry/exfiltration pattern detected",
                "blocked": True,
            }

        # Layer 1: Semantic similarity
        semantic = self._semantic_scores(query)

        # Layer 2: Arabic root boost
        root_boost = self._arabic_root_boost(query)

        # Combine scores
        final_scores = {}
        for lobe in Lobe:
            name = lobe.value
            final_scores[name] = semantic.get(name, 0.0) + root_boost.get(name, 0.0)

        # Pick winner
        best_lobe = max(final_scores, key=final_scores.get)
        best_score = final_scores[best_lobe]

        # Confidence normalization (0-1 scale)
        total = sum(final_scores.values())
        confidence = best_score / total if total > 0 else 0.0

        # Hybrid routing: if top two are close, flag it
        sorted_scores = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
        hybrid = False
        secondary = None
        if len(sorted_scores) >= 2:
            gap = sorted_scores[0][1] - sorted_scores[1][1]
            if gap < 0.05 and sorted_scores[1][1] > 0.3:
                hybrid = True
                secondary = sorted_scores[1][0]

        latency = round((time.time() - t0) * 1000, 1)

        return {
            "lobe": best_lobe,
            "confidence": round(confidence, 3),
            "scores": {k: round(v, 4) for k, v in final_scores.items()},
            "semantic_scores": {k: round(v, 4) for k, v in semantic.items()},
            "root_boost": {k: round(v, 4) for k, v in root_boost.items()},
            "hybrid": hybrid,
            "secondary_lobe": secondary,
            "security": security.value,
            "latency_ms": latency,
            "model": self.embedder.model,
            "reason": "semantic_embedding + arabic_root + phalanx",
        }

# ─── CLI ──────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(prog="niyah-router", description="Niyah Semantic Router v2")
    p.add_argument("query", nargs="?")
    p.add_argument("-i", "--interactive", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--ollama-url", default=OLLAMA_URL)
    args = p.parse_args()

    router = NiyahSemanticRouter(args.ollama_url)
    router.initialize()

    if args.interactive:
        print(f"\n  NIYAH SEMANTIC ROUTER v{__version__}")
        print(f"  Model: {router.embedder.model}")
        print(f"  Type 'exit' to quit\n")
        while True:
            try:
                q = input("  Query: ").strip()
                if q.lower() in ("exit", "quit", "خروج"):
                    break
                r = router.classify(q)
                print(f"  → Lobe: {r['lobe']} | Confidence: {r['confidence']}")
                print(f"    Scores: {r['scores']}")
                if r.get('hybrid'):
                    print(f"    HYBRID: also consider {r['secondary_lobe']}")
                if r.get('security') != 'clean':
                    print(f"    PHALANX: {r['security']}")
                print()
            except (KeyboardInterrupt, EOFError):
                break
    elif args.query:
        r = router.classify(args.query)
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            print(f"[{r['lobe'].upper()}] confidence={r['confidence']} latency={r['latency_ms']}ms")
            print(f"  scores: {r['scores']}")
    else:
        p.print_help()

if __name__ == "__main__":
    main()
