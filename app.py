from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import streamlit as st
import streamlit.components.v1 as components
from code_editor import code_editor

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
DEFAULT_MARKDOWN_FILE = "resume.md"
OUTPUT_DIRECTORY = "generated"

# PDF margin flags matching the user's pandoc command:
#   pandoc resume.md -o CV.pdf --pdf-engine=wkhtmltopdf
#     --pdf-engine-opt=-T --pdf-engine-opt=8mm
#     --pdf-engine-opt=-B --pdf-engine-opt=8mm
#     --pdf-engine-opt=-L --pdf-engine-opt=8mm
#     --pdf-engine-opt=-R --pdf-engine-opt=8mm
PANDOC_MARGIN_OPTS = [
    "--pdf-engine-opt=-T", "--pdf-engine-opt=8mm",
    "--pdf-engine-opt=-B", "--pdf-engine-opt=8mm",
    "--pdf-engine-opt=-L", "--pdf-engine-opt=8mm",
    "--pdf-engine-opt=-R", "--pdf-engine-opt=8mm",
]


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def check_tool(name: str) -> bool:
    return shutil.which(name) is not None


def load_markdown(path: Path) -> Tuple[str, str]:
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8"), f"✓ Loaded {path.name}"
    return "", f"⚠ {path.name} not found — starting with an empty document."


def validate_filename(raw: str) -> Tuple[Optional[str], Optional[str]]:
    name = raw.strip()
    if not name:
        return None, "Save As Name cannot be empty."
    if any(c in name for c in ("/", "\\")) or ".." in name:
        return None, "Invalid filename: path separators and '..' are not allowed."
    stem = name[:-3] if name.lower().endswith(".md") else name
    if not stem:
        return None, "Invalid filename."
    if not re.fullmatch(r"[A-Za-z0-9._-]+", stem):
        return None, "Filename may contain only letters, numbers, '.', '_', or '-'."
    return f"{stem}.md", None


def pandoc_to_html(content: str) -> Tuple[Optional[str], Optional[str]]:
    """Render markdown to standalone HTML via pandoc (matches PDF rendering)."""
    tmp_md = tmp_html = None
    try:
        fd, tmp_md = tempfile.mkstemp(suffix=".md")
        os.close(fd)
        Path(tmp_md).write_text(content, encoding="utf-8")
        tmp_html = tmp_md[:-3] + ".html"

        result = subprocess.run(
            ["pandoc", tmp_md, "-t", "html5", "--standalone", "-o", tmp_html],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            details = (result.stderr or "").strip() or "(no details)"
            return None, f"Pandoc preview error (code {result.returncode}):\n{details}"
        return Path(tmp_html).read_text(encoding="utf-8"), None
    except FileNotFoundError:
        return None, "✗ Pandoc not found. Install Pandoc and ensure it is in PATH."
    finally:
        for p in [tmp_md, tmp_html]:
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def generate_pdf(md_path: Path, pdf_path: Path) -> Tuple[bool, str]:
    cmd = [
        "pandoc", str(md_path),
        "-o", str(pdf_path),
        "--pdf-engine=wkhtmltopdf",
    ] + PANDOC_MARGIN_OPTS

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, f"✓ PDF generated: {pdf_path.name}"
    except FileNotFoundError:
        return False, "✗ Pandoc not found. Install Pandoc and ensure it is in PATH."
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip() or "(no stderr output)"
        if "wkhtmltopdf" in stderr.lower():
            return False, f"✗ wkhtmltopdf unavailable.\n{stderr}"
        return False, f"✗ PDF generation failed (code {exc.returncode}).\n{stderr}"


# ─────────────────────────────────────────────
# Session state initialisation
# ─────────────────────────────────────────────

def init_state() -> None:
    if "initialized" in st.session_state:
        return
    content, msg = load_markdown(Path(DEFAULT_MARKDOWN_FILE))
    st.session_state.initialized = True
    st.session_state.editor_content = content
    st.session_state.logs = [msg]
    st.session_state.save_as_name = Path(DEFAULT_MARKDOWN_FILE).stem
    st.session_state.last_pdf_path = None
    st.session_state.preview_html = None
    st.session_state.preview_error = None


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Resume Editor",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    Path(OUTPUT_DIRECTORY).mkdir(parents=True, exist_ok=True)
    init_state()

    pandoc_ok = check_tool("pandoc")
    wkhtml_ok = check_tool("wkhtmltopdf")

    st.markdown("""
    <style>
        .block-container { padding-top: 1rem; padding-bottom: 0.5rem; }
    </style>
    """, unsafe_allow_html=True)

    # ── Sidebar ────────────────────────────────────────────────
    with st.sidebar:
        st.header("System Requirements")
        st.write("✓ Pandoc available" if pandoc_ok else "✗ Pandoc not found")
        st.write("✓ wkhtmltopdf available" if wkhtml_ok else "✗ wkhtmltopdf not found")
        st.divider()

        # PDF download button — appears after a successful generation
        if st.session_state.last_pdf_path:
            p = Path(st.session_state.last_pdf_path)
            if p.exists():
                st.download_button(
                    label="⬇ Download PDF",
                    data=p.read_bytes(),
                    file_name=p.name,
                    mime="application/pdf",
                    use_container_width=True,
                )
        st.divider()

        st.header("Activity Log")
        st.text_area(
            "log",
            value="\n".join(st.session_state.logs[-40:]),
            height=280,
            disabled=True,
            label_visibility="collapsed",
        )

    # ── Page header ─────────────────────────────────────────────
    st.title("Resume Editor")

    # ── Action bar: buttons + save-as field ────────────────────
    btn1, btn2, _, save_col = st.columns([1, 1.4, 0.1, 3])
    with btn1:
        preview_clicked = st.button(
            "👁 Preview", use_container_width=True,
            help="Render via pandoc — same output as the PDF",
        )
    with btn2:
        save_clicked = st.button(
            "💾 Save & PDF", use_container_width=True,
            help="Save Markdown to generated/ and generate PDF",
        )
    with save_col:
        st.text_input(
            "Save As",
            key="save_as_name",
            help="e.g. resume_updated or resume_updated.md",
        )

    # ── Two-column layout ───────────────────────────────────────
    left_col, right_col = st.columns(2, gap="medium")

    with left_col:
        st.subheader("Markdown Source")
        st.caption("Edit here, then click **👁 Preview** or **💾 Save & PDF** above.")
        editor_result = code_editor(
            st.session_state.editor_content,
            lang="markdown",
            theme="default",
            height=[28, 42],
            key="main_editor",
            # response_mode="blur": editor sends its current text to Python
            # whenever focus leaves (mousedown on a button causes blur first,
            # so session_state.editor_content is always up-to-date before
            # the Streamlit button click rerun is processed).
            response_mode=["blur"],
            options={
                "lineNumbers": True,
                "lineWrapping": True,
                "tabSize": 2,
                "indentUnit": 2,
                "spellcheck": False,
            },
        )

    # ── Sync editor content from blur events ────────────────────
    if isinstance(editor_result, dict):
        etext = editor_result.get("text")
        etype = editor_result.get("type", "")
        # Accept blur, submit, or change events (all carry the current text)
        if isinstance(etext, str) and etext and etype in ("blur", "submit", "change"):
            st.session_state.editor_content = etext

    # ── Preview action ──────────────────────────────────────────
    if preview_clicked:
        st.session_state.logs.append("Generating preview…")
        html_out, err = pandoc_to_html(st.session_state.editor_content)
        if err:
            st.session_state.preview_html = None
            st.session_state.preview_error = err
            st.session_state.logs.append(f"✗ Preview: {err}")
        else:
            st.session_state.preview_html = html_out
            st.session_state.preview_error = None
            st.session_state.logs.append("✓ Preview updated")

    # ── Save & PDF action ───────────────────────────────────────
    if save_clicked:
        fname, err = validate_filename(st.session_state.save_as_name)
        if err:
            st.session_state.logs.append(f"✗ Filename error: {err}")
        else:
            out_dir = Path(OUTPUT_DIRECTORY)
            md_path = out_dir / fname
            pdf_path = out_dir / f"{md_path.stem}.pdf"

            # Write raw markdown — no conversion
            try:
                md_path.write_text(st.session_state.editor_content, encoding="utf-8")
                st.session_state.logs.append(f"✓ Saved: {md_path.as_posix()}")
            except OSError as exc:
                st.session_state.logs.append(f"✗ Save failed: {exc}")
            else:
                # Generate PDF with the user's exact margin options
                st.session_state.logs.append("Generating PDF…")
                ok, msg = generate_pdf(md_path, pdf_path)
                st.session_state.logs.append(msg)
                if ok:
                    st.session_state.last_pdf_path = str(pdf_path)
                    st.session_state.logs.append(f"PDF: {pdf_path.as_posix()}")
                else:
                    st.session_state.last_pdf_path = None

                # Refresh preview to reflect the saved state
                html_out, perr = pandoc_to_html(st.session_state.editor_content)
                if not perr:
                    st.session_state.preview_html = html_out
                    st.session_state.preview_error = None
                    st.session_state.logs.append("✓ Preview refreshed")

    # ── Right column — rendered preview ─────────────────────────
    with right_col:
        st.subheader("Rendered Preview")
        if st.session_state.preview_error:
            st.error(st.session_state.preview_error)
        elif st.session_state.preview_html:
            components.html(st.session_state.preview_html, height=900, scrolling=True)
        else:
            st.info(
                "Click **👁 Preview** to render your resume here.\n\n"
                "The preview is generated by pandoc — it matches what your PDF will look like."
            )


if __name__ == "__main__":
    main()
