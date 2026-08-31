"""
Cost Control
=============
Implements the "Intelligent Cost Control" pillar from the original pitch,
which the earlier prototype never actually wired up: a semantic cache for
repeat/near-duplicate queries, and a complexity router that prices simple
vs. complex queries differently — the same way a real system would send
simple queries to a cheap model and reserve expensive reasoning for
queries that need it.

Both run as real logic against real request text (Jaccard similarity over
tokenized prompts), not a hard-coded lookup — ask the same question two
different ways and it will still register as a cache hit if the wording
overlaps enough; ask something close-but-different and it won't.
"""
import re
import time
from typing import Optional, Dict, List, Any

SIMPLE_RATE_PER_TOKEN = 0.00006     # simulated small-model rate
COMPLEX_RATE_PER_TOKEN = 0.00022    # simulated large-model rate
CACHE_SIMILARITY_THRESHOLD = 0.55    # min Jaccard similarity to count as a cache hit

# Prompts matching these patterns, or over the length threshold, are
# routed to the "complex" (larger, pricier) tier.
COMPLEX_SIGNAL_RE = re.compile(
    r"\b(why|compare|analy[sz]e|evaluate|policy|recommend|safe|risk|summari[sz]e)\b",
    re.IGNORECASE,
)
COMPLEX_WORD_COUNT = 12


def _tokenize(text: str):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: str, b: str) -> float:
    A, B = _tokenize(a), _tokenize(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def classify_complexity(prompt: str) -> str:
    if len(prompt.split()) > COMPLEX_WORD_COUNT or COMPLEX_SIGNAL_RE.search(prompt):
        return "complex"
    return "simple"


def estimate_cost(prompt: str, response: str, complexity: str) -> float:
    # Rough token estimate (~1.3 tokens per word) — good enough to make
    # the relative cost difference between tiers and cache hits/misses
    # meaningful, without needing a real tokenizer.
    tokens = len((prompt + " " + response).split()) * 1.3
    rate = COMPLEX_RATE_PER_TOKEN if complexity == "complex" else SIMPLE_RATE_PER_TOKEN
    return round(tokens * rate, 5)


# In-memory per-use-case semantic cache. Reset when the process restarts —
# intentionally simple for prototype scope; a production version would
# back this with a persistent vector store.
_CACHE: Dict[str, List[Dict[str, Any]]] = {}


def check_cache(use_case: str, prompt: str) -> Optional[Dict[str, Any]]:
    best_entry, best_sim = None, 0.0
    for entry in _CACHE.get(use_case, []):
        sim = _jaccard(entry["prompt"], prompt)
        if sim > best_sim:
            best_sim, best_entry = sim, entry
    if best_entry and best_sim >= CACHE_SIMILARITY_THRESHOLD:
        return {
            "similarity": round(best_sim, 2),
            "matched_prompt": best_entry["prompt"],
            "cached_decision": best_entry["decision"],
            "original_cost": best_entry["cost"],
        }
    return None


def store_cache(use_case: str, prompt: str, decision: dict, cost: float):
    _CACHE.setdefault(use_case, []).append({
        "prompt": prompt, "decision": decision, "cost": cost, "ts": time.time(),
    })


def cache_size(use_case: str) -> int:
    return len(_CACHE.get(use_case, []))


def reset_cache():
    _CACHE.clear()
