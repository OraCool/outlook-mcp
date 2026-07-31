"""PII redaction for email JSON (Presidio when available; optional dependency)."""

from __future__ import annotations

import copy
import hashlib
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Match ``tools._common._EMAIL_LIKE_RE`` (keep in sync for consistent client-visible scrubbing).
_EMAIL_LIKE_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)

# Default entity types Presidio recognizes (subset; must match analyzer recognizers for the language).
_DEFAULT_ENTITIES_CSV = (
    "EMAIL_ADDRESS,PERSON,PHONE_NUMBER,IBAN_CODE,CREDIT_CARD,IP_ADDRESS,LOCATION"
)

try:  # optional dependency: pip install outlook-multi-tenant-mcp[pii]
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig

    _IMPORT_OK = True
except ImportError:
    AnalyzerEngine = None  # type: ignore[misc, assignment]
    AnonymizerEngine = None  # type: ignore[misc, assignment]
    OperatorConfig = None  # type: ignore[misc, assignment]
    _IMPORT_OK = False

_ANALYZER_ENGINE: Any | None = None
_ANONYMIZER_ENGINE: Any | None = None


class PseudonymMap:
    """Document-scoped, bidirectional value <-> placeholder map.

    One instance is shared across every field of a document, so a value that appears in the
    subject, the body and an address blob collapses to a *single* placeholder — and two
    different values can never share one. That consistency is what makes the substitution
    reversible, and it is the property a per-call counter cannot provide.

    Placeholders are LLM-friendly (``[PERSON_1]``) rather than ciphertext: the anonymized text
    is fed to a model, and a model reproduces short bracketed labels far more reliably than
    the base64 blobs Presidio's own ``encrypt``/``decrypt`` round trip would put in the prompt.
    """

    def __init__(self) -> None:
        self._to_placeholder: dict[tuple[str, str], str] = {}
        self._to_value: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def placeholder_for(self, entity_type: str, value: str) -> str:
        """Return the stable placeholder for ``value``, minting one on first sight."""
        et = entity_type.upper()
        key = (et, value)
        existing = self._to_placeholder.get(key)
        if existing is not None:
            return existing
        self._counters[et] = self._counters.get(et, 0) + 1
        placeholder = f"[{et}_{self._counters[et]}]"
        self._to_placeholder[key] = placeholder
        self._to_value[placeholder] = value
        return placeholder

    @property
    def placeholders(self) -> set[str]:
        return set(self._to_value)

    def restore(self, text: str) -> str:
        """Substitute every known placeholder in ``text`` back to its original value."""
        if not text or not self._to_value:
            return text
        # Longest first: otherwise "[PERSON_1]" would match inside "[PERSON_10]".
        for placeholder in sorted(self._to_value, key=len, reverse=True):
            if placeholder in text:
                text = text.replace(placeholder, self._to_value[placeholder])
        return text

    def __len__(self) -> int:
        return len(self._to_value)
_PRESIDIO_UNAVAILABLE_LOGGED = False
_DETERMINISTIC_RESPONSE_FALLBACK_LOGGED = False


def is_presidio_available() -> bool:
    """True if presidio-analyzer is importable (does not verify spaCy model)."""
    return _IMPORT_OK


def _get_analyzer() -> Any | None:
    """Lazy AnalyzerEngine; returns None if init fails or presidio not installed."""
    global _ANALYZER_ENGINE, _PRESIDIO_UNAVAILABLE_LOGGED
    if not _IMPORT_OK:
        return None
    if _ANALYZER_ENGINE is None:
        try:
            _ANALYZER_ENGINE = AnalyzerEngine()
        except Exception as e:  # noqa: BLE001
            if not _PRESIDIO_UNAVAILABLE_LOGGED:
                logger.warning("Presidio AnalyzerEngine could not be initialized: %s", e)
                _PRESIDIO_UNAVAILABLE_LOGGED = True
            return None
    return _ANALYZER_ENGINE


def _get_anonymizer() -> Any | None:
    """Lazy AnonymizerEngine; returns None if init fails or presidio not installed."""
    global _ANONYMIZER_ENGINE
    if not _IMPORT_OK:
        return None
    if _ANONYMIZER_ENGINE is None:
        try:
            _ANONYMIZER_ENGINE = AnonymizerEngine()
        except Exception as e:  # noqa: BLE001
            logger.warning("Presidio AnonymizerEngine could not be initialized: %s", e)
            return None
    return _ANONYMIZER_ENGINE


def _entity_allowlist(entities_csv: str) -> set[str]:
    parts = {p.strip().upper() for p in entities_csv.replace(";", ",").split(",") if p.strip()}
    if not parts:
        return {p.strip().upper() for p in _DEFAULT_ENTITIES_CSV.split(",") if p.strip()}
    return parts


# spaCy `en` + Presidio on Cyrillic prose yields many false PERSON/LOCATION spans; keep pattern-friendly types.
_CYRILLIC_DERIVED_FALSE_POSITIVE_ENTITIES = frozenset({"PERSON", "LOCATION"})
_CYRILLIC_LETTER_RATIO_THRESHOLD = 0.20


def _cyrillic_letter_ratio(text: str) -> float:
    """Share of alphabetic characters that are Cyrillic (incl. yo)."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    cyrillic = 0
    for c in letters:
        o = ord(c)
        if 0x0400 <= o <= 0x04FF or c in "\u0451\u0401":  # Cyrillic blocks + ё/Ё
            cyrillic += 1
    return cyrillic / len(letters)


def _allowed_entities_for_script(text: str, allowed: set[str]) -> set[str]:
    """Drop NER types that mis-fire on non-Latin text when the default pipeline is English."""
    if _cyrillic_letter_ratio(text) < _CYRILLIC_LETTER_RATIO_THRESHOLD:
        return allowed
    return {e for e in allowed if e not in _CYRILLIC_DERIVED_FALSE_POSITIVE_ENTITIES}


def _operator_for(strategy: str, entity_type: str, mapping: PseudonymMap | None) -> Any:
    """Build the per-entity-type Presidio operator.

    The ``custom`` operator's lambda receives only the matched string, so the entity type is
    bound here per config entry rather than read inside the callback.
    """
    if strategy == "hash":
        return OperatorConfig("custom", {"lambda": lambda v: hashlib.sha256(v.encode("utf-8")).hexdigest()[:8]})
    if strategy == "remove":
        return OperatorConfig("replace", {"new_value": "[REDACTED]"})
    active = mapping if mapping is not None else PseudonymMap()
    return OperatorConfig("custom", {"lambda": lambda v, _et=entity_type: active.placeholder_for(_et, v)})


def redact_text(
    text: str,
    *,
    strategy: str,
    allowed_entities: set[str],
    language: str = "en",
    mapping: PseudonymMap | None = None,
) -> str:
    """Redact PII spans in ``text`` using Presidio (pseudonymize / hash / remove).

    Pass ``mapping`` to share one placeholder namespace across a whole document and make the
    substitution reversible via :func:`restore_text`. Without it, each call gets a private
    namespace, so placeholders are *not* comparable between calls.
    """
    if not text:
        return text
    strat = strategy.lower().strip()
    if strat not in ("pseudonymize", "hash", "remove"):
        strat = "pseudonymize"

    analyzer = _get_analyzer()
    anonymizer = _get_anonymizer()
    if analyzer is None or anonymizer is None:
        return text

    effective_entities = _allowed_entities_for_script(text, allowed_entities)
    if not effective_entities:
        return text

    entity_list = sorted(effective_entities)
    try:
        try:
            results = analyzer.analyze(text=text, language=language, entities=entity_list)
        except TypeError:
            results = analyzer.analyze(text=text, language=language)
            results = [r for r in results if str(r.entity_type).upper() in effective_entities]
    except Exception as e:  # noqa: BLE001
        logger.warning("Presidio analyze failed: %s", e)
        return text

    filtered = [r for r in results if str(r.entity_type).upper() in effective_entities]
    if not filtered:
        return text

    # AnonymizerEngine resolves overlapping/contained spans and rewrites right-to-left itself;
    # the previous hand-rolled loop did neither reliably.
    operators = {et: _operator_for(strat, et, mapping) for et in {str(r.entity_type).upper() for r in filtered}}
    try:
        return str(anonymizer.anonymize(text=text, analyzer_results=filtered, operators=operators).text)
    except Exception as e:  # noqa: BLE001
        logger.warning("Presidio anonymize failed: %s", e)
        return text


def restore_text(text: str, mapping: PseudonymMap) -> str:
    """Reverse :func:`redact_text` on ``text`` using the document's ``mapping``.

    Safe to run on model output: only placeholders this map minted are substituted, so text the
    model invented is left untouched.
    """
    return mapping.restore(text)


def _scrub_emails_in_str(s: str) -> str:
    return _EMAIL_LIKE_RE.sub("[EMAIL_REDACTED]", s)


def _redact_address_blob_deterministic(blob: dict[str, Any]) -> None:
    """Mask addresses and display names when Presidio is unavailable (tool response path only)."""
    addr = blob.get("address")
    if isinstance(addr, str) and addr:
        blob["address"] = _scrub_emails_in_str(addr)
    name = blob.get("name")
    if isinstance(name, str) and name.strip():
        blob["name"] = "[REDACTED]"


def _apply_deterministic_tool_response_redaction(out: dict[str, Any]) -> None:
    """In-place: email regex on text fields; redact routing display names without Presidio."""
    for key in ("subject", "body_preview", "body_content"):
        val = out.get(key)
        if isinstance(val, str) and val:
            out[key] = _scrub_emails_in_str(val)
    for addr_key in ("from", "sender"):
        b = out.get(addr_key)
        if isinstance(b, dict):
            _redact_address_blob_deterministic(b)
    to_list = out.get("to_recipients")
    if isinstance(to_list, list):
        for item in to_list:
            if isinstance(item, dict):
                _redact_address_blob_deterministic(item)


def _email_json_when_presidio_unavailable(
    email_json: dict[str, Any],
    *,
    deterministic_fallback: bool,
) -> dict[str, Any]:
    global _PRESIDIO_UNAVAILABLE_LOGGED, _DETERMINISTIC_RESPONSE_FALLBACK_LOGGED

    if not _PRESIDIO_UNAVAILABLE_LOGGED:
        logger.warning(
            "PII redaction is enabled but Presidio is not available or failed to init; "
            "install with: pip install 'outlook-multi-tenant-mcp[pii]' and spacy model en_core_web_lg"
        )
        _PRESIDIO_UNAVAILABLE_LOGGED = True
    if not deterministic_fallback:
        return email_json
    out = copy.deepcopy(email_json)
    _apply_deterministic_tool_response_redaction(out)
    if not _DETERMINISTIC_RESPONSE_FALLBACK_LOGGED:
        logger.error(
            "PII_RESPONSE_LEVEL=redacted but Presidio is unavailable; tool response email "
            "payload used deterministic email/display-name masking. Use Python 3.12+, "
            "pip install '.[pii]', and python -m spacy download en_core_web_lg for full Presidio redaction."
        )
        _DETERMINISTIC_RESPONSE_FALLBACK_LOGGED = True
    return out


def _redact_address_blob(
    blob: dict[str, Any],
    *,
    strategy: str,
    allowed_entities: set[str],
    language: str,
) -> None:
    addr = blob.get("address")
    if isinstance(addr, str) and addr:
        blob["address"] = redact_text(
            addr,
            strategy=strategy,
            allowed_entities=allowed_entities,
            language=language,
        )
    name = blob.get("name")
    if isinstance(name, str) and name:
        blob["name"] = redact_text(
            name,
            strategy=strategy,
            allowed_entities=allowed_entities,
            language=language,
        )


def redact_email_json(
    email_json: dict[str, Any],
    *,
    enabled: bool,
    strategy: str,
    entities_csv: str,
    language: str = "en",
    deterministic_fallback: bool = False,
) -> dict[str, Any]:
    """Deep-copy ``email_json`` and redact PII in text and address fields.

    If ``deterministic_fallback`` is True (``PII_RESPONSE_LEVEL=redacted`` tool payloads only) and
    Presidio cannot run, still apply regex email scrub and display-name redaction instead of
    returning plaintext.
    """
    if not enabled:
        return email_json
    if not _IMPORT_OK or _get_analyzer() is None:
        return _email_json_when_presidio_unavailable(
            email_json,
            deterministic_fallback=deterministic_fallback,
        )

    allowed = _entity_allowlist(entities_csv)
    out: dict[str, Any] = copy.deepcopy(email_json)
    strat = strategy.lower().strip()

    for key in ("subject", "body_preview", "body_content"):
        val = out.get(key)
        if isinstance(val, str) and val:
            out[key] = redact_text(
                val,
                strategy=strat,
                allowed_entities=allowed,
                language=language,
            )

    for addr_key in ("from", "sender"):
        b = out.get(addr_key)
        if isinstance(b, dict):
            _redact_address_blob(b, strategy=strat, allowed_entities=allowed, language=language)

    to_list = out.get("to_recipients")
    if isinstance(to_list, list):
        for item in to_list:
            if isinstance(item, dict):
                _redact_address_blob(item, strategy=strat, allowed_entities=allowed, language=language)

    return out


_TEXT_FIELDS = ("subject", "body_preview", "body_content")
_ADDRESS_FIELDS = ("from", "sender")


def anonymize_email_json(
    email_json: dict[str, Any],
    *,
    strategy: str,
    entities_csv: str,
    language: str = "en",
    mapping: PseudonymMap | None = None,
) -> tuple[dict[str, Any], PseudonymMap]:
    """Anonymize a whole email in one pass and return ``(redacted_copy, mapping)``.

    Every field shares one :class:`PseudonymMap`, so a person named in the subject and in the
    ``from`` blob collapses to a single placeholder. Feed ``mapping`` back in to extend the same
    namespace across several messages (a thread), then use :func:`restore_text` on model output.

    The input is never mutated. When Presidio is unavailable the copy is returned unchanged with
    an empty map — callers that need a guaranteed scrub must use ``deterministic_fallback``
    via :func:`redact_email_json`.
    """
    m = mapping if mapping is not None else PseudonymMap()
    out: dict[str, Any] = copy.deepcopy(email_json)
    if not _IMPORT_OK or _get_analyzer() is None:
        return out, m

    allowed = _entity_allowlist(entities_csv)
    strat = strategy.lower().strip()

    def scrub(value: str) -> str:
        return redact_text(value, strategy=strat, allowed_entities=allowed, language=language, mapping=m)

    for key in _TEXT_FIELDS:
        val = out.get(key)
        if isinstance(val, str) and val:
            out[key] = scrub(val)

    blobs: list[dict[str, Any]] = [b for k in _ADDRESS_FIELDS if isinstance(b := out.get(k), dict)]
    to_list = out.get("to_recipients")
    if isinstance(to_list, list):
        blobs += [item for item in to_list if isinstance(item, dict)]

    for blob in blobs:
        for field in ("address", "name"):
            val = blob.get(field)
            if isinstance(val, str) and val:
                blob[field] = scrub(val)

    return out, m


def redact_email_json_if_enabled(email_json: dict[str, Any]) -> dict[str, Any]:
    """Apply redaction using runtime :func:`~outlook_mcp.config.get_settings`."""
    from outlook_mcp.config import get_settings

    s = get_settings()
    return redact_email_json(
        email_json,
        enabled=bool(s.pii_redaction_enabled),
        strategy=s.pii_redaction_strategy,
        entities_csv=s.pii_entities,
    )


def anonymize_email_json_if_enabled(email_json: dict[str, Any]) -> tuple[dict[str, Any], PseudonymMap]:
    """``anonymize_email_json`` driven by runtime settings; returns the map for later restore.

    When redaction is disabled the email is passed through with an empty map, so
    :func:`restore_text` stays a safe no-op and callers need no branch of their own.
    """
    from outlook_mcp.config import get_settings

    s = get_settings()
    if not s.pii_redaction_enabled:
        return email_json, PseudonymMap()
    return anonymize_email_json(
        email_json,
        strategy=s.pii_redaction_strategy,
        entities_csv=s.pii_entities,
    )
