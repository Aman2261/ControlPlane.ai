"""
Detector 1 — PII / Privacy
===========================
Scans response text for structured PII (email, phone, SSN, credit card)
via regex, plus a lightweight heuristic for full names appearing next to
identifying context words (DOB, patient, applicant, etc.).

This runs purely on the text ControlPlane sees at the input/output layer —
no access to the model's internals, consistent with the "consumed via API"
constraint in the brief.
"""
import re
from dataclasses import dataclass, asdict
from typing import List


@dataclass
class Finding:
    detector: str
    risk_type: str          # e.g. "privacy"
    subtype: str            # e.g. "email", "phone", "name"
    span: str
    confidence: float       # 0-1, how sure the detector is
    detail: str

    def to_dict(self):
        return asdict(self)


EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CC_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
DOB_CONTEXT_RE = re.compile(r"\bDOB\b[^)]{0,20}\d{1,2}/\d{1,2}/\d{2,4}", re.IGNORECASE)

# Very small heuristic: "First Last" following an identifying context word.
NAME_CONTEXT_RE = re.compile(
    r"\b(?:Patient|Applicant|Customer|Employee|Mr\.|Ms\.|Mrs\.)\s+"
    r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)"
)


def detect(response_text: str) -> List[Finding]:
    findings: List[Finding] = []

    for m in EMAIL_RE.finditer(response_text):
        findings.append(Finding(
            detector="pii", risk_type="privacy", subtype="email",
            span=m.group(), confidence=0.97,
            detail="Structured email address disclosed in response.",
        ))

    for m in PHONE_RE.finditer(response_text):
        findings.append(Finding(
            detector="pii", risk_type="privacy", subtype="phone",
            span=m.group(), confidence=0.95,
            detail="Structured phone number disclosed in response.",
        ))

    for m in SSN_RE.finditer(response_text):
        findings.append(Finding(
            detector="pii", risk_type="privacy", subtype="ssn",
            span=m.group(), confidence=0.99,
            detail="Social Security Number pattern disclosed in response.",
        ))

    for m in CC_RE.finditer(response_text):
        digits = re.sub(r"[^0-9]", "", m.group())
        if len(digits) in (13, 14, 15, 16):
            findings.append(Finding(
                detector="pii", risk_type="privacy", subtype="credit_card",
                span=m.group(), confidence=0.9,
                detail="Possible payment card number disclosed in response.",
            ))

    for m in DOB_CONTEXT_RE.finditer(response_text):
        findings.append(Finding(
            detector="pii", risk_type="privacy", subtype="dob",
            span=m.group(), confidence=0.9,
            detail="Date of birth disclosed alongside identifying context.",
        ))

    for m in NAME_CONTEXT_RE.finditer(response_text):
        findings.append(Finding(
            detector="pii", risk_type="privacy", subtype="name",
            span=m.group(), confidence=0.65,
            detail="Full name disclosed alongside identifying context "
                   "(patient/applicant/customer/employee).",
        ))

    return findings
