"""Turn an invoice/receipt (PDF or photo) into structured data with an AI model.

Two providers, same output schema:
- gemini: Google's free tier (default when no Claude key is set)
- claude: paid, most accurate
"""
from __future__ import annotations

import base64
import os
import time



from pydantic import BaseModel, Field

GEMINI_MODELS = [os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"), "gemini-3.1-flash-lite", "gemini-3.5-flash"]  # lite first: fast; full flash is often overloaded on the free tier
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

PROMPT = """Extract the data from this invoice or receipt.
Rules: copy names, numbers and dates exactly as printed; dates as YYYY-MM-DD; amounts as plain numbers
without currency symbols; currency as a 3-letter code (EGP, USD, EUR...). Use null for anything not shown.
If the document is not an invoice, receipt or bill, set is_invoice to false and leave the rest empty.
Do not calculate values that are not printed, except line totals when only quantity and unit price appear."""


class LineItem(BaseModel):
    description: str
    quantity: float | None = None
    unit_price: float | None = None
    total: float | None = None


class Invoice(BaseModel):
    is_invoice: bool = Field(True, description="false if the document is not an invoice, receipt or bill")
    vendor_name: str | None = Field(None, description="Seller / company issuing the invoice")
    vendor_tax_id: str | None = None
    customer_name: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = Field(None, description="YYYY-MM-DD")
    due_date: str | None = Field(None, description="YYYY-MM-DD")
    currency: str | None = None
    items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None


class ExtractionError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


def provider() -> str:
    return os.getenv("AI_PROVIDER") or ("claude" if os.getenv("ANTHROPIC_API_KEY") else "gemini")


def extract(data: bytes, mime: str) -> Invoice:
    return _claude(data, mime) if provider() == "claude" else _gemini(data, mime)


# ---------------------------------------------------------------- Gemini (free)
_gclient = None


def _gemini(data: bytes, mime: str) -> Invoice:
    from google import genai
    from google.genai import errors, types
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        raise ExtractionError(500, "Server is missing GEMINI_API_KEY (free from Google AI Studio).")
    global _gclient
    _gclient = _gclient or genai.Client(http_options=types.HttpOptions(
        timeout=45_000, retry_options=types.HttpRetryOptions(attempts=1)))
    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=Invoice)
    parts = [types.Part.from_bytes(data=data, mime_type=mime), PROMPT]
    busy = False
    for model in dict.fromkeys(GEMINI_MODELS):     # each free model has its own quota
        for attempt in range(2):                   # one quick retry when Google is momentarily overloaded
            try:
                resp = _gclient.models.generate_content(model=model, contents=parts, config=config)
            except errors.ClientError as exc:
                if exc.code in (404, 429):
                    break
                raise ExtractionError(502, f"Gemini rejected the file ({exc.code}).") from exc
            except (errors.ServerError, TimeoutError, OSError):
                busy = True
                time.sleep(1)
                continue
            if not resp.text:
                raise ExtractionError(422, "The AI could not read this document.")
            return _check(Invoice.model_validate_json(resp.text))
    if busy:
        raise ExtractionError(503, "Google's free AI is busy right now - please try again in a minute.")
    raise ExtractionError(429, "The free AI quota is used up for today - it resets tomorrow.")


def _check(inv: Invoice) -> Invoice:
    if not inv.is_invoice:
        raise ExtractionError(422, "This doesn't look like an invoice or receipt.")
    return inv


# ---------------------------------------------------------------- Claude (paid)
def _claude(data: bytes, mime: str) -> Invoice:
    import anthropic
    b64 = base64.standard_b64encode(data).decode()
    block = ({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
             if mime == "application/pdf" else
             {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
    try:
        resp = anthropic.Anthropic().messages.parse(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": [block, {"type": "text", "text": PROMPT}]}],
            output_format=Invoice,
        )
    except (anthropic.AuthenticationError, TypeError) as exc:
        raise ExtractionError(500, "Server is missing a valid ANTHROPIC_API_KEY.") from exc
    except anthropic.RateLimitError as exc:
        raise ExtractionError(429, "Too many requests - please try again in a moment.") from exc
    except anthropic.APIStatusError as exc:
        raise ExtractionError(502, f"AI service error ({exc.status_code}).") from exc
    except anthropic.APIConnectionError as exc:
        raise ExtractionError(503, "Could not reach the AI service.") from exc
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise ExtractionError(422, "The AI could not read this document.")
    return _check(resp.parsed_output)
