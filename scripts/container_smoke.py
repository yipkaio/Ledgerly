"""Check a built runtime image with disposable volumes and no network or API credits.

Run: python scripts/container_smoke.py --image expense-agent:local
Only containers/volumes with this run's random prefix are removed.
"""

import argparse
import secrets
import subprocess
import sys
import time
from uuid import uuid4


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], check=check, text=True, capture_output=True, timeout=60
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="expense-agent:local")
    args = parser.parse_args()
    docker("version")
    prefix = "expense-smoke-" + uuid4().hex[:12]
    data, cache = prefix + "-data", prefix + "-cache"
    receipt_id = str(uuid4())
    key = secrets.token_hex(32)
    volumes = []
    try:
        for volume in (data, cache):
            docker("volume", "create", volume)
            volumes.append(volume)

        def launch():
            docker(
                "run", "-d", "--name", prefix, "--network", "none", "--read-only",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--init",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=512m,mode=1777",
                "--mount", f"type=volume,src={data},dst=/app/data",
                "--mount", f"type=volume,src={cache},dst=/home/expense",
                "-e", "APP_API_KEY=" + key, "-e", "LLM_GATEWAY_API_KEY=test-only-no-network",
                "-e", "OCR_ENGINE=tesseract", "-e", "API_DOCS_ENABLED=false", args.image,
            )
            for _ in range(30):
                result = docker("exec", prefix, "python", "-c",
                                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)", check=False)
                if result.returncode == 0:
                    return
                time.sleep(1)
            raise RuntimeError("Container did not become healthy")

        launch()
        checks = """
import os
import urllib.request
import urllib.error
assert os.getuid() == 10001
for path, expected in [('/receipts', 401), ('/docs', 404)]:
    try:
        urllib.request.urlopen('http://127.0.0.1:8000' + path, timeout=3)
    except urllib.error.HTTPError as exc:
        assert exc.code == expected
    else:
        raise AssertionError(path)
"""
        docker("exec", prefix, "python", "-c", checks)
        # Seed a synthetic failure through the storage layer; no paid upload.
        seed = """
import os, sys
from pathlib import Path
from app.database import ReceiptStore
store = ReceiptStore(Path(os.environ['DATABASE_PATH']))
store.start(sys.argv[1], 'image/jpeg', 4, '/app/data/uploads/synthetic.jpg', None)
store.fail(sys.argv[1], 'Smoke test fixture')
Path('/app/data/uploads/synthetic.jpg').write_bytes(b'test')
(Path.home() / '.cache' / 'smoke-marker').write_text('cached')
"""
        docker("exec", prefix, "python", "-c", seed, receipt_id)
        docker("stop", "--time", "15", prefix)
        docker("rm", prefix)
        launch()
        verify = """
import os, sys, json, urllib.request
from pathlib import Path
request = urllib.request.Request('http://127.0.0.1:8000/receipts/' + sys.argv[1],
                                 headers={'X-API-Key': os.environ['APP_API_KEY']})
with urllib.request.urlopen(request, timeout=5) as response:
    result = json.load(response)
assert result['processing_status'] == 'FAILED'
assert Path('/app/data/uploads/synthetic.jpg').read_bytes() == b'test'
assert (Path.home() / '.cache' / 'smoke-marker').read_text() == 'cached'
"""
        docker("exec", prefix, "python", "-c", verify, receipt_id)
        print("PASS: startup, authentication, docs disabled, non-root user, and data/cache persistence after recreation.")
        return 0
    finally:
        docker("rm", "--force", prefix, check=False)
        for volume in volumes:
            docker("volume", "rm", volume, check=False)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        # Do not print subprocess arguments: they include an ephemeral test key.
        print(f"Docker smoke test failed ({type(exc).__name__}). Check Docker and the built image.", file=sys.stderr)
        raise SystemExit(1)
