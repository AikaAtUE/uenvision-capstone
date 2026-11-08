"""CSV downloads of survey answers (Data > Survey Responses, administrators only).

- Curriculum surveys (Student / Alumni / Professor): one row per skill a respondent tagged,
  with who answered and the subject repeated on every row, so the file can be filtered or
  pivoted by respondent, subject or skill. A subject with no skills still gets one row.
- Feedback surveys (SUS / UAT / functional test sheet): one row per saved answer (for the
  test sheet, one row per test case), one file per survey since their questions differ.

The answers are written as they were saved (same names and values), not re-scored.
Files start with a UTF-8 byte order mark so Excel shows accented names correctly."""
import csv
import json
import re

from django.http import HttpResponse
from django.utils import timezone

from .views.common import PH_TIME

DATA_SET_LABELS = {True: "Dummy", False: "Real"}
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell(value):
    """A value as a CSV cell. Lists/dicts become JSON; text that Excel would run as a
    formula gets a leading apostrophe."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        if value.startswith(_FORMULA_START):
            return "'" + value
        return value
    return value


def _when(dt):
    return timezone.localtime(dt, PH_TIME).strftime("%Y-%m-%d %H:%M") if dt else ""


def _response(filename, header, rows):
    stamp = timezone.localtime(timezone.now(), PH_TIME).strftime("%Y%m%d-%H%M")
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}-{stamp}.csv"'
    resp.write("﻿")
    writer = csv.writer(resp)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return resp


def _dict(value):
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Curriculum surveys
# ---------------------------------------------------------------------------
# personal_info fields with their own column, in this order; any other field a response
# has gets a column after them ("About you: <field>").
INFO_COLUMNS = [("student_number", "Student number"), ("course", "Course"), ("year_level", "Year level"),
                ("year_graduated", "Year graduated"), ("section", "Section")]
_INFO_SKIP = {"name", "ue_email"} | {k for k, _ in INFO_COLUMNS}
# Top-level keys that are written elsewhere (or say nothing: consent is always true).
_TOP_SKIP = {"personal_info", "subjects", "employment", "consent", "edited_at", "target_role"}


def curriculum_csv(responses, filename):
    from . import curriculum_data, job_roles

    names_by_code = {code: info["name"] for code, info in curriculum_data.subject_by_code().items()}
    role_labels = getattr(job_roles, "ROLE_LABELS", {}) or {}

    info_extra, employment_keys, top_extra = [], [], []
    for resp in responses:
        data = _dict(resp.data)
        for k in _dict(data.get("personal_info")):
            if k not in _INFO_SKIP and k not in info_extra:
                info_extra.append(k)
        for k in _dict(data.get("employment")):
            if k not in employment_keys:
                employment_keys.append(k)
        for k in data:
            if k not in _TOP_SKIP and k not in top_extra:
                top_extra.append(k)

    header = (["Response ID", "Respondent type", "Data set", "Submitted (PH time)", "Last edited",
               "Name", "Email", "Account email"]
              + [label for _, label in INFO_COLUMNS]
              + [f"About you: {k}" for k in info_extra]
              + ["Target role"]
              + [f"Employment: {k}" for k in employment_keys]
              + top_extra
              + ["Subject code", "Subject name", "Semester", "Subject added by respondent", "Skill", "Skill level"])

    def rows():
        for resp in responses:
            data = _dict(resp.data)
            info = _dict(data.get("personal_info"))
            employment = _dict(data.get("employment"))
            user = resp.user
            role = str(data.get("target_role") or "")
            base = ([resp.pk, resp.get_respondent_type_display(), DATA_SET_LABELS[bool(resp.is_dummy)],
                     _when(resp.created_at), data.get("edited_at") or "",
                     info.get("name") or (user.get_full_name() if user else ""),
                     info.get("ue_email") or (user.email if user else ""),
                     user.email if user else ""]
                    + [info.get(k, "") for k, _ in INFO_COLUMNS]
                    + [info.get(k, "") for k in info_extra]
                    + [role_labels.get(role, role)]
                    + [employment.get(k, "") for k in employment_keys]
                    + [data.get(k, "") for k in top_extra])
            subjects = [s for s in (data.get("subjects") or []) if isinstance(s, dict)]
            if not subjects:
                yield base + ["", "", "", "", "", ""]
                continue
            for subj in subjects:
                code = str(subj.get("code") or "")
                subject = [code, subj.get("name") or names_by_code.get(code, ""),
                           subj.get("term_label") or subj.get("term") or "", bool(subj.get("custom"))]
                skills = subj.get("skills") or []
                if not skills:
                    yield base + subject + ["", ""]
                for sk in skills:
                    if isinstance(sk, dict):
                        yield base + subject + [sk.get("name") or "", sk.get("level") or ""]
                    elif isinstance(sk, str):
                        yield base + subject + [sk, ""]

    return _response(filename, header, rows())


# ---------------------------------------------------------------------------
# Feedback surveys (SUS / UAT / functional test sheet)
# ---------------------------------------------------------------------------
# Answer fields that go first, in this order, then q1, q2, ... then the scores, then any
# other field alphabetically, with "edited_at" last.
_FIRST = ["respondent_name", "respondent_role", "tester_name", "tester_role", "sus_audience", "uat_audience",
          "sus_version", "uat_version", "test_date", "submission_id"]
_SCORES = ["sus_score", "uat_score"]
_Q = re.compile(r"^q(\d+)$")


def _key_order(key):
    if key in _FIRST:
        return (0, _FIRST.index(key), "")
    m = _Q.match(key)
    if m:
        return (1, int(m.group(1)), "")
    if key in _SCORES:
        return (2, _SCORES.index(key), "")
    if key == "edited_at":
        return (4, 0, "")
    return (3, 0, key)


def feedback_csv(kind, responses, filename):
    keys = []
    for resp in responses:
        for k in _dict(resp.data):
            if k not in keys:
                keys.append(k)
    keys.sort(key=_key_order)
    header = ["Response ID", "Survey", "Data set", "Submitted (PH time)", "Account email"] + keys

    def rows():
        for resp in responses:
            data = _dict(resp.data)
            yield ([resp.pk, resp.get_survey_type_display(), DATA_SET_LABELS[bool(resp.is_dummy)],
                    _when(resp.created_at), resp.user.email if resp.user else ""]
                   + [data.get(k, "") for k in keys])

    return _response(filename, header, rows())
