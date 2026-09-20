"""Document Intelligence agent facade over the existing extraction services."""

from __future__ import annotations

from dataclasses import dataclass

from app.extraction import ReceiptExtraction, ReceiptExtractor
from app.statement_extraction import StatementExtraction, StatementExtractor


@dataclass(frozen=True)
class DocumentIntelligenceAgent:
    """One logical boundary for receipt and bank-statement understanding.

    OCR/PDF parsing remains local and bounded. Only normalized text is supplied to
    the configured extractors, and statement AI remains an explicit opt-in path.
    """

    receipt_extractor: ReceiptExtractor
    statement_extractor: StatementExtractor

    async def extract_receipt(self, ocr_text: str) -> ReceiptExtraction:
        return await self.receipt_extractor.extract(ocr_text)

    async def extract_statement(self, statement_text: str) -> StatementExtraction:
        return await self.statement_extractor.extract(statement_text)
