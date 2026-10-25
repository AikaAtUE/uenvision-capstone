"""
UEnvision — Professor recommendations: for the "under-taught" skills that
gap_analysis.py identifies (high job-market demand, little/no curriculum
survey coverage — see that module for exactly how that list is built), this
asks Gemini to find real training resources (courses, certifications, official
docs, video series) so a professor sees not just WHAT looks under-taught but
WHERE to learn/teach it.

Reuses the same api_keys.txt / google-genai setup as the scrape/extract
pipeline (myapp/pipeline/extract_skills_gemini.py — see that file for the
original key-rotation / error-classification pattern this borrows from).
Unlike that script, which runs as a long background job via the Console page,
this runs SYNCHRONOUSLY inside a single POST request (see
views.recommendations_generate_view), so:
  - retries/backoff are capped short (a couple of quick retries, not the
    extractor's up-to-120s waits) — a skill that still fails is just left out
    of that batch, with its error reported back, rather than blocking the page;
  - the number of skills processed per click is capped (MAX_SKILLS_PER_RUN)
    so one click can't run away with the API quota or the request timeout.

IMPORTANT caveat, surfaced in the UI too: this tries Gemini's Google Search
grounding tool first, so results are an actual live search rather than purely
"whatever the model remembers". But grounding support depends on the installed
google-genai version and the chosen model, so there's a graceful fallback to
plain (ungrounded) generation when the grounded call fails for a tool-related
reason — and ungrounded results can be outdated or, rarely, invented. Every
row this writes is marked "verified: no" (or "no (ungrounded)") because
nothing here has been checked by a human yet; this is a starting list to
review, not something to hand to students unreviewed.
"""
import base64
import csv
import json
import random
import re
import threading
import time
from pathlib import Path

from django.conf import settings

from .pipeline import manager as pipeline

MAX_SKILLS_PER_RUN = 8   # how many skills one "Generate" click will call Gemini for
MIN_RESOURCES = 3
MAX_RESOURCES = 6
RPM = 5                  # same free-tier assumption as extract_skills_gemini.py
MAX_RETRIES = 2          # short on purpose -- this runs inside an HTTP request
MODEL = "gemini-3.5-flash-lite"
_grounding_unavailable = False   # set once search grounding hits a quota error (free tier)

# One CSV per audience: professors get resources to learn/teach a skill, students and
# alumni get resources to learn it themselves. Same columns for both.
RECS_FILES = {
    "professor": "professor_training_recommendations.csv",
    "student": "student_learning_recommendations.csv",
}
RECS_FILENAME = RECS_FILES["professor"]
RECS_COLUMNS = ["skill", "type", "name", "provider", "link", "photo", "verified", "context", "generated_at"]
MAX_SKILLS_PER_STUDENT_RUN = 5

# A small neutral "course" icon, inlined as a data: URI so the CSV/UI never
# depends on a network fetch when Gemini doesn't supply its own thumbnail.
_PLACEHOLDER_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    b'<rect width="64" height="64" rx="10" fill="#eef0f4"/>'
    b'<path d="M32 16 10 25l22 9 22-9z" fill="#16233f"/>'
    b'<path d="M18 29v12c0 4 6 7 14 7s14-3 14-7V29" fill="none" stroke="#16233f" stroke-width="3"/>'
    b'</svg>'
)
DEFAULT_PHOTO = "data:image/svg+xml;base64," + base64.b64encode(_PLACEHOLDER_SVG).decode("ascii")

# Drop default course photos (.jpg/.jpeg/.png/.webp) into this folder and one is
# picked at random whenever Gemini doesn't give a photo link. Empty/missing
# folder -> DEFAULT_PHOTO above.
DEFAULT_PHOTOS_DIR = Path(__file__).resolve().parent / "static" / "myapp" / "img" / "course-photos"
_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# The only resource types written to the CSV. Anything else Gemini says is mapped
# onto the closest one by _normalize_type().
RESOURCE_TYPES = ("Training", "Lesson", "Course")
_TYPE_HINTS = (
    ("Training", ("training", "certif", "bootcamp", "workshop", "lab", "exam")),
    ("Lesson", ("lesson", "tutorial", "doc", "guide", "video", "article", "series", "playlist")),
)


def _normalize_type(raw) -> str:
    text = str(raw or "").strip().lower()
    for name in RESOURCE_TYPES:
        if text.startswith(name.lower()):
            return name
    for name, hints in _TYPE_HINTS:
        if any(h in text for h in hints):
            return name
    return "Course"


def default_photo() -> str:
    try:
        photos = sorted(p.name for p in DEFAULT_PHOTOS_DIR.iterdir()
                        if p.is_file() and p.suffix.lower() in _PHOTO_EXTS)
    except OSError:
        photos = []
    if not photos:
        return DEFAULT_PHOTO
    return f"{settings.STATIC_URL.rstrip('/')}/myapp/img/course-photos/{random.choice(photos)}"


_WRITE_LOCK = threading.Lock()


class RecommendationError(Exception):
    """Something the UI should show as a plain error message, not a traceback."""


# ---------------------------------------------------------------------------
# Storage: data/professor_training_recommendations.csv
# ---------------------------------------------------------------------------
def recs_path(audience: str = "professor") -> Path:
    return Path(settings.DATA_DIR) / RECS_FILES[audience]


def load_recommendations(audience: str = "professor") -> dict:
    """-> {skill_lower: [row, ...]} from whatever's already on disk, or {} if
    nothing has been generated yet."""
    path = recs_path(audience)
    if not path.is_file():
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row.get("skill") or "").strip().lower()
            if key:
                out.setdefault(key, []).append(row)
    return out


def _write_recommendations(by_skill: dict, audience: str = "professor") -> None:
    path = recs_path(audience)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for rows in by_skill.values() for r in rows]
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RECS_COLUMNS, lineterminator="\r\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------
_AUDIENCE_INTRO = {
    "professor": (
        "You are a curriculum advisor helping a university Computer Science / Information "
        "Technology department find real, currently available training resources for a "
        "specific technical skill, so a professor can learn it and teach it in class. "
    ),
    "student": (
        "You are a career advisor helping a university Computer Science / Information "
        "Technology student or fresh graduate find real, currently available resources to "
        "learn a specific technical skill on their own. Prefer free or low-cost, "
        "beginner-friendly options. "
    ),
}
_SYSTEM_PROMPT_BODY = (
    "If you have web search available, use it to find REAL "
    "courses, certifications, official documentation, or well-known video series -- "
    "never invent a course or a URL; if you are not certain a resource is real, leave "
    "it out instead. Prefer reputable providers (Coursera, edX, Udemy, freeCodeCamp, "
    "official vendor documentation, well-known YouTube channels). Mix free and paid "
    "options where possible. Respond with ONLY a JSON object, no commentary, no "
    "markdown fences, matching exactly this shape:\n"
    '{"resources": [{"type": "...", "name": "...", "provider": "...", "link": "...", '
    '"photo": "... or null"}]}\n'
    'Set "type" to exactly one of: "Training" (certifications, bootcamps, hands-on '
    'training programs), "Lesson" (a single tutorial, official documentation page, '
    'article, or video/video series), or "Course" (a structured multi-module course). '
    '"photo" is a direct link to an image for that resource (its thumbnail or cover), '
    'or null if you can\'t find one.\n'
    f"Return between {MIN_RESOURCES} and {MAX_RESOURCES} resources."
)
_SYSTEM_PROMPT = _AUDIENCE_INTRO["professor"] + _SYSTEM_PROMPT_BODY


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RecommendationError("The model's reply didn't contain a JSON object.")
    try:
        return json.loads(m.group(0))
    except ValueError as exc:
        raise RecommendationError(f"The model's reply wasn't valid JSON: {exc}") from exc


def short_error(e: Exception) -> str:
    """One readable line from a google-genai error, e.g. '429 RESOURCE_EXHAUSTED: You exceeded ...'."""
    code, status, message = getattr(e, "code", None), getattr(e, "status", None), getattr(e, "message", None)
    if code and message:
        text = f"{code} {status or ''}: {message}".replace("  ", " ")
    else:
        text = str(e)
    return re.sub(r"\s+", " ", text).strip()[:240]


def classify_error(e: Exception) -> str:
    """Returns 'rotate' | 'wait' | 'retry' | 'fatal' -- same categories as
    extract_skills_gemini.classify_error(), kept independent so this module
    doesn't depend on the pipeline package's own script-style entry point."""
    code = getattr(e, "code", None)
    low = str(e).lower()
    squashed = re.sub(r"[\s_]", "", low)
    if code == 429 or "resource_exhausted" in low:
        if "limit: 0" in low:
            return "fatal"
        if "perday" in squashed or "daily" in low:
            return "rotate"
        return "wait"
    if code in (401, 403):
        return "rotate"
    if code == 400 and ("api key" in low or "api_key" in low or "expired" in low):
        return "rotate"
    if code in (400, 404):
        return "fatal"
    return "retry"


def _call_gemini(client, model: str, skill: str, audience: str = "professor", context: str = "") -> list:
    """-> list of resource dicts for one skill. Raises on failure (caller
    classifies/retries/rotates)."""
    from google.genai import types  # imported lazily so this module still loads
                                     # even before `pip install google-genai` has run

    prompt = f'Skill: "{skill}"\n'
    if context:
        prompt += f"Context: {context}\n"
    prompt += "Find real training resources for this skill."
    base_cfg = dict(system_instruction=_AUDIENCE_INTRO[audience] + _SYSTEM_PROMPT_BODY, max_output_tokens=2048)

    grounding_tool = None
    try:
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
    except AttributeError:
        pass  # older google-genai version without Search grounding -- fall back below

    global _grounding_unavailable
    resp, grounded, grounding_quota_error = None, False, False
    if grounding_tool is not None and not _grounding_unavailable:
        try:
            resp = client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(tools=[grounding_tool], **base_cfg),
            )
            grounded = True
        except Exception as e:
            low = str(e).lower()
            # The free tier has no Google Search grounding for Gemini 3.x models, which
            # comes back as a 429 quota error -- so a 429 here is retried without search.
            grounding_quota_error = getattr(e, "code", None) == 429 or "resource_exhausted" in low
            if not grounding_quota_error and not any(w in low for w in ("tool", "search", "grounding", "function")):
                raise  # not a tool-support issue -- let the caller classify/retry/rotate this
            resp = None  # fall through to the ungrounded call below

    if resp is None:
        resp = client.models.generate_content(
            model=model, contents=prompt, config=types.GenerateContentConfig(**base_cfg))
        grounded = False
        if grounding_quota_error:
            _grounding_unavailable = True  # plain calls work, so stop spending requests on search

    data = _extract_json(getattr(resp, "text", "") or "")
    resources = data.get("resources")
    if not isinstance(resources, list) or not resources:
        raise RecommendationError("The model returned no resources for this skill.")

    out = []
    for r in resources[:MAX_RESOURCES]:
        if not isinstance(r, dict) or not r.get("name") or not r.get("link"):
            continue
        out.append({
            "type": _normalize_type(r.get("type")),
            "name": str(r["name"]).strip()[:200],
            "provider": str(r.get("provider") or "").strip()[:120],
            "link": str(r["link"]).strip()[:500],
            "photo": (str(r["photo"]).strip()[:500] if r.get("photo") else "") or default_photo(),
            "verified": "no" if grounded else "no (ungrounded)",
        })
    if not out:
        raise RecommendationError("The model's resources were missing a name or link.")
    return out


def generate_for_skills(skills: list, audience: str = "professor", context: str = "") -> dict:
    """Calls Gemini for exactly these skills (caller decides which ones are
    worth (re)generating), merges the results into the on-disk CSV, and
    returns {"results": {skill: [row, ...]}, "errors": {skill: message},
    "key_errors": [{"key": "Key N", "error": message}, ...]}.

    Every key in api_keys.txt is tried: when a key fails (quota, rate limit,
    invalid key...) it is dropped for the rest of the run and the same skill is
    retried on the next key. key_errors lists why each dropped key failed."""
    from google import genai

    keys_text = pipeline.read_api_keys_text()
    keys = [ln.strip() for ln in keys_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not keys:
        raise RecommendationError(
            "No Gemini API key is set. Add one on Data → Extract Skills first.")

    limit = MAX_SKILLS_PER_RUN if audience == "professor" else MAX_SKILLS_PER_STUDENT_RUN
    results, errors = {}, {}
    key_errors = {}   # key index -> why that key was dropped for this run
    key_idx = 0
    client = genai.Client(api_key=keys[key_idx])
    last_call = 0.0
    interval = 60.0 / RPM

    def next_working_key():
        """Index of the next key (after the current one, wrapping) that hasn't failed, or None."""
        for step in range(1, len(keys) + 1):
            i = (key_idx + step) % len(keys)
            if i not in key_errors:
                return i
        return None

    for skill in skills[:limit]:
        if len(key_errors) == len(keys):
            errors[skill] = f"skipped, all {len(keys)} API keys failed"
            continue
        retries = 0
        while True:
            wait = interval - (time.time() - last_call)
            if wait > 0:
                time.sleep(wait)
            last_call = time.time()
            try:
                resources = _call_gemini(client, MODEL, skill, audience, context)
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                rows = [{"skill": skill, "context": context, "generated_at": stamp, **r} for r in resources]
                results[skill] = rows
                break
            except RecommendationError as e:
                # the key worked but the reply was unusable -- ask again a couple of times
                retries += 1
                if retries > MAX_RETRIES:
                    errors[skill] = str(e)[:200]
                    break
            except Exception as e:
                kind = classify_error(e)
                if kind == "retry" and retries < MAX_RETRIES:
                    retries += 1        # server hiccup or network error: same key, short pause
                    time.sleep(2 * retries)
                    continue
                code = getattr(e, "code", None)
                if kind == "fatal" and code in (400, 404) and "api key" not in str(e).lower():
                    # a bad request or unknown model fails the same way on every key
                    errors[skill] = short_error(e)
                    break
                # quota, rate limit, invalid/expired key, or repeated server errors:
                # drop this key for the rest of the run and move on to the next one
                key_errors[key_idx] = short_error(e)
                nxt = next_working_key()
                if nxt is None:
                    errors[skill] = f"all {len(keys)} API keys failed"
                    break
                key_idx, retries = nxt, 0
                client = genai.Client(api_key=keys[key_idx])
                last_call = 0.0   # the per-minute pacing is per key, so a fresh key can go at once

    # Re-read just before writing so two people generating at once don't drop each other's rows.
    with _WRITE_LOCK:
        by_skill = load_recommendations(audience)
        for skill, rows in results.items():
            by_skill[skill.strip().lower()] = rows
        _write_recommendations(by_skill, audience)
    return {
        "results": results,
        "errors": errors,
        # never the keys themselves -- just their position in api_keys.txt
        "key_errors": [{"key": f"Key {i + 1}", "error": msg} for i, msg in sorted(key_errors.items())],
    }
