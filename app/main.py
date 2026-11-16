"""Invoice & receipt extractor - FastAPI backend.

Drop in PDFs or photos of invoices; each one becomes a row of structured data (vendor, number, dates,
line items, totals). Download everything as one Excel file.

Run:  uvicorn app.main:app --reload     then open http://localhost:8001
"""
from __future__ import annotations

import io
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from .extract import ExtractionError, Invoice, extract, provider  # noqa: E402  (after .env is loaded)

MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp"}
app = FastAPI(title="Invoice Extractor")


@app.get("/")
def home() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/info")
def info() -> dict:
    return {"provider": provider()}


@app.post("/api/extract")
async def extract_one(file: UploadFile) -> dict:
    name = Path(file.filename or "file").name
    mime = MIME.get(Path(name).suffix.lower())
    if not mime:
        raise HTTPException(400, "Supported files: PDF, PNG, JPG, WEBP.")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "File is larger than 20 MB.")
    try:
        inv = extract(data, mime)
    except ExtractionError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return {"file": name, "invoice": inv.model_dump()}


@app.post("/api/excel")
def to_excel(rows: list[dict]) -> StreamingResponse:
    """rows = [{"file": ..., "invoice": {...}}, ...] as returned by /api/extract."""
    wb = Workbook()
    head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="B3121F")

    def sheet(ws, header):
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill

    ws = wb.active
    ws.title = "Invoices"
    sheet(ws, ["File", "Vendor", "Vendor tax ID", "Customer", "Invoice #", "Date", "Due", "Currency",
               "Subtotal", "Tax", "Total"])
    items = wb.create_sheet("Line items")
    sheet(items, ["File", "Invoice #", "Description", "Qty", "Unit price", "Line total"])
    for r in rows:
        inv = Invoice.model_validate(r.get("invoice") or {})
        ws.append([r.get("file"), inv.vendor_name, inv.vendor_tax_id, inv.customer_name, inv.invoice_number,
                   inv.invoice_date, inv.due_date, inv.currency, inv.subtotal, inv.tax, inv.total])
        for it in inv.items:
            items.append([r.get("file"), inv.invoice_number, it.description, it.quantity, it.unit_price, it.total])
    for s in (ws, items):
        for col in s.columns:
            s.column_dimensions[col[0].column_letter].width = min(45, max(10, *(len(str(c.value or "")) + 2 for c in col)))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="invoices.xlsx"'})
