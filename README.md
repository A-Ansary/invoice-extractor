# Invoice & Receipt Extractor

Drop in PDFs or photos of invoices and receipts; an AI model reads each one and turns it into clean,
structured data: vendor, tax ID, customer, invoice number, dates, line items, subtotal, tax and total.
Review the results in the browser and download everything as one Excel file (an "Invoices" sheet plus a
"Line items" sheet). Saves accountants and small businesses hours of manual data entry.

## Features
- PDF, PNG, JPG and WEBP, several files at once (drag and drop).
- Schema-validated output (Pydantic), dates normalised to YYYY-MM-DD, amounts as numbers.
- Excel export with formatted headers.
- Runs on Google Gemini's free tier, or Claude for the highest accuracy - one setting.

## Run it
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
echo GEMINI_API_KEY=your-free-key > .env
uvicorn app.main:app --port 8001
```
Open http://localhost:8001 and drop `samples/invoice-1.pdf` in.

## Settings (.env)
| Variable | Default | Meaning |
|---|---|---|
| `AI_PROVIDER` | claude if its key is set, else gemini | `claude` or `gemini` |
| `GEMINI_API_KEY` | - | Free key from Google AI Studio |
| `ANTHROPIC_API_KEY` | - | Claude API key |
| `GEMINI_MODEL` | gemini-3.5-flash | Main Gemini model (free fallbacks are tried when its quota runs out) |
| `CLAUDE_MODEL` | claude-opus-5-5 | Claude model |
