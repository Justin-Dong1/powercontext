"""Fetch the exact public PowerContext dependency into an isolated cache."""

from pathlib import Path
import hashlib, json, urllib.request, zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent if HERE.parent.name == "ecosystem" else HERE.parent
COMMIT = "fda256c329c6ea9f6e6bb037354922f0f577ac5e"
target = ROOT / ".cache/minimax-deps"
target.mkdir(parents=True, exist_ok=True)
url = "https://codeload.github.com/Justin-Dong1/powercontext/zip/" + COMMIT
with urllib.request.urlopen(url, timeout=90) as response:
    raw = response.read(40 * 1024 * 1024 + 1)
if len(raw) > 40 * 1024 * 1024:
    raise ValueError("Archive exceeds size limit")
archive = target / "powercontext.zip"
archive.write_bytes(raw)
with zipfile.ZipFile(archive) as z:
    if sum(x.file_size for x in z.infolist()) > 200 * 1024 * 1024:
        raise ValueError("Expanded archive too large")
    for x in z.infolist():
        if not (target / x.filename).resolve().is_relative_to(target.resolve()):
            raise ValueError("Archive path escape")
    z.extractall(target)
receipt = dict(
    url=url, commit=COMMIT, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)
)
(target / "source-receipt.json").write_text(
    json.dumps(receipt, indent=2), encoding="utf8"
)
print(json.dumps(receipt))
