import hashlib
import json
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def build_page() -> tuple[str, str]:
    """Return (html, version) with the Clawd art inlined."""
    html = (WEB / "page.html").read_text(encoding="utf-8")
    data = (WEB / "clawd.json").read_text(encoding="utf-8")
    version = hashlib.sha1((html + data).encode()).hexdigest()[:10]
    html = html.replace("/*CLAWD_DATA*/null", data).replace("/*PAGE_VERSION*/", version)
    return html, version


def inject_js() -> str:
    """JS that replaces the current document with the page buffered in window.__cmBuf."""
    return "(function(){var h=window.__cmBuf.join('');document.open();document.write(h);document.close();return 'injected';})()"


if __name__ == "__main__":
    out = WEB.parent / "build" / "preview.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(build_page()[0], encoding="utf-8")
    print(out)
