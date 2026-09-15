"""Read only generated receipt names, never a client or database supplied path."""
import os
import stat
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import Response


def _read_regular(path: Path, max_bytes: int, signature: bytes, unavailable: str) -> bytes:
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise OSError('Not a regular file')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise OSError('Not a regular file')
            data = source.read(max_bytes + 1)
        if len(data) > max_bytes or not data.startswith(signature):
            raise OSError('Invalid receipt file')
        return data
    except OSError:
        raise HTTPException(404, unavailable) from None


def receipt_image(store, upload_dir: Path, receipt_id: str, max_bytes: int) -> Response:
    receipt = store.get(receipt_id)
    if receipt is None:
        raise HTTPException(404, 'Receipt not found')
    content_type = receipt['content_type']
    kind = {
        'image/jpeg': ('.jpg', b'\xff\xd8\xff'),
        'image/png': ('.png', b'\x89PNG\r\n\x1a\n'),
        'application/pdf': ('.pdf', b'%PDF-'),
    }.get(content_type)
    extension = kind[0] if kind else None
    if extension is None:
        raise HTTPException(404, 'Receipt file is unavailable')
    path = upload_dir / (receipt_id + extension)
    data = _read_regular(path, max_bytes, kind[1], 'Receipt file is unavailable')
    return Response(data, media_type=content_type, headers={
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Disposition': f'inline; filename="{receipt_id}{extension}"',
        'Content-Security-Policy': "default-src 'none'; sandbox",
    })


def receipt_preview(store, upload_dir: Path, receipt_id: str, max_bytes: int) -> Response:
    receipt = store.get(receipt_id)
    if receipt is None:
        raise HTTPException(404, 'Receipt not found')
    if receipt['content_type'] in ('image/jpeg', 'image/png'):
        return receipt_image(store, upload_dir, receipt_id, max_bytes)
    if receipt['content_type'] != 'application/pdf':
        raise HTTPException(404, 'Receipt preview is unavailable')
    extension = '.preview.png'
    # A generated preview is bounded by render pixels; allow at most 20 MB on read.
    data = _read_regular(
        upload_dir / (receipt_id + extension),
        min(20 * 1024 * 1024, max_bytes * 4),
        b'\x89PNG\r\n\x1a\n',
        'Receipt preview is unavailable',
    )
    return Response(data, media_type='image/png', headers={
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Disposition': f'inline; filename="{receipt_id}{extension}"',
        'Content-Security-Policy': "default-src 'none'; sandbox",
    })
