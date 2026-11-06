"""
UEnvision — subject profiles: which skills are built up in each subject, from the
curriculum survey answers (professors, students and alumni).

The profile is DERIVED data, stored in SubjectSkillStat and rebuilt by plain code (no
Gemini) after every survey submit or edit (a post_save / post_delete signal, see the end
of this file), so it always matches the survey answers. One row per (data set, program,
subject, skill) with how many professors and how many students/alumni reported the skill
for that subject and their average level.

Subjects are matched by NAME, not code: the name is normalized (capitals, spacing and
punctuation ignored) and then the aliases an administrator set on Data > Recommendations
are applied ("Fundamentals of Programming" = "Computer Programming 1"). A subject both
BSIT and BSCS have is counted in each program that has it, at that program's year level,
so "earlier year levels" are always looked up in the same program.

Skill names are grouped exactly like the gap analysis (gap_analysis._standardize: only
capitals, spacing and punctuation are ignored), so nothing here re-merges skill counts.
Nothing here changes any count shown from the extracted / hard skills data sets.

Settings (data/.state/recommendation_settings.json, changed on Data > Recommendations):
    min_respondents   how many people must report a skill for a subject before it counts
                      as built up there (used for assumed skills and the faculty view)
"""
import json
import re

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from . import curriculum_data, gap_analysis
from .models import CurriculumSurveyResponse, SubjectAlias, SubjectSkillStat
from .pipeline import manager as pipeline

DEFAULT_SETTINGS = {"min_respondents": 2}
MIN_RESPONDENTS_RANGE = (1, 50)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def _settings_file():
    return pipeline.state_dir() / "recommendation_settings.json"


def get_settings() -> dict:
    out = dict(DEFAULT_SETTINGS)
    try:
        saved = json.loads(_settings_file().read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            out.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
    except (OSError, ValueError):
        pass
    try:
        out["min_respondents"] = max(MIN_RESPONDENTS_RANGE[0], min(MIN_RESPONDENTS_RANGE[1], int(out["min_respondents"])))
    except (TypeError, ValueError):
        out["min_respondents"] = DEFAULT_SETTINGS["min_respondents"]
    return out


def save_settings(cfg: dict) -> None:
    path = _settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({k: cfg[k] for k in DEFAULT_SETTINGS}, indent=2), encoding="utf-8")
    tmp.replace(path)


def min_respondents() -> int:
    return get_settings()["min_respondents"]


# ---------------------------------------------------------------------------
# Subject names
# ---------------------------------------------------------------------------
def name_key(name) -> str:
    """'Computer Programming 1' / 'computer  programming-1' -> 'computer programming 1'."""
    text = re.sub(r"[^a-z0-9+#]+", " ", str(name or "").lower())
    return " ".join(text.split())[:160]


def alias_map() -> dict:
    """{alias name key: the name key it is the same subject as}, chains followed."""
    raw = dict(SubjectAlias.objects.values_list("alias_key", "same_as_key"))
    out = {}
    for key in raw:
        seen, cur = {key}, raw[key]
        while cur in raw and cur not in seen:   # a = b, b = c  ->  a = c
            seen.add(cur)
            cur = raw[cur]
        out[key] = cur
    return out


def canonical(name, aliases=None) -> str:
    key = name_key(name)
    aliases = alias_map() if aliases is None else aliases
    return aliases.get(key, key)


def subject_names() -> list:
    """Every subject name in the curriculum plus the ones people added in their surveys,
    for the alias picker. -> [name, ...] sorted, one per name key."""
    seen = {}
    for info in curriculum_data.subject_by_code().values():
        seen.setdefault(name_key(info["name"]), info["name"])
    for data in CurriculumSurveyResponse.objects.values_list("data", flat=True):
        for subj in (data or {}).get("subjects") or [] if isinstance(data, dict) else []:
            if isinstance(subj, dict) and subj.get("custom") and subj.get("name"):
                seen.setdefault(name_key(subj["name"]), " ".join(str(subj["name"]).split())[:160])
    return sorted(seen.values(), key=str.lower)


# ---------------------------------------------------------------------------
# Rebuilding
# ---------------------------------------------------------------------------
def _current_responses(dummy):
    """Each account's latest record per side (like gap_analysis._academic_responses), plus
    every response without an account. -> [(respondent_type, data)]"""
    rows = list(CurriculumSurveyResponse.objects.filter(is_dummy=dummy).order_by("created_at", "pk")
                .values_list("respondent_type", "data", "user_id"))
    side = lambda t: "professor" if t == CurriculumSurveyResponse.PROFESSOR else "learner"   # noqa: E731
    latest = {}
    for i, (rtype, _, uid) in enumerate(rows):
        if uid:
            latest[(uid, side(rtype))] = i
    return [(rtype, data) for i, (rtype, data, uid) in enumerate(rows)
            if isinstance(data, dict) and (not uid or latest[(uid, side(rtype))] == i)]


def build(dummy=False) -> list:
    """-> unsaved SubjectSkillStat rows computed from the survey answers."""
    by_code = curriculum_data.subject_by_code()
    lookup = curriculum_data.subject_lookup()
    aliases = alias_map()
    agg = {}   # (program, subject_key) -> {"name", "codes", "year", "skills": {skill_key: {...}}}

    for rtype, data in _current_responses(dummy):
        professor = rtype == CurriculumSurveyResponse.PROFESSOR
        course = str((data.get("personal_info") or {}).get("course") or "")
        mine = {}   # (program, subject_key, skill_key) -> (display, weight): one count per response
        meta = {}
        for subj in data.get("subjects") or []:
            if not isinstance(subj, dict) or not subj.get("code"):
                continue
            code = str(subj["code"])
            info = by_code.get(code)
            name = info["name"] if info else str(subj.get("name") or code)
            programs = info["programs"] if info else [p for p in (subj.get("programs") or []) if p in curriculum_data.PROGRAMS]
            if not professor:
                # a student / alumnus took the subject in their own program
                programs = [course] if course in curriculum_data.PROGRAMS and (not programs or course in programs) else programs
            key = canonical(name, aliases)
            for program in programs:
                year = (lookup.get((program, code)) or {}).get("year")
                m = meta.setdefault((program, key), {"name": name, "codes": set(), "year": year})
                m["codes"].add(code)
                if m["year"] is None:
                    m["year"] = year
                for raw, lvl in gap_analysis._skill_entries(subj.get("skills")):
                    hit = gap_analysis._standardize(raw)
                    if not hit:
                        continue
                    w = gap_analysis.level_weight(lvl)
                    prev = mine.get((program, key, hit[0]))
                    if prev is None or w > prev[1]:
                        mine[(program, key, hit[0])] = (hit[1], w)
        for (program, key), m in meta.items():
            entry = agg.setdefault((program, key), {"name": m["name"], "codes": set(), "year": m["year"], "skills": {}})
            entry["codes"] |= m["codes"]
            if entry["year"] is None:
                entry["year"] = m["year"]
            if key in {name_key(i["name"]) for c, i in by_code.items() if c in m["codes"]}:
                entry["name"] = m["name"]   # prefer the curriculum's own spelling
        for (program, key, skill_key), (display, w) in mine.items():
            s = agg[(program, key)]["skills"].setdefault(skill_key, {"skill": display, "p": [], "l": []})
            s["p" if professor else "l"].append(w)

    mean = lambda xs: sum(xs) / len(xs) if xs else None   # noqa: E731
    out = []
    for (program, key), entry in agg.items():
        for skill_key, s in entry["skills"].items():
            out.append(SubjectSkillStat(
                is_dummy=dummy, program=program, subject_key=key, subject_name=entry["name"][:160],
                codes=", ".join(sorted(entry["codes"]))[:200], year=entry["year"],
                skill_key=skill_key[:120], skill=s["skill"][:120],
                professors=len(s["p"]), learners=len(s["l"]),
                professor_depth=mean(s["p"]), learner_depth=mean(s["l"])))
    return out


def rebuild(dummy=False) -> int:
    rows = build(dummy)
    with transaction.atomic():
        SubjectSkillStat.objects.filter(is_dummy=dummy).delete()
        SubjectSkillStat.objects.bulk_create(rows, batch_size=500)
    return len(rows)


def rebuild_all() -> None:
    rebuild(False)
    rebuild(True)


def ensure_built(dummy=False) -> None:
    """First use after deploying: build the table if there are answers but no rows yet."""
    if not SubjectSkillStat.objects.filter(is_dummy=dummy).exists() and \
            CurriculumSurveyResponse.objects.filter(is_dummy=dummy).exists():
        rebuild(dummy)


def schedule_rebuild(dummy) -> None:
    """Rebuild once when the current transaction commits (several saves in one request,
    e.g. a submit that also links the account, rebuild only once)."""
    from django.db import connection
    dummy = bool(dummy)
    if connection.in_atomic_block and any(getattr(cb, "_profile_rebuild", None) is dummy
                                          for _sids, cb, *_rest in connection.run_on_commit):
        return

    def run():
        rebuild(dummy)
    run._profile_rebuild = dummy
    transaction.on_commit(run)


@receiver(post_save, sender=CurriculumSurveyResponse)
@receiver(post_delete, sender=CurriculumSurveyResponse)
def _survey_changed(sender, instance, **kwargs):
    schedule_rebuild(bool(instance.is_dummy))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
LEVEL_NAMES = (("Introduced", 0.5), ("Practiced", 0.835), ("Applied", 1.01))


def level_name(weight) -> str:
    """0-1 average level -> 'Introduced' / 'Practiced' / 'Applied' (nearest survey level)."""
    if weight is None:
        return ""
    for name, below in LEVEL_NAMES:
        if weight < below:
            return name
    return "Applied"


def stat_depth(stat) -> float:
    """Average level of everyone who reported it (professors and learners together)."""
    total = (stat.professor_depth or 0) * stat.professors + (stat.learner_depth or 0) * stat.learners
    return total / stat.respondents if stat.respondents else 0.0


def rows_for(program, dummy=False, subject_keys=None, year_below=None, year_above=None, counted_only=True):
    """SubjectSkillStat rows of one program (optionally only some subjects or year levels),
    only the ones reported by at least min_respondents people unless counted_only=False."""
    ensure_built(dummy)
    qs = SubjectSkillStat.objects.filter(is_dummy=dummy, program=program)
    if subject_keys is not None:
        qs = qs.filter(subject_key__in=list(subject_keys))
    if year_below is not None:
        qs = qs.filter(year__lt=year_below)
    if year_above is not None:
        qs = qs.filter(year__gt=year_above)
    rows = list(qs)
    if counted_only:
        need = min_respondents()
        rows = [r for r in rows if r.respondents >= need]
    return rows
