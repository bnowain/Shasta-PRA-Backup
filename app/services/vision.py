"""VLM image description service — Stage 3 of the document intelligence pipeline.

Routes through Mission Control's vision_model capability class when MC is running
(http://localhost:8860/models/run). Falls back to direct Ollama if MC is down.

MC's vision_model registry (config/models.json):
  - Primary:  ollama/llama3.2-vision:11b  (local, fast, general-purpose)
  - Secondary: ollama/qwen2-vl:7b         (local, strong on text-in-images)
  - Fallback: anthropic/claude-haiku-4-5  (cloud, vision-capable)

NOTE: Some of these models may already exist in Mission Control under other
capability classes. claude-haiku-4-5 is also registered as fast_model/planner_model.
The vision_model class is preferred for image tasks to get correct model routing.

See VISION_PIPELINE.md for the full 3-stage pipeline standard.
"""

import base64
import io
import logging
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# Mission Control endpoint
MC_URL = "http://localhost:8860"
MC_MODELS_RUN = f"{MC_URL}/models/run"
MC_HEALTH = f"{MC_URL}/api/health"

# Direct Ollama fallback
OLLAMA_URL = "http://localhost:11434"

# MC capability class for vision tasks
MC_VISION_CLASS = "vision_model"

# Prompt for all document descriptions — structured output format
# Each field has exactly one home, preventing redundancy.
DESCRIBE_PROMPT = """\
Describe this image for a public records archive. Respond using ONLY these four labeled fields, \
each on its own line. No markdown, no bold, no asterisks. Do not repeat any fact across fields. \
Be specific but not verbose.

Subject: [Who or what is the main subject — if a person is visible, state gender if clearly \
indicated by clothing, hair, or build; describe clothing and physical characteristics]
Visible text: [Transcribe any text, labels, or markings exactly as written — preserve Roman \
numerals (VII not 11, IV not 4); write "None" if no text is visible]
Setting: [Indoor or outdoor, location type, notable background elements]
Context: [What this image documents — use the record context above if relevant; state legal or \
official context if evident from visible evidence; do NOT speculate about causes or procedures \
not labeled in the image]\
"""

# Grading rubric weights (must sum to 100)
GRADE_WEIGHTS = {
    "field_completeness": 20,   # all 4 fields present and non-empty
    "gender_stated":      10,   # gender stated when inferable from visible cues
    "text_accuracy":      20,   # visible text transcribed correctly (roman numerals etc)
    "no_redundancy":      15,   # same fact not repeated across fields
    "no_speculation":     20,   # no invented causes, procedures, or substances
    "context_use":        15,   # record context used meaningfully when available
}

# Max PDF pages to describe per document (large maps can be many pages)
MAX_PDF_PAGES = 5

# Request timeouts — vision models load slowly on first call (cold start ~200s)
MC_TIMEOUT = 300        # MC adds routing overhead; vision models are slow
OLLAMA_TIMEOUT = 300    # direct Ollama; allow for cold model load


# ---------------------------------------------------------------------------
# Availability checks
# ---------------------------------------------------------------------------

def is_mc_available() -> bool:
    """Return True if Mission Control is running."""
    try:
        resp = httpx.get(MC_HEALTH, timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def is_ollama_vision_available(model: str = "llama3.2-vision") -> bool:
    """Return True if Ollama is running and has a vision-capable model."""
    try:
        resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if resp.status_code != 200:
            return False
        vision_keywords = ["vision", "llava", "qwen2-vl", "qwen2.5-vl", "minicpm", "moondream", "bakllava"]
        models = [m["name"].lower() for m in resp.json().get("models", [])]
        if model:
            return any(m.startswith(model.split(":")[0].lower()) for m in models)
        return any(any(kw in m for kw in vision_keywords) for m in models)
    except Exception:
        return False


def list_vision_models() -> list[str]:
    """Return available Ollama models that support vision."""
    try:
        resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if resp.status_code != 200:
            return []
        vision_keywords = ["vision", "llava", "qwen2-vl", "qwen2.5-vl", "minicpm", "moondream", "bakllava"]
        return [
            m["name"] for m in resp.json().get("models", [])
            if any(kw in m["name"].lower() for kw in vision_keywords)
        ]
    except Exception:
        return []


def get_backend() -> str:
    """Return 'mc' if Mission Control is available, 'ollama' if local vision model exists, else 'none'."""
    if is_mc_available():
        return "mc"
    if list_vision_models():
        return "ollama"
    return "none"


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _encode_file(image_path: Path) -> str:
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


def _render_pdf_page(pdf_path: Path, page_index: int) -> str:
    """Render a PDF page to base64 JPEG using PyMuPDF."""
    import fitz
    from PIL import Image

    with fitz.open(str(pdf_path)) as doc:
        if page_index >= len(doc):
            return ""
        pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(2, 2))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------------
# MC backend — routes through vision_model capability class
# ---------------------------------------------------------------------------

def _describe_via_mc(image_b64: str, prompt: str = DESCRIBE_PROMPT) -> tuple[str, str]:
    """Send image to Mission Control POST /models/run using vision_model class.

    Returns (description_text, model_id_string).
    """
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                },
            ],
        }
    ]
    resp = httpx.post(
        MC_MODELS_RUN,
        json={
            "model_id": MC_VISION_CLASS,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 512,
        },
        timeout=MC_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data.get("response_text", "").strip()
    # MC returns the actual model used in model_id field
    model_id = data.get("model_id", MC_VISION_CLASS)
    return text, model_id


# ---------------------------------------------------------------------------
# Direct Ollama backend — fallback when MC is down
# ---------------------------------------------------------------------------

def _describe_via_ollama(image_b64: str, model: str, prompt: str = DESCRIBE_PROMPT) -> tuple[str, str]:
    """Call Ollama generate API directly with image content.

    Returns (description_text, model_id_string).
    """
    resp = httpx.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "options": {"temperature": 0.0},
        },
        timeout=OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    text = resp.json().get("response", "").strip()
    actual_model = resp.json().get("model", model)
    return text, actual_model


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

GRADE_PROMPT_TEMPLATE = """\
You are grading a VLM-generated description of a public records image.

DESCRIPTION TO GRADE:
{description}

RECORD CONTEXT PROVIDED TO THE MODEL:
{context}

Score each criterion from 0-10, then compute a weighted total.
Respond with ONLY valid JSON in this exact shape:
{{
  "field_completeness": <0-10>,
  "gender_stated": <0-10>,
  "text_accuracy": <0-10>,
  "no_redundancy": <0-10>,
  "no_speculation": <0-10>,
  "context_use": <0-10>,
  "notes": "<one sentence explaining the biggest weakness>"
}}

Criteria definitions:
- field_completeness (weight 20): All four fields present (Subject, Visible text, Setting, Context) and non-empty
- gender_stated (weight 10): Gender stated when clearly inferable from visible clothing/physical cues; 10=stated correctly, 5=omitted when inferable, 0=stated wrong
- text_accuracy (weight 20): Visible text transcribed correctly; Roman numerals preserved as Roman numerals (VII not 11); 10=exact, 5=minor error, 0=wrong or missing
- no_redundancy (weight 15): Same fact not repeated across multiple fields; 10=no repeats, 0=same info in 2+ fields
- no_speculation (weight 20): No invented causes, procedures, or substances not labeled in image; 10=none, 0=clear speculation
- context_use (weight 15): Record context (case name, dept, request topic) referenced meaningfully; 10=well-used, 5=ignored, 0=misused\
"""


def grade_description(description: str, context_provided: str = "") -> dict:
    """Grade a VLM description using MC's fast_model.

    Returns {scores, weighted_total, passed, notes, grader_model} or error dict.
    Routes through MC if available, direct Ollama otherwise.
    """
    import json as _json

    prompt = GRADE_PROMPT_TEMPLATE.format(
        description=description,
        context=context_provided or "(none provided)",
    )

    raw = ""
    grader_model = "unknown"

    try:
        if is_mc_available():
            resp = httpx.post(
                MC_MODELS_RUN,
                json={
                    "model_id": "fast_model",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 300,
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("response_text", "")
            grader_model = data.get("model_id", "fast_model")
        else:
            resp = httpx.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": "qwen2.5:7b", "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.0}},
                timeout=60,
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            grader_model = "qwen2.5:7b"

        # Extract JSON from response
        start = raw.find("{")
        end = raw.rfind("}") + 1
        scores = _json.loads(raw[start:end])

        weighted = (
            scores.get("field_completeness", 0) * GRADE_WEIGHTS["field_completeness"] / 10 +
            scores.get("gender_stated", 0)      * GRADE_WEIGHTS["gender_stated"] / 10 +
            scores.get("text_accuracy", 0)      * GRADE_WEIGHTS["text_accuracy"] / 10 +
            scores.get("no_redundancy", 0)      * GRADE_WEIGHTS["no_redundancy"] / 10 +
            scores.get("no_speculation", 0)     * GRADE_WEIGHTS["no_speculation"] / 10 +
            scores.get("context_use", 0)        * GRADE_WEIGHTS["context_use"] / 10
        )

        return {
            "scores": scores,
            "weighted_total": round(weighted, 1),
            "passed": weighted >= 70,
            "notes": scores.get("notes", ""),
            "grader_model": grader_model,
        }

    except Exception as e:
        return {"error": str(e), "weighted_total": None, "passed": None}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def describe_image_file(image_path: Path, fallback_model: str = "qwen2.5vl:7b") -> tuple[str, str]:
    """Describe a standalone image file.

    Routes through MC vision_model if MC is running, otherwise uses Ollama directly.
    Returns (description_text, model_id).
    """
    image_b64 = _encode_file(image_path)
    backend = get_backend()

    if backend == "mc":
        log.debug(f"VLM via MC: {image_path.name}")
        return _describe_via_mc(image_b64)
    elif backend == "ollama":
        models = list_vision_models()
        model = models[0] if models else fallback_model
        log.debug(f"VLM via Ollama ({model}): {image_path.name}")
        return _describe_via_ollama(image_b64, model)
    else:
        raise RuntimeError(
            "No vision backend available. "
            "Start Mission Control (port 8860) or pull a vision model: "
            "ollama pull llama3.2-vision:11b"
        )


def describe_pdf_pages(
    pdf_path: Path,
    fallback_model: str = "qwen2.5vl:7b",
    max_pages: int = MAX_PDF_PAGES,
    prompt: str = DESCRIBE_PROMPT,
) -> list[dict]:
    """Describe each page of a PDF using a VLM.

    Returns list of {page_number, text, method, model_id}.
    """
    import fitz

    backend = get_backend()
    ollama_model = None
    if backend == "ollama":
        models = list_vision_models()
        ollama_model = models[0] if models else fallback_model

    results = []
    with fitz.open(str(pdf_path)) as doc:
        n_pages = min(len(doc), max_pages)

    for i in range(n_pages):
        image_b64 = _render_pdf_page(pdf_path, i)
        if not image_b64:
            results.append({"page_number": i, "text": "", "method": "vlm_description", "model_id": None})
            continue

        try:
            if backend == "mc":
                text, model_id = _describe_via_mc(image_b64, prompt)
            elif backend == "ollama":
                text, model_id = _describe_via_ollama(image_b64, ollama_model, prompt)
            else:
                raise RuntimeError("No vision backend available")
            results.append({"page_number": i, "text": text, "method": "vlm_description", "model_id": model_id})
        except Exception as e:
            log.warning(f"VLM failed for {pdf_path.name} page {i}: {e}")
            results.append({"page_number": i, "text": "", "method": "vlm_description", "model_id": None})

    return results


def _build_context_prompt(conn, doc_id: int) -> str:
    """Build a context prefix from the PRA request and sibling documents.

    Returns a string to prepend to DESCRIBE_PROMPT, or empty string if no context found.
    """
    from app.services.ocr import _execute, _fetchone, _fetchall

    # Get the request this document belongs to
    row = _fetchone(_execute(conn, """
        SELECT r.pretty_id, r.request_text, r.department_names, r.request_state
        FROM requests r
        JOIN documents d ON d.request_pretty_id = r.pretty_id
        WHERE d.id = ?
    """, (doc_id,)))
    if not row:
        return ""

    lines = ["RECORD CONTEXT (use this to inform your description):"]
    lines.append(f"Request ID: {row['pretty_id']} | Dept: {row['department_names']} | Status: {row['request_state']}")

    req_text = (row['request_text'] or "").strip().replace("\n", " ")
    if req_text:
        lines.append(f"Request summary: {req_text[:300]}{'...' if len(req_text) > 300 else ''}")

    # Sibling documents in the same request
    siblings = _fetchall(_execute(conn, """
        SELECT title, file_extension FROM documents
        WHERE request_pretty_id = (
            SELECT request_pretty_id FROM documents WHERE id = ?
        ) AND id != ?
        ORDER BY id LIMIT 10
    """, (doc_id, doc_id)))
    if siblings:
        sibling_names = ", ".join(f"{s['title']}" for s in siblings[:8])
        if len(siblings) > 8:
            sibling_names += f" (+{len(siblings)-8} more)"
        lines.append(f"Other files in this record: {sibling_names}")

    # Any existing text from sibling docs (first 200 chars of first match)
    existing = _fetchone(_execute(conn, """
        SELECT d.title, dt.text_content
        FROM documents d JOIN document_text dt ON dt.document_id = d.id
        WHERE d.request_pretty_id = (
            SELECT request_pretty_id FROM documents WHERE id = ?
        )
          AND d.id != ?
          AND LENGTH(dt.text_content) > 100
          AND dt.method != 'vlm_description'
        ORDER BY LENGTH(dt.text_content) DESC
        LIMIT 1
    """, (doc_id, doc_id)))
    if existing:
        snippet = existing['text_content'][:200].replace("\n", " ")
        lines.append(f"Text from '{existing['title']}': {snippet}...")

    return "\n".join(lines) + "\n\n"


def describe_document(conn, doc_id: int, local_path: str, ext: str, fallback_model: str = "qwen2.5vl:7b") -> dict:
    """Run VLM description on a document and store in document_text.

    Returns {success, page_count, char_count, backend, error}.
    """
    from datetime import datetime
    from app.services.ocr import _execute, _commit
    from app.config import BASE_DIR, IMAGE_OCR_EXTENSIONS

    result = {"success": False, "page_count": 0, "char_count": 0, "backend": "none", "model_id": None, "error": ""}

    file_path = Path(local_path.replace("\\", "/"))
    if not file_path.is_absolute():
        file_path = BASE_DIR / file_path

    if not file_path.exists():
        result["error"] = f"File not found: {file_path}"
        return result

    backend = get_backend()
    if backend == "none":
        result["error"] = (
            "No vision backend available. "
            "Start Mission Control or pull: ollama pull llama3.2-vision:11b"
        )
        return result

    result["backend"] = backend

    now = datetime.now().isoformat()
    _execute(conn,
        "INSERT INTO processing_log (document_id, operation, status, started_at, created_at) VALUES (?, ?, ?, ?, ?)",
        (doc_id, "vlm_describe", "processing", now, now))
    _commit(conn)

    ext_lower = ext.lower().lstrip(".")

    try:
        pages = []

        context_prefix = _build_context_prompt(conn, doc_id)
        prompt = context_prefix + DESCRIBE_PROMPT

        if ext_lower in IMAGE_OCR_EXTENSIONS:
            image_b64 = _encode_file(file_path)
            backend = get_backend()
            if backend == "mc":
                text, model_id = _describe_via_mc(image_b64, prompt)
            elif backend == "ollama":
                models = list_vision_models()
                model = models[0] if models else fallback_model
                text, model_id = _describe_via_ollama(image_b64, model, prompt)
            else:
                raise RuntimeError("No vision backend available")
            pages = [{"page_number": 0, "text": text, "method": "vlm_description", "model_id": model_id}]

        elif ext_lower == "pdf":
            pages = describe_pdf_pages(file_path, fallback_model, prompt=prompt)

        elif ext_lower in {"docx", "doc", "pptx", "ppt"}:
            preview = file_path.parent / (file_path.name + ".preview.pdf")
            if preview.exists():
                pages = describe_pdf_pages(preview, fallback_model, prompt=prompt)
            else:
                result["error"] = "No preview PDF found"
                _execute(conn,
                    "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
                    "WHERE document_id=? AND operation=? AND status=?",
                    ("failed", result["error"], datetime.now().isoformat(), doc_id, "vlm_describe", "processing"))
                _commit(conn)
                return result

        else:
            result["error"] = f"Unsupported extension for VLM: .{ext_lower}"
            _execute(conn,
                "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
                "WHERE document_id=? AND operation=? AND status=?",
                ("failed", result["error"], datetime.now().isoformat(), doc_id, "vlm_describe", "processing"))
            _commit(conn)
            return result

        total_chars = 0
        model_used = None
        for page in pages:
            text = page["text"]
            total_chars += len(text)
            page_model = page.get("model_id")
            if page_model:
                model_used = page_model
            _execute(conn,
                "INSERT OR REPLACE INTO document_text "
                "(document_id, page_number, text_content, method, model_id) VALUES (?, ?, ?, ?, ?)",
                (doc_id, page["page_number"], text, page["method"], page_model))

        result["model_id"] = model_used

        _commit(conn)
        _execute(conn,
            "UPDATE processing_log SET status=?, completed_at=? "
            "WHERE document_id=? AND operation=? AND status=?",
            ("completed", datetime.now().isoformat(), doc_id, "vlm_describe", "processing"))
        _commit(conn)

        result["success"] = True
        result["page_count"] = len(pages)
        result["char_count"] = total_chars
        return result

    except Exception as e:
        result["error"] = str(e)
        _execute(conn,
            "UPDATE processing_log SET status=?, error_message=?, completed_at=? "
            "WHERE document_id=? AND operation=? AND status=?",
            ("failed", result["error"], datetime.now().isoformat(), doc_id, "vlm_describe", "processing"))
        _commit(conn)
        return result


def get_visual_documents(conn, limit: int = 0) -> list[dict]:
    """Get documents processed by OCR that yielded near-zero text.

    These are candidates for VLM description (photos, maps, diagrams).
    Excludes docs already described by VLM.
    """
    from app.services.ocr import _execute, _fetchall

    sql = """
        SELECT d.id, d.title, d.file_extension, d.file_size_mb, d.local_path,
               d.request_pretty_id, SUM(LENGTH(dt.text_content)) as total_chars
        FROM documents d
        JOIN document_text dt ON dt.document_id = d.id
        WHERE d.downloaded = 1
          AND d.local_path IS NOT NULL
          AND LOWER(d.file_extension) IN ('jpg','jpeg','png','tif','tiff','bmp','pdf')
          AND d.id NOT IN (
              SELECT document_id FROM document_text WHERE method = 'vlm_description'
          )
        GROUP BY d.id
        HAVING total_chars < 10
        ORDER BY d.file_size_mb ASC
    """
    if limit > 0:
        sql += f" LIMIT {limit}"

    return _fetchall(_execute(conn, sql))
