"""Read only generated image names, never a client or database supplied path."""
import os
import stat
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import Response


def receipt_image(store, upload_dir: Path, receipt_id: str, max_bytes: int) -> Response:
    receipt = store.get(receipt_id)
    if receipt is None:
        raise HTTPException(404, 'Receipt not found')
    content_type = receipt['content_type']
    extension = {'image/jpeg': '.jpg', 'image/png': '.png'}.get(content_type)
    if extension is None:
        raise HTTPException(404, 'Receipt image is unavailable')
    path = upload_dir / (receipt_id + extension)
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise OSError('Not a regular file')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise OSError('Not a regular file')
            data = source.read(max_bytes + 1)
        signature = b'\xff\xd8\xff' if extension == '.jpg' else b'\x89PNG\r\n\x1a\n'
        if len(data) > max_bytes or not data.startswith(signature):
            raise OSError('Invalid image')
    except OSError:
        raise HTTPException(404, 'Receipt image is unavailable') from None
    return Response(data, media_type=content_type, headers={
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Disposition': f'inline; filename="{receipt_id}{extension}"',
        'Content-Security-Policy': "default-src 'none'; sandbox",
    })
