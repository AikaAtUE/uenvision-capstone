"""Recommendations Lab (/recs-lab/): developers only, blueprint-aware faculty advice, gap ranking
that keeps each skill's own share, and the skill tags. Gemini is always mocked."""
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from ..models import CurriculumSurveyResponse as R, CustomUser
from ..recs_lab import blueprints, engine, gemini, taxonomy
from .helpers import IsolatedDataMixin

LAB_PAGES = ["recs_lab", "recs_lab_faculty", "recs_lab_admin", "recs_lab_student", "recs_lab_alumni",
             "recs_lab_blueprints", "recs_lab_skills"]


def make_user(email, role, **kw):
    u = CustomUser.objects.create_user(email=email, password="secret123", first_name="T", last_name=email[:4],
                                       role=role, **kw)
    u.email_verified = True
    u.save()
    return u


class LabAccessTests(IsolatedDataMixin, TestCase):
    def test_developer_sees_every_page(self):
        self.client.force_login(make_user("dev@ue.edu.ph", CustomUser.Role.DEVELOPER))
        for name in LAB_PAGES:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)
        r = self.client.get(reverse("recs_lab_faculty") + "?subject=CCS%201101")
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse("recs_lab_blueprints") + "?subject=CCS%201101")
        self.assertEqual(r.status_code, 200)

    def test_other_roles_never_reach_it(self):
        roles = [CustomUser.Role.ADMINISTRATOR, CustomUser.Role.FACULTY, CustomUser.Role.STUDENT, CustomUser.Role.ALUMNI]
        for i, role in enumerate(roles):
            self.client.force_login(make_user(f"u{i}@ue.edu.ph", role))
            for name in LAB_PAGES:
                r = self.client.get(reverse(name))
                self.assertIn(r.status_code, (302, 404), f"{role} {name}")
                self.assertNotIn(b"Recommendations Lab", r.content)

    def test_anonymous_is_sent_to_login(self):
        r = self.client.get(reverse("recs_lab"))
        self.assertEqual(r.status_code, 302)

    def test_no_link_to_the_lab_in_the_normal_site(self):
        dev = make_user("dev2@ue.edu.ph", CustomUser.Role.DEVELOPER)
        self.client.force_login(dev)
        r = self.client.get("/", follow=True)
        self.assertNotIn(b"/recs-lab/", r.content)


class TaxonomyTests(IsolatedDataMixin, TestCase):
    def test_rule_tags(self):
        self.assertEqual(taxonomy.rule_tag("Python"), ("language", "lang-general"))
        self.assertEqual(taxonomy.rule_tag("React")[0], "framework")
        self.assertEqual(taxonomy.rule_tag("Agile")[0], "practice")
        self.assertEqual(taxonomy.rule_tag("JSON")[0], "concept")
        self.assertEqual(taxonomy.rule_tag("Cloud Computing")[0], "concept")

    def test_manual_tag_wins_and_reset_restores_rules(self):
        taxonomy.set_tag("Python", "tool", "", source="manual")
        self.assertEqual(taxonomy.tag("Python")["kind"], "tool")
        taxonomy.clear_tag("Python")
        self.assertEqual(taxonomy.tag("Python")["kind"], "language")

    def test_gemini_never_overwrites_manual_tags(self):
        taxonomy.set_tag("Python", "tool", "", source="manual")
        answer = {"skills": [{"skill": "Python", "kind": "language", "family": "lang-general"},
                             {"skill": "Jira", "kind": "tool", "family": "pm-tools"}]}
        with mock.patch.object(gemini, "_ask", return_value=answer) as ask:
            res = gemini.tag_skills(["Python", "Jira"])
        self.assertNotIn("Python", ask.call_args[0][1].split("Skills:\n", 1)[1])
        self.assertEqual(res["tagged"], 1)
        self.assertEqual(taxonomy.tag("Python")["kind"], "tool")
        self.assertEqual(taxonomy.tag("Jira")["source"], "gemini")


class BlueprintTests(IsolatedDataMixin, TestCase):
    def test_fundamentals_has_one_language_slot(self):
        bp = blueprints.get("CCS 1101")
        self.assertEqual(bp["status"], "auto")
        langs = [s for s in bp["slots"] if s["family"] == "lang-general"]
        self.assertEqual(len(langs), 1)
        self.assertEqual(langs[0]["count"], 1)
        self.assertFalse(langs[0]["optional"])

    def test_save_approve_reset(self):
        bp, problems = blueprints.from_text({"core": "Debugging | bug fixing | applied\nLoops", "slots":
                                             "Language | lang-general | 1 | required | Python, Java",
                                             "extensions": "Git", "out_of_scope": "A second language", "notes": "x"})
        self.assertEqual(problems, [])
        blueprints.save("CCS 1101", bp)
        got = blueprints.get("CCS 1101")
        self.assertEqual(got["status"], "draft")
        self.assertEqual([c["name"] for c in got["core"]], ["Debugging", "Loops"])
        self.assertEqual(got["core"][0]["target"], "applied")
        blueprints.approve("CCS 1101")
        self.assertEqual(blueprints.get("CCS 1101")["status"], "approved")
        blueprints.reset("CCS 1101")
        self.assertEqual(blueprints.get("CCS 1101")["status"], "auto")

    def test_gemini_draft_is_saved_as_draft(self):
        answer = {"core": [{"name": "Debugging", "also": [], "target": "practiced"}], "slots": [],
                  "extensions": [], "out_of_scope": [], "notes": "Logic first."}
        with mock.patch.object(gemini, "_ask", return_value=answer):
            gemini.draft_blueprint("CCS 1101")
        got = blueprints.get("CCS 1101")
        self.assertEqual((got["status"], got["source"]), ("draft", "gemini"))

    def test_gemini_failure_shows_a_message(self):
        self.client.force_login(make_user("dev@ue.edu.ph", CustomUser.Role.DEVELOPER))
        with mock.patch.object(gemini, "_ask", side_effect=gemini.LabGeminiError("Gemini is busy.")):
            r = self.client.post(reverse("recs_lab_blueprints"), {"subject": "CCS 1101", "action": "gemini"}, follow=True)
        self.assertContains(r, "Gemini is busy.")
        self.assertEqual(blueprints.get("CCS 1101")["status"], "auto")


class FacultyTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        prof = make_user("prof@ue.edu.ph", CustomUser.Role.FACULTY)
        R.objects.create(respondent_type=R.PROFESSOR, user=prof, data={"subjects": [
            {"code": "CCS 1101", "name": "Fundamentals of Programming",
             "skills": [{"name": "Python", "level": "Applied"}, {"name": "Debugging", "level": "Introduced"}]}]})
        for i in range(4):
            u = make_user(f"s{i}@ue.edu.ph", CustomUser.Role.STUDENT)
            R.objects.create(respondent_type=R.STUDENT, user=u, data={"personal_info": {"course": "BSCS"}, "subjects": [
                {"code": "CCS 1101", "name": "Fundamentals of Programming",
                 "skills": [{"name": "Python", "level": "Practiced"},
                            {"name": "Debugging", "level": "Practiced" if i == 0 else "Introduced"}]}]})
        self.prof = prof

    def test_language_slot_filled_and_no_second_language(self):
        v = engine.faculty_view("CCS 1101", self.prof.pk)
        lang = next(s for s in v["slots"] if s["family"] == "lang-general")
        self.assertEqual(lang["status"], "filled")
        self.assertIn("Python", lang["filled"])
        self.assertIn("No second", lang["why"])
        for r in v["rows"]:
            self.assertNotIn(r["item"], ("Java", "C++", "C"))

    def test_debugging_not_landing(self):
        v = engine.faculty_view("CCS 1101", self.prof.pk)
        dbg = next(r for r in v["core"] if r["item"] == "Debugging")
        self.assertEqual(dbg["status"], "not_landing")
        self.assertEqual((dbg["strong"], dbg["n"]), (1, 4))
        self.assertEqual(v["cards"][0]["status"], "not_landing")


class AdminGapTests(IsolatedDataMixin, TestCase):
    def test_members_keep_their_own_share(self):
        res = engine.admin_gaps(entry_only=False, floor=0.5)
        if not res["exists"]:
            self.skipTest("No extracted job data in this checkout.")
        d = engine.demand("", entry_only=False)
        for row in res["all_rows"]:
            for m in row["members"]:
                self.assertEqual(m["pct"], d["pct"][m["key"]])
            self.assertEqual(row["demand"], max(m["pct"] for m in row["members"]))
        gaps = [r["gap"] for r in res["rows"]]
        self.assertEqual(gaps, sorted(gaps, reverse=True))
        self.assertLessEqual(len(res["rows"]), 10)
