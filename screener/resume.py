"""Load resume text from PDF, DOCX, Markdown or plain text."""
from __future__ import annotations

from pathlib import Path


def load_resume(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"Resume not found at {path}. Put your resume in ./private/ (gitignored) and set "
            "profile.resume_path in config.yaml, or pass --resume. To try the tool first, use "
            "--resume samples/sample_resume.md."
        )
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    elif suffix == ".docx":
        import docx
        text = "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    text = text.strip()
    if len(text) < 200:
        raise ValueError(f"Resume at {path} yielded only {len(text)} characters — is it a scanned PDF? "
                         "Try exporting it as text/Markdown.")
    return text
