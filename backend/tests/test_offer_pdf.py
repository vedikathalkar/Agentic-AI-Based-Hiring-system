"""The offer-letter PDF layout engine (no web stack needed)."""

import io

import pdfplumber

from app.services.pdf_service import letter_pdf


def test_letter_pdf_renders_formatting_and_paginates():
    body = "Date: 01 October 2026\n\n# Offer of Employment\nDear **Asha**,\n\n- CTC: ₹18,00,000\n---\n" + "Long paragraph. " * 600
    pdf = letter_pdf("Nimbus Analytics", "nimbus.example  |  Pune", body, footer="Offer #5")
    assert pdf.startswith(b"%PDF")
    doc = pdfplumber.open(io.BytesIO(pdf))
    first = doc.pages[0].extract_text()
    assert "Nimbus Analytics" in first and "Offer of Employment" in first and "Dear Asha," in first
    assert "Rs.18,00,000" in first.replace(" ", "") and "**" not in first
    assert len(doc.pages) > 1 and "Page 2 of" in doc.pages[1].extract_text()
