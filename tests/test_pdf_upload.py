from io import BytesIO
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.pdf import PDFEncryptedError, PDFTimeoutError, extract_pdf_text
from test_api import TEST_KEY, configured_client


HEADERS = {"X-API-Key": TEST_KEY}


def make_pdf(text: str | None = None, pages: int = 1, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=240, height=320)
        if text:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            font_ref = writer._add_object(font)
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
            )
            stream = DecodedStreamObject()
            safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream.set_data(f"BT /F1 12 Tf 20 280 Td ({safe}) Tj ET".encode("latin-1"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("secret")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def upload(client, content: bytes):
    return client.post(
        "/receipts/upload",
        headers=HEADERS,
        files={"receipt": ("receipt.pdf", content, "application/pdf")},
    )


def test_native_text_pdf_uses_no_ocr_and_retains_protected_original(monkeypatch, tmp_path):
    client, ocr, extractor, _ = configured_client(monkeypatch, tmp_path, max_bytes=20_000)
    content = make_pdf("TEO HENG STATIONERY RECEIPT TOTAL MYR 4.90")
    response = upload(client, content)
    assert response.status_code == 202, response.text
    result = response.json()
    assert result["content_type"] == "application/pdf"
    assert result["ocr_engine"] == "pdf:native"
    assert result["ocr_confidence"] is None
    assert "TEO HENG" in result["ocr_text"]
    assert ocr.paths == []
    assert "TEO HENG" in extractor.inputs[0]

    original = client.get(f"/receipts/{result['receipt_id']}/image", headers=HEADERS)
    assert original.status_code == 200
    assert original.headers["content-type"] == "application/pdf"
    assert original.content == content
    preview = client.get(f"/receipts/{result['receipt_id']}/preview", headers=HEADERS)
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_scanned_pdf_renders_then_uses_selected_ocr(monkeypatch, tmp_path):
    client, ocr, extractor, _ = configured_client(monkeypatch, tmp_path, max_bytes=20_000)
    response = upload(client, make_pdf())
    assert response.status_code == 202, response.text
    result = response.json()
    assert result["ocr_engine"] == "pdf:stub"
    assert result["ocr_confidence"] == 0.95
    assert len(ocr.paths) == 1
    assert ocr.paths[0].suffix == ".png"
    assert not ocr.paths[0].exists()
    assert extractor.inputs == ["--- Page 1 ---\nMR DIY\nTOTAL RM 33.90"]


def test_encrypted_and_excess_page_pdfs_fail_before_ocr_or_gateway(monkeypatch, tmp_path):
    client, ocr, extractor, classifier = configured_client(monkeypatch, tmp_path, max_bytes=30_000)
    encrypted = upload(client, make_pdf("SECRET RECEIPT TOTAL MYR 1.00", encrypted=True))
    assert encrypted.status_code == 422
    assert encrypted.json() == {"detail": "Encrypted PDFs are not supported"}
    too_many = upload(client, make_pdf(pages=4))
    assert too_many.status_code == 422
    assert too_many.json() == {"detail": "PDF must contain 1 to 3 pages"}
    assert ocr.paths == extractor.inputs == classifier.inputs == []
    assert not list(tmp_path.glob("*.pdf"))
    assert not list(tmp_path.glob("*.preview.png"))


def test_statement_pdf_password_is_request_only_and_unlocks_parser(tmp_path):
    source = tmp_path / "encrypted.pdf"
    source.write_bytes(make_pdf("PRIVATE BANK STATEMENT", encrypted=True))
    from test_api import StubOCRService

    ocr = StubOCRService()
    try:
        extract_pdf_text(source, ocr, max_pages=3, max_render_pixels=30_000_000,
                         timeout_seconds=30, password="wrong")
    except PDFEncryptedError:
        pass
    else:
        raise AssertionError("Incorrect PDF password was accepted")

    result = extract_pdf_text(source, ocr, max_pages=3, max_render_pixels=30_000_000,
                              timeout_seconds=30, password="secret")
    assert "PRIVATE BANK STATEMENT" in result.text
    assert result.engine == "pdf:native"
    assert ocr.paths == []


def test_pdf_signature_and_exact_duplicate(monkeypatch, tmp_path):
    client, ocr, extractor, _ = configured_client(monkeypatch, tmp_path, max_bytes=20_000)
    fake = upload(client, b"not a pdf")
    assert fake.status_code == 415
    content = make_pdf("VALID RECEIPT NUMBER 123 TOTAL MYR 3.00")
    first = upload(client, content)
    assert first.status_code == 202
    calls = (len(ocr.paths), len(extractor.inputs))
    duplicate = upload(client, content)
    assert duplicate.status_code == 409
    assert duplicate.json()["existing_receipt_id"] == first.json()["receipt_id"]
    assert (len(ocr.paths), len(extractor.inputs)) == calls


def test_malformed_and_timed_out_pdf_fail_safely(monkeypatch, tmp_path):
    client, ocr, extractor, classifier = configured_client(monkeypatch, tmp_path, max_bytes=20_000)
    malformed = upload(client, b"%PDF-not-a-document")
    assert malformed.status_code == 422
    assert malformed.json() == {"detail": "Receipt PDF could not be processed"}

    def timeout(*args, **kwargs):
        raise PDFTimeoutError("private parser details")

    monkeypatch.setattr("app.main.extract_pdf", timeout)
    timed_out = upload(client, make_pdf())
    assert timed_out.status_code == 504
    assert timed_out.json() == {"detail": "Receipt PDF timed out"}
    assert "private" not in timed_out.text
    assert ocr.paths == extractor.inputs == classifier.inputs == []
    assert not list(tmp_path.glob("*.pdf"))
