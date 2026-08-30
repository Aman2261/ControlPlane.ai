"""
Detector 2 — Grounding / Hallucination
========================================
Answers the brief's hardest complexity head-on: "there is often no
reliable, real-time ground truth to check a claim against."

Two modes, chosen automatically based on what's available:

1. RETRIEVAL VERIFICATION (source documents provided): split the response
   into claims, use TF-IDF cosine similarity to find the best-matching
   source sentence for each claim, then specifically compare any numbers
   in the claim against numbers in that matched sentence. A confident
   numeric contradiction (e.g. "25 days" vs a source that says "15 days")
   is scored as high-confidence hallucination even if the surrounding
   language is otherwise similar — this is deliberately stricter than
   similarity alone, since fluent paraphrasing is exactly what makes
   hallucinations hard to catch.

2. SELF-CONSISTENCY (no source documents available): compare the response
   against an independently-generated second sample of "the same answer."
   Low similarity between the two samples is treated as a proxy for low
   confidence — not proof of a hallucination, just a signal the claim
   can't currently be verified, which is scored and surfaced as such
   rather than silently assumed correct.

This is intentionally a lightweight, dependency-free approximation of the
production pattern (embedding-based entailment / NLI models, live
retrieval against a knowledge base) — the brief explicitly invites
reasonable assumptions at prototype scale.
"""
import re
from dataclasses import dataclass, asdict
from typing import List, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class Finding:
    detector: str
    risk_type: str
    subtype: str
    span: str
    confidence: float
    detail: str

    def to_dict(self):
        return asdict(self)


NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _split_claims(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if len(p.strip()) > 0]


def _is_checkable_claim(text: str) -> bool:
    """Filters out short interjections/acknowledgements ("Sure!", "Thanks.")
    that carry no verifiable factual content and would otherwise register
    as false 'unsupported claims' just for lacking a source match."""
    words = re.findall(r"[a-zA-Z]+", text)
    return len(words) >= 4


def _best_match(claim: str, candidates: List[str]):
    if not candidates:
        return None, 0.0
    corpus = candidates + [claim]
    vec = TfidfVectorizer().fit_transform(corpus)
    sims = cosine_similarity(vec[-1], vec[:-1]).flatten()
    best_idx = sims.argmax()
    return candidates[best_idx], float(sims[best_idx])


def _numbers(text: str) -> List[str]:
    return NUM_RE.findall(text)


def detect(response_text: str, source_documents: Optional[List[str]] = None,
           consistency_sample: Optional[str] = None) -> List[Finding]:
    findings: List[Finding] = []
    claims = _split_claims(response_text)

    if source_documents:
        # Split sources into sentences too, so matching is granular.
        source_sentences = []
        for doc in source_documents:
            source_sentences.extend(_split_claims(doc))

        for claim in claims:
            if not _is_checkable_claim(claim):
                continue
            match, score = _best_match(claim, source_sentences)
            if match is None:
                continue

            claim_nums = _numbers(claim)
            match_nums = _numbers(match)
            numeric_contradiction = (
                claim_nums and match_nums and
                set(claim_nums) - set(match_nums) and
                score > 0.15  # only counts if the sentence is clearly "about" the same thing
            )

            if numeric_contradiction:
                findings.append(Finding(
                    detector="grounding", risk_type="hallucination",
                    subtype="numeric_contradiction",
                    span=claim.strip(),
                    confidence=0.9,
                    detail=(
                        f"Claim states {claim_nums} but the matched source "
                        f"sentence states {match_nums}: \"{match.strip()}\""
                    ),
                ))
            elif score < 0.12:
                # Claim doesn't resemble anything in the provided sources at all.
                findings.append(Finding(
                    detector="grounding", risk_type="hallucination",
                    subtype="unsupported_claim",
                    span=claim.strip(),
                    confidence=round(min(0.85, 1 - score), 2),
                    detail="No supporting sentence found in the provided "
                           "source documents for this claim.",
                ))
    else:
        # No ground truth available -> self-consistency fallback.
        if consistency_sample:
            match, score = _best_match(response_text, [consistency_sample])
            if score < 0.35:
                findings.append(Finding(
                    detector="grounding", risk_type="hallucination",
                    subtype="low_self_consistency",
                    span=response_text.strip(),
                    confidence=round(min(0.75, 1 - score), 2),
                    detail=(
                        "No source document available to verify this claim. "
                        "An independently generated sample of the same "
                        f"answer disagrees (similarity={score:.2f}) — "
                        "surfaced as low-confidence rather than assumed correct."
                    ),
                ))

    return findings
