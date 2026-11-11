"""
The Recommendations Lab's Gemini jobs. All run only after a developer clicks a button:

  tag_skills(names)        kind + family for skills the built-in rules don't know
  draft_blueprint(info)    a first blueprint for one subject (saved as "draft")
  ask_search(...)          learning resources (resources.py), with Google Search grounding

Gemini is never asked to score or rank anything: the engine does that with counts.
Keys and error handling are the same as recommendations.py (api_keys.txt + GEMINI_API_KEYS).
"""
import json
import time

from .. import recommendations
from ..pipeline import manager as pipeline
from . import blueprints, taxonomy

MODEL = recommendations.MODEL
MAX_TAG_BATCH = 120


class LabGeminiError(Exception):
    pass


def _keys():
    text = pipeline.read_api_keys_text()
    keys = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return list(dict.fromkeys(keys + pipeline.env_api_keys()))


def _ask(system, prompt, max_tokens=8192):
    """One JSON answer from Gemini, trying every key. -> dict."""
    from google import genai
    from google.genai import types

    keys = _keys()
    if not keys:
        raise LabGeminiError("No Gemini API key is set. Add one on Data → Data Extraction first.")
    errors = []
    for key in keys:
        client = genai.Client(api_key=key)
        for attempt in range(3):
            try:
                resp = client.models.generate_content(
                    model=MODEL, contents=prompt,
                    config=types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens,
                                                       response_mime_type="application/json"))
                return recommendations._extract_json(getattr(resp, "text", "") or "")
            except recommendations.RecommendationError as e:
                errors.append(str(e))
                continue
            except Exception as e:  # noqa: BLE001  (google-genai raises many types)
                kind = recommendations.classify_error(e)
                errors.append(recommendations.short_error(e))
                if kind in ("retry", "wait") and attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                break   # rotate / fatal: next key
    raise LabGeminiError("Gemini didn't answer: " + (errors[-1] if errors else "unknown error"))


_SEARCH_OFF = {"off": False}   # set once Google Search grounding fails for quota/tool reasons


def ask_search(system, prompt, max_tokens=4096):
    """One JSON answer using Google Search grounding (real pages), like recommendations.py.
    Grounding isn't on every key's tier: then the same request is asked without it."""
    from google import genai
    from google.genai import types

    keys = _keys()
    if not keys:
        raise LabGeminiError("No Gemini API key is set. Add one on Data → Data Extraction first.")
    errors = []
    for k in keys:
        client = genai.Client(api_key=k)
        for attempt in range(3):
            grounded = not _SEARCH_OFF["off"]
            try:
                if grounded:
                    cfg = types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens,
                                                      tools=[types.Tool(google_search=types.GoogleSearch())])
                else:
                    cfg = types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens,
                                                      response_mime_type="application/json")
                resp = client.models.generate_content(model=MODEL, contents=prompt, config=cfg)
                return recommendations._extract_json(getattr(resp, "text", "") or "")
            except recommendations.RecommendationError as e:
                errors.append(str(e))
                continue
            except Exception as e:  # noqa: BLE001
                low = str(e).lower()
                if grounded and (getattr(e, "code", None) == 429 or "resource_exhausted" in low
                                 or any(w in low for w in ("tool", "search", "grounding"))):
                    _SEARCH_OFF["off"] = True     # retry the same key without search
                    continue
                kind = recommendations.classify_error(e)
                errors.append(recommendations.short_error(e))
                if kind in ("retry", "wait") and attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                break
    raise LabGeminiError("Gemini didn't answer: " + (errors[-1] if errors else "unknown error"))


# ---------------------------------------------------------------------------
# Skill tags
# ---------------------------------------------------------------------------
_TAG_SYSTEM = (
    "You classify IT/CS skill names for a university curriculum tool. For each skill, give its kind: "
    '"concept" (an idea or body of knowledge, e.g. Recursion, Normalization, REST API design), '
    '"language" (a programming, query or markup language), "framework" (a framework or library), '
    '"tool" (a product, platform, service or database system) or "practice" (a way of working, e.g. Agile, '
    "Unit testing, Code review). For languages, frameworks and tools also give a family: the group of skills "
    "that can replace each other in a job (e.g. Python and Java are both general-purpose languages, MySQL and "
    "PostgreSQL are both relational databases). Use one of the family keys given when one fits; otherwise "
    'invent a short new family label in "new_family" and leave "family" empty. Concepts and practices have '
    'no family. Answer with ONLY JSON: {"skills": [{"skill": "...", "kind": "...", "family": "...", '
    '"new_family": "..."}]} with the skill names copied exactly.'
)


def tag_skills(names):
    """Tags up to MAX_TAG_BATCH names and saves them (source "gemini"). Names a developer
    tagged by hand are skipped. -> {"tagged": n, "new_families": [labels]}"""
    data = taxonomy.saved()
    todo = [n for n in dict.fromkeys(names) if data["skills"].get(taxonomy.key_of(n), {}).get("source") != "manual"]
    todo = todo[:MAX_TAG_BATCH]
    if not todo:
        return {"tagged": 0, "new_families": [], "tried": []}
    fams = taxonomy.families(data)
    fam_text = "\n".join(f"{k}: {f['label']} ({f['kind']})" for k, f in fams.items())
    prompt = f"Family keys:\n{fam_text}\n\nSkills:\n" + "\n".join(todo)
    answer = _ask(_TAG_SYSTEM, prompt)
    rows = answer.get("skills") if isinstance(answer, dict) else None
    if not isinstance(rows, list):
        raise LabGeminiError("Gemini's answer had no skills list.")
    wanted = {taxonomy.key_of(n): n for n in todo}
    tagged, new_labels = 0, []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = wanted.get(taxonomy.key_of(r.get("skill") or ""))
        kind = str(r.get("kind") or "").lower()
        if not name or kind not in taxonomy.KINDS:
            continue
        fam = str(r.get("family") or "")
        if kind in taxonomy.INTERCHANGEABLE and not fam and r.get("new_family"):
            label = " ".join(str(r["new_family"]).split())[:60]
            existing = next((k for k, f in taxonomy.families().items() if f["label"].lower() == label.lower()), None)
            fam = existing or taxonomy.add_family(label, kind)
            if not existing:
                new_labels.append(label)
        taxonomy.set_tag(name, kind, fam, source="gemini")
        tagged += 1
    return {"tagged": tagged, "new_families": new_labels, "tried": todo}


# ---------------------------------------------------------------------------
# Blueprints
# ---------------------------------------------------------------------------
_BP_SYSTEM = (
    "You help a Philippine university (UE College of Computer Studies and Systems, CHED BSIT/BSCS curriculum) "
    "describe what one subject is FOR, so a recommendation tool stops suggesting the wrong things. Think like the "
    "subject's syllabus, not like a job board. Give:\n"
    '- "core": the concepts the subject must build (3 to 12), each {"name", "also" (other names the same thing is '
    'reported under), "target" ("introduced", "practiced" or "applied": how far students should get)}. Prefer '
    "names from the skill list given, so they match survey answers.\n"
    '- "slots": needs that any ONE skill from a family fills, e.g. an intro programming subject needs exactly one '
    'general-purpose language, not Python AND Java. Each {"label", "family" (one of the family keys given), '
    '"count" (usually 1), "optional" (true/false), "options" (typical choices)}.\n'
    '- "extensions": optional extras worth adding once the core lands (0 to 8 names).\n'
    '- "out_of_scope": things that belong in other subjects and must not be suggested here (e.g. "A second '
    'programming language", "Frameworks").\n'
    '- "notes": one or two sentences on the subject\'s purpose.\n'
    "First-year subjects focus on fundamentals; upper-year subjects can follow industry tools more. "
    "Answer with ONLY a JSON object with exactly those keys."
)


def draft_blueprint(code, reported=()):
    """Asks Gemini for a blueprint of one subject and saves it as a draft. `reported`: skill
    names survey respondents reported for this subject (helps Gemini use their names)."""
    info = blueprints.subject(code)
    if not info:
        raise LabGeminiError("Unknown subject.")
    fams = taxonomy.families()
    years = ", ".join(f"{p} year {y}" for p, y in info["years"].items())
    prompt = (
        f"Subject: {info['code']} {info['name']}\nPrograms and year level: {years}\n"
        f"Curated skill list for this subject: {', '.join(blueprints.skills_catalog.suggestions_for(info['name']))}\n"
        f"Skills survey respondents reported for it: {', '.join(list(reported)[:60]) or 'none yet'}\n"
        "Family keys:\n" + "\n".join(f"{k}: {f['label']} ({f['kind']})" for k, f in fams.items())
    )
    answer = _ask(_BP_SYSTEM, prompt)
    if not isinstance(answer, dict) or not answer.get("core"):
        raise LabGeminiError("Gemini's blueprint had no core concepts.")
    return blueprints.save(code, answer, status="draft", source="gemini")


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)
