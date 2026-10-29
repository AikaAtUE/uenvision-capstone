import json

from django.test import TestCase, override_settings
from django.urls import reverse

import re

from django.contrib.messages import get_messages

from .models import CustomUser, SurveyResponse

# Most tests log in as a plain Faculty account to test other things, so the "answer the
# Professor Survey first" redirect is off by default here; ProfessorSurveyFirstTests turns it on.
from django.conf import settings as _settings
_settings.REQUIRE_PROFESSOR_SURVEY = False


class SurveyAndLogoutTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="jose.rizal@ue.edu.ph", password="rizal123",
            first_name="Jose", last_name="Rizal",
        )
        self.url = reverse("survey_submit")

    def post(self, payload):
        return self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

    def sus_row(self, value=5):
        row = {f"q{n}": value for n in range(1, 7)}
        row.update({"respondent_role": "Student", "sus_score": 999, "comments": None})
        return row

    def test_requires_login(self):
        resp = self.post({"type": "sus", "rows": [self.sus_row()]})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(SurveyResponse.objects.count(), 0)

    def test_sus_saved_and_score_recomputed_on_server(self):
        self.client.force_login(self.user)
        # all-positive SUS: every item gives (answer - 1); all 5s -> 100, all 3s -> 50
        resp = self.post({"type": "sus", "rows": [self.sus_row(5)]})
        self.assertEqual(resp.status_code, 200)
        saved = SurveyResponse.objects.get()
        self.assertEqual(saved.user, self.user)
        self.assertEqual(saved.data["sus_score"], 100.0)  # client's 999 is ignored
        self.assertEqual(saved.data["sus_version"], 4)
        self.assertEqual(self.post({"type": "sus", "rows": [self.sus_row(3)]}).status_code, 200)
        self.assertEqual(SurveyResponse.objects.order_by("-pk").first().data["sus_score"], 50.0)

    def test_survey_js_asks_as_many_sus_questions_as_the_server_expects(self):
        import re
        from pathlib import Path
        from .views import SUS_QUESTION_COUNT
        js = (Path(__file__).parent / "static" / "myapp" / "survey.js").read_text(encoding="utf-8")
        block = re.search(r"var SUS_QUESTIONS = \[(.*?)\];", js, re.S).group(1)
        self.assertEqual(len(re.findall(r"^\s*'", block, re.M)), SUS_QUESTION_COUNT)

    def test_name_and_role_come_from_the_account(self):
        self.client.force_login(self.user)
        row = self.sus_row()  # the form says "Student"; the account is Faculty
        self.post({"type": "sus", "rows": [row]})
        saved = SurveyResponse.objects.get()
        self.assertEqual(saved.data["respondent_role"], "Faculty")
        self.assertEqual(saved.data["respondent_name"], "Jose Rizal")
        self.post({"type": "uat", "rows": [{"tester_name": "Someone else", "login_worked": "Yes"}]})
        uat = SurveyResponse.objects.get(survey_type="uat")
        self.assertEqual((uat.data["tester_name"], uat.data["tester_role"]), ("Jose Rizal", "Faculty"))

    def test_feedback_forms_do_not_ask_for_name_role_or_partial(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("feedback")).content.decode()
        for gone in ('id="sus-role"', 'id="uat-name"', 'id="uat-role"', 'id="uat-satisfaction"', 'id="functional-tester"'):
            self.assertNotIn(gone, html)
        self.assertIn("Answering as <strong>Jose Rizal</strong> (Faculty)", html)

    def test_uat_date_is_the_day_it_was_completed(self):
        from django.utils import timezone
        from .views import PH_TIME
        self.client.force_login(self.user)
        self.post({"type": "uat", "rows": [{"test_date": "2001-01-01", "login_worked": "Yes"}]})
        uat = SurveyResponse.objects.get(survey_type="uat")
        today = timezone.localdate(timezone=PH_TIME).isoformat()
        self.assertEqual(uat.data["test_date"], today)  # the form's date is ignored

    def test_feedback_forms_do_not_ask_for_program_or_test_date(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("feedback")).content.decode()
        for gone in ('id="sus-program"', 'id="uat-program"', 'id="uat-date"'):
            self.assertNotIn(gone, html)

    def test_sus_rejects_out_of_range_answer(self):
        self.client.force_login(self.user)
        row = self.sus_row(); row["q3"] = 9
        self.assertEqual(self.post({"type": "sus", "rows": [row]}).status_code, 400)
        self.assertEqual(SurveyResponse.objects.count(), 0)

    def test_functional_saves_one_row_per_test_case(self):
        self.client.force_login(self.user)
        rows = [{"submission_id": "abc", "test_case_id": f"TC-0{i}", "status": "Pass"} for i in (1, 2, 3)]
        self.assertEqual(self.post({"type": "functional", "rows": rows}).status_code, 200)
        self.assertEqual(SurveyResponse.objects.filter(survey_type="functional").count(), 3)

    def test_rejects_bad_type_and_bad_json_and_get(self):
        self.client.force_login(self.user)
        self.assertEqual(self.post({"type": "nope", "rows": [{}]}).status_code, 400)
        self.assertEqual(self.client.post(self.url, data="not json", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_logout_ends_session(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertRedirects(self.client.get(reverse("logout")), reverse("home"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)  # login_required kicks in

    def test_feedback_page_points_survey_js_at_submit_url(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("feedback")).content.decode()
        self.assertIn(f'data-submit-url="{self.url}"', html)

class RoleAndPasswordTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            "admin@ue.edu.ph", "adminpass1", first_name="Ada", last_name="Min",
            role=CustomUser.Role.ADMINISTRATOR)
        self.faculty = CustomUser.objects.create_user(
            "fac@ue.edu.ph", "facpass123", first_name="Fay", last_name="Culty")

    # --- role
    def test_default_role_is_faculty(self):
        self.assertEqual(self.faculty.role, "faculty")
        self.assertFalse(self.faculty.is_administrator)
        self.assertTrue(self.admin.is_administrator)

    def test_superuser_is_administrator(self):
        su = CustomUser.objects.create_superuser("su@ue.edu.ph", "superpass1", first_name="S", last_name="U")
        self.assertTrue(su.is_administrator)

    def test_signup_always_faculty_and_min_length(self):
        r = self.client.post(reverse("signup"), {"last_name": "A", "first_name": "B", "email": "x@ue.edu.ph",
                                                  "password": "short", "password2": "short"})
        self.assertContains(r, "at least 8")
        self.assertFalse(CustomUser.objects.filter(email="x@ue.edu.ph").exists())
        self.client.post(reverse("signup"), {"last_name": "A", "first_name": "B", "email": "x@ue.edu.ph",
                                              "password": "longenough1", "password2": "longenough1", "role": "administrator"})
        self.assertEqual(CustomUser.objects.get(email="x@ue.edu.ph").role, "faculty")

    # --- change password
    def test_change_password(self):
        self.client.force_login(self.faculty)
        url = reverse("change_password")
        post = lambda c, n, f: self.client.post(url, {"current_password": c, "new_password": n, "confirm_password": f}, follow=True)

        self.assertContains(post("wrong", "newpass123", "newpass123"), "Current password is incorrect")
        self.assertContains(post("facpass123", "short", "short"), "at least 8")
        self.assertContains(post("facpass123", "newpass123", "different1"), "do not match")
        self.faculty.refresh_from_db()
        self.assertTrue(self.faculty.check_password("facpass123"))

        r = post("facpass123", "newpass123", "newpass123")
        self.assertContains(r, "has been changed")
        self.faculty.refresh_from_db()
        self.assertTrue(self.faculty.check_password("newpass123"))
        # still logged in afterwards
        self.assertEqual(self.client.get(reverse("settings")).status_code, 200)

    def test_change_password_requires_login(self):
        r = self.client.post(reverse("change_password"), {})
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r["Location"])


class AccountsPageTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            "admin@ue.edu.ph", "adminpass1", first_name="Ada", last_name="Min",
            role=CustomUser.Role.ADMINISTRATOR)
        self.faculty = CustomUser.objects.create_user(
            "fac@ue.edu.ph", "facpass123", first_name="Fay", last_name="Culty")

    def test_sidebar_link_only_for_admin(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("dashboard")), reverse("accounts"))
        self.client.force_login(self.faculty)
        self.assertNotContains(self.client.get(reverse("dashboard")), reverse("accounts"))

    def test_faculty_blocked_everywhere(self):
        self.client.force_login(self.faculty)
        self.assertEqual(self.client.get(reverse("accounts")).status_code, 403)
        for name, args in [("account_create", []), ("account_edit", [self.admin.pk]),
                           ("account_reset_password", [self.admin.pk]), ("account_delete", [self.admin.pk])]:
            self.assertEqual(self.client.post(reverse(name, args=args), {"email": "z@ue.edu.ph"}).status_code, 403, name)
        self.assertTrue(CustomUser.objects.filter(pk=self.admin.pk).exists())

    def test_anonymous_redirected(self):
        self.assertEqual(self.client.get(reverse("accounts")).status_code, 302)

    def test_create(self):
        self.client.force_login(self.admin)
        url = reverse("account_create")
        base = {"last_name": "Cruz", "first_name": "Juan", "email": "juan@ue.edu.ph", "role": "faculty"}
        resp = self.client.post(url, base)
        u = CustomUser.objects.get(email="juan@ue.edu.ph")
        temp = _temporary_password(resp)
        self.assertTrue(u.check_password(temp))
        self.assertTrue(u.must_change_password)
        self.assertFalse(u.check_password("default123"))
        self.assertEqual(u.role, "faculty")
        # duplicate email (case-insensitive), bad role, short password
        self.client.post(url, {**base, "email": "JUAN@ue.edu.ph"})
        self.client.post(url, {**base, "email": "b@ue.edu.ph", "role": "root"})
        self.client.post(url, {**base, "email": "c@ue.edu.ph", "password": "short"})
        self.assertEqual(CustomUser.objects.filter(email__iexact="juan@ue.edu.ph").count(), 1)
        self.assertFalse(CustomUser.objects.filter(email__in=["b@ue.edu.ph", "c@ue.edu.ph"]).exists())
        self.client.post(url, {**base, "email": "boss@ue.edu.ph", "role": "administrator", "password": "mypassword1"})
        boss = CustomUser.objects.get(email="boss@ue.edu.ph")
        self.assertTrue(boss.is_administrator)
        self.assertTrue(boss.check_password("mypassword1"))
        self.assertFalse(boss.must_change_password)  # a password the administrator typed is kept as is

    def test_edit_name_and_email(self):
        self.client.force_login(self.admin)
        url = reverse("account_edit", args=[self.faculty.pk])
        self.client.post(url, {"last_name": "New", "first_name": "Name", "middle_name": "M", "email": "new@ue.edu.ph"})
        self.faculty.refresh_from_db()
        self.assertEqual(self.faculty.get_full_name(), "Name M New")
        self.assertEqual(self.faculty.email, "new@ue.edu.ph")
        self.assertEqual(self.faculty.role, "faculty")  # edit can't change role
        # email already used by someone else
        self.client.post(url, {"last_name": "New", "first_name": "Name", "email": "admin@ue.edu.ph"})
        self.faculty.refresh_from_db()
        self.assertEqual(self.faculty.email, "new@ue.edu.ph")

    def test_reset_password(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("account_reset_password", args=[self.faculty.pk]))
        self.faculty.refresh_from_db()
        temp = _temporary_password(resp)
        self.assertTrue(self.faculty.check_password(temp))
        self.assertTrue(self.faculty.must_change_password)
        # a different one every time
        self.client.post(reverse("account_reset_password", args=[self.faculty.pk]))
        self.faculty.refresh_from_db()
        self.assertFalse(self.faculty.check_password(temp))

    def test_reset_own_password_keeps_session(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("account_reset_password", args=[self.admin.pk]))
        # still logged in, but sent to Settings to choose a new password first
        self.assertRedirects(self.client.get(reverse("accounts")), reverse("settings"))
        self.assertEqual(self.client.get(reverse("settings")).status_code, 200)

    def test_delete(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("account_delete", args=[self.faculty.pk]))
        self.assertFalse(CustomUser.objects.filter(pk=self.faculty.pk).exists())
        # cannot delete self
        self.client.post(reverse("account_delete", args=[self.admin.pk]))
        self.assertTrue(CustomUser.objects.filter(pk=self.admin.pk).exists())

    def test_get_not_allowed_on_actions(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("account_delete", args=[self.faculty.pk])).status_code, 405)


class IsolatedDataMixin:
    """Points DATA_DIR at a temporary copy of data/ (ontology + extracted skills) so
    tests that add custom skills or seed curated ones never touch the real files."""
    def setUp(self):
        import shutil, tempfile
        from pathlib import Path
        from django.conf import settings
        from django.test import override_settings
        from . import gap_analysis, job_roles, ontology, skills_catalog
        super().setUp()
        self._tmp = tempfile.mkdtemp()
        real = Path(settings.DATA_DIR)
        (Path(self._tmp) / "ontology").mkdir()
        shutil.copy(real / "ontology" / "mind_tech_ontology.csv", Path(self._tmp) / "ontology")
        if (real / "extracted_skills.csv").is_file():
            shutil.copy(real / "extracted_skills.csv", self._tmp)
        self._override = override_settings(DATA_DIR=Path(self._tmp))
        self._override.enable()
        skills_catalog._ENTRIES = None
        skills_catalog._CURATED_DONE = False
        job_roles._CACHE.update(key=None, value=None)
        ontology.subject_skill_map.cache_clear()

    def tearDown(self):
        import shutil
        from . import gap_analysis, job_roles, ontology, skills_catalog
        self._override.disable()
        shutil.rmtree(self._tmp, ignore_errors=True)
        skills_catalog._ENTRIES = None
        skills_catalog._CURATED_DONE = False
        job_roles._CACHE.update(key=None, value=None)
        ontology.subject_skill_map.cache_clear()
        super().tearDown()


class CurriculumCalendarTests(TestCase):
    def test_period_follows_calendar(self):
        from datetime import date
        from . import curriculum_data as cd
        first = cd.current_period(date(2026, 10, 23))
        self.assertEqual(first["slot"], "1")
        self.assertEqual(first["previous_sem_label"], "2nd Semester AY 2025-2026")
        self.assertEqual(first["previous_summer_label"], "Summer 2026")
        second = cd.current_period(date(2027, 1, 8))
        self.assertEqual(second["slot"], "2")
        self.assertEqual(second["previous_sem_label"], "1st Semester AY 2026-2027")
        self.assertIsNone(second["previous_summer_label"])
        self.assertEqual(cd.current_period(date(2026, 6, 1))["slot"], "summer")

    def test_first_semester_eligibility(self):
        from . import curriculum_data as cd
        elig = cd.build_student_eligibility("1")
        # 1st years: no previous term; nobody gets their current year's 2nd semester
        self.assertIsNone(elig["BSIT"]["1"]["previous"])
        self.assertEqual(elig["BSIT"]["4"]["current"]["term_key"], "y4s1")
        # previous semester is always the last regular semester; a summer in between is added
        self.assertEqual(elig["BSIT"]["3"]["previous"]["term_key"], "y2s2")
        self.assertEqual([t["term_key"] for t in elig["BSIT"]["3"]["previous_summer"]], ["y2sum"])
        self.assertEqual(elig["BSCS"]["3"]["previous"]["term_key"], "y2s2")
        self.assertEqual(elig["BSCS"]["3"]["previous_summer"], [])
        self.assertEqual(elig["BSCS"]["4"]["previous"]["term_key"], "y3s2")
        self.assertEqual([t["term_key"] for t in elig["BSCS"]["4"]["previous_summer"]], ["y3sum"])
        self.assertEqual([t["term_key"] for t in elig["BSIT"]["3"]["earlier"]], ["y1s1", "y1s2", "y2s1"])
        codes = [s["code"] for s in elig["BSIT"]["1"]["current"]["subjects"]]
        self.assertIn("CCP 1101", codes)

    def test_second_semester_eligibility(self):
        from . import curriculum_data as cd
        elig = cd.build_student_eligibility("2")
        self.assertEqual(elig["BSCS"]["1"]["current"]["term_key"], "y1s2")
        self.assertEqual(elig["BSCS"]["1"]["previous"]["term_key"], "y1s1")
        self.assertEqual(elig["BSCS"]["1"]["previous_summer"], [])

    def test_summer_eligibility(self):
        from . import curriculum_data as cd
        elig = cd.build_student_eligibility("summer")
        # a student in summer classes reports the 2nd semester that just ended
        self.assertEqual(elig["BSIT"]["2"]["current"]["term_key"], "y2sum")
        self.assertEqual(elig["BSIT"]["2"]["previous"]["term_key"], "y2s2")
        self.assertEqual(elig["BSIT"]["2"]["previous_summer"], [])


class CurriculumSurveySubmitTests(IsolatedDataMixin, TestCase):
    def payload(self, **over):
        p = {
            "consent": True,
            "personal_info": {"name": "Juan", "ue_email": "juan@ue.edu.ph", "course": "BSIT",
                              "student_number": "2023-1", "year_level": 3},
            "has_previous": True,
            "subjects": [
                {"code": "CIA 1102", "term": "current", "skills": [{"name": "Python", "level": "advanced"}]},
                {"code": "CIP 1102", "term": "previous", "skills": [{"name": "SQL", "level": "beginner"}]},
            ],
        }
        p.update(over)
        return p

    def post(self, payload):
        return self.client.post(reverse("student_survey_submit"), data=json.dumps(payload),
                                content_type="application/json")

    def test_accepts_valid(self):
        self.assertEqual(self.post(self.payload()).status_code, 200)

    def test_rejects_non_ue_email(self):
        p = self.payload()
        p["personal_info"]["ue_email"] = "juan@gmail.com"
        self.assertEqual(self.post(p).status_code, 400)

    def test_requires_previous_semester(self):
        p = self.payload()
        p["subjects"] = p["subjects"][:1]
        self.assertEqual(self.post(p).status_code, 400)

    def test_survey_pages_render(self):
        for name in ("student_survey", "alumni_survey"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        # the professor survey needs a faculty/administrator login
        self.assertEqual(self.client.get(reverse("professor_survey")).status_code, 302)


class GapWeightingTests(TestCase):
    def test_level_weights(self):
        from .gap_analysis import level_weight
        self.assertAlmostEqual(level_weight("applied"), 1.0)
        self.assertAlmostEqual(level_weight("Introduced"), 1 / 3)
        self.assertAlmostEqual(level_weight("beginner"), 0.25)
        self.assertAlmostEqual(level_weight(None), 1.0)

    def test_compute_with_responses(self):
        from . import gap_analysis
        from .models import CurriculumSurveyResponse
        CurriculumSurveyResponse.objects.create(respondent_type="professor", data={
            "subjects": [{"program": "BSIT", "code": "CFD 1101", "skills": [{"name": "SQL", "level": "introduced"}]}]})
        CurriculumSurveyResponse.objects.create(respondent_type="student", data={
            "personal_info": {"course": "BSIT"},
            "subjects": [{"code": "CFD 1101", "skills": [{"name": "SQL", "level": "expert"}]}]})
        gap = gap_analysis.compute(top=30)
        if not gap["exists"]:
            self.skipTest("no extracted_skills.csv")
        sql = next((r for r in gap["under_taught"] + gap["well_covered"] if r["skill"].lower() == "sql"), None)
        self.assertIsNotNone(sql)
        self.assertEqual(sql["academic_count"], 2)
        self.assertAlmostEqual(sql["academic_pct"], round((1 / 3 + 1.0) / 2 * 100, 1))
        self.assertAlmostEqual(sql["taught_depth_pct"], 33.3)
        self.assertAlmostEqual(sql["learned_proficiency_pct"], 100.0)
        subj = next(r for r in gap["by_subject"] if r["code"] == "CFD 1101")
        self.assertEqual(subj["respondents"], 2)
        self.assertEqual(gap_analysis.compute(top=30, program="BSIT")["survey_responses"], 2)
        self.assertEqual(gap_analysis.compute(top=30, program="BSCS")["survey_responses"], 0)


class RecommendationTypeTests(TestCase):
    def test_normalize_type(self):
        from .recommendations import _normalize_type
        self.assertEqual(_normalize_type("Certification"), "Training")
        self.assertEqual(_normalize_type("Official documentation"), "Lesson")
        self.assertEqual(_normalize_type("Online course"), "Course")
        self.assertEqual(_normalize_type(None), "Course")


class SkillCatalogTests(IsolatedDataMixin, TestCase):
    def test_curated_suggestions_are_subject_specific(self):
        from . import ontology
        skills = ontology.subject_skill_map()
        self.assertIn("SQL", skills["CFD 1101"])
        self.assertIn("Cisco Packet Tracer", skills["CIT 2201"])
        self.assertEqual(skills["CIT EL01"], [])

    def test_curated_names_missing_from_ontology_are_seeded(self):
        from . import skills_catalog
        skills_catalog.ensure_curated()
        names = [r["name"] for r in skills_catalog.search("linux")]
        self.assertIn("Linux", names)

    def test_search_finds_synonyms(self):
        r = self.client.get(reverse("skill_search"), {"q": "k8s"}).json()["results"][0]
        self.assertEqual((r["name"], r["synonym"], r["exact"]), ("Kubernetes", "k8s", True))
        self.assertEqual(self.client.get(reverse("skill_search"), {"q": "js"}).json()["results"][0]["name"], "JavaScript")

    def test_search_and_add(self):
        r = self.client.get(reverse("skill_search"), {"q": "dock"})
        self.assertIn("Docker", [x["name"] for x in r.json()["results"]])
        add = lambda name: self.client.post(reverse("skill_add"), data=json.dumps({"name": name}),
                                            content_type="application/json")
        r = add("Quantum Basket Weaving")
        self.assertTrue(r.json()["created"])
        r = self.client.get(reverse("skill_search"), {"q": "quantum basket"})
        self.assertEqual(r.json()["results"][0]["name"], "Quantum Basket Weaving")
        self.assertFalse(add("quantum basket weaving").json()["created"])   # no duplicates
        self.assertFalse(add("Docker").json()["created"])                    # already in the ontology
        self.assertEqual(add("<script>").status_code, 400)


class PublicSiteTests(IsolatedDataMixin, TestCase):
    def test_home_and_roles(self):
        r = self.client.get(reverse("home"))
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse("role_skills"), {"role": "data-analyst"})
        body = r.json()
        if not body.get("exists"):
            self.skipTest("no extracted_skills.csv")
        self.assertEqual(body["role"]["key"], "data-analyst")
        self.assertIn("overall_pct", body["role"]["skills"][0])
        self.assertEqual(self.client.get(reverse("home"), {"role": "data-analyst"}).status_code, 200)

    def test_charts_say_where_the_numbers_come_from(self):
        r = self.client.get(reverse("home"), {"role": "data-analyst"})
        if not r.context["stats"].get("exists"):
            self.skipTest("no extracted_skills.csv")
        overall = r.context["stats"]["overall"]["postings"]
        self.assertContains(r, f"According to {overall} IT/CS job posting")
        self.assertContains(r, "Data Analyst job posting")

    def test_role_for(self):
        from .job_roles import role_for
        self.assertEqual(role_for("Android Developer", "IT and Software"), "mobile")
        self.assertEqual(role_for("QA Automation Engineer, Hybrid", "IT and Software"), "qa")
        self.assertIsNone(role_for("Tax Accountant", "Accounting and Finance"))

    def test_check_gap_page(self):
        r = self.client.get(reverse("check_gap"), {"role": "qa"})
        self.assertContains(r, "?role=qa")

    def test_homepage_dashboard_and_gap_show_the_same_numbers(self):
        from . import gap_analysis, job_roles
        from .pipeline import manager as pipeline
        home = job_roles.skill_stats("", 10)
        if not home.get("exists"):
            self.skipTest("no extracted_skills.csv")
        dash = pipeline.skills_dashboard("hard", 10)
        gap = gap_analysis.compute(10)
        self.assertEqual(dash["stats"]["postings"], home["overall"]["postings"])
        self.assertEqual(gap["postings_considered"], home["overall"]["postings"])
        self.assertEqual([(b["skill"], b["count"], b["pct"]) for b in dash["bars"]],
                         [(s["skill"], s["count"], s["pct"]) for s in home["overall"]["skills"]])
        gap_rows = {r["skill"]: r["industry_pct"] for r in gap["under_taught"] + gap["well_covered"]}
        for s in home["overall"]["skills"]:
            if s["skill"] in gap_rows:
                self.assertEqual(gap_rows[s["skill"]], s["pct"])

    def test_skills_are_counted_as_written_in_the_data_set(self):
        from .gap_analysis import _standardize
        self.assertEqual(_standardize("JIRA")[0], _standardize(" Jira ")[0])
        self.assertNotEqual(_standardize("REST APIs")[0], _standardize("RESTful APIs")[0])
        self.assertEqual(_standardize("REST APIs")[1], "REST APIs")

    def test_tech_company_industries_are_merged(self):
        from .pipeline.skills_schema import TECH_INDUSTRY, normalize_record
        for name in ("IT and Software", "Information Technology / IT", "Computer Software / Engineering", "Internet"):
            self.assertEqual(normalize_record({"company_industry": name})["company_industry"], TECH_INDUSTRY)
        self.assertEqual(normalize_record({"company_industry": "Financial Services "})["company_industry"], "Financial Services")
        self.assertEqual(normalize_record({"company_industry": "Insurance"})["company_industry"], "Insurance")


class StudentFlowTests(IsolatedDataMixin, TestCase):
    def submit(self, url_name="student_survey_submit", **extra):
        payload = {
            "consent": True,
            "personal_info": {"name": "Juan Dela Cruz", "ue_email": "juan@ue.edu.ph", "course": "BSIT",
                              "student_number": "2023-1", "year_level": 1},
            "has_previous": False,
            "target_role": "data-analyst",
            "subjects": [{"code": "CCP 1101", "term": "current",
                          "skills": [{"name": "Python", "level": "advanced"}, {"name": "SQL", "level": "beginner"}]}],
        }
        payload.update(extra)
        return self.client.post(reverse(url_name), data=json.dumps(payload), content_type="application/json")

    def test_survey_register_dashboard(self):
        from .models import CurriculumSurveyResponse
        r = self.submit()
        reg = r.json()["register_url"]
        self.assertContains(self.client.get(reg), "Confirm your UE email")
        token = reg.split("t=", 1)[1]
        bad = self.client.post(reverse("register"), {"t": token, "email": "other@ue.edu.ph",
                                                     "password": "secret123", "password2": "secret123"})
        self.assertContains(bad, "same UE email")
        r = self.client.post(reverse("register"), {"t": token, "email": "JUAN@ue.edu.ph",
                                                   "password": "secret123", "password2": "secret123"})
        self.assertRedirects(r, reverse("student_dashboard"), fetch_redirect_response=False)
        user = CustomUser.objects.get(email="juan@ue.edu.ph")
        self.assertEqual(user.role, CustomUser.Role.STUDENT)
        self.assertEqual(user.target_role, "data-analyst")
        self.assertEqual(CurriculumSurveyResponse.objects.get().user, user)
        dash = self.client.get(reverse("student_dashboard"))
        self.assertEqual(dash.status_code, 200)
        self.assertContains(dash, "Job readiness")
        # the link can't be used twice
        self.assertContains(self.client.get(reg), "already")

    def test_learners_are_kept_out_of_staff_pages(self):
        user = CustomUser.objects.create_user(email="a@ue.edu.ph", password="secret123",
                                              first_name="A", last_name="B", role=CustomUser.Role.ALUMNI)
        self.client.force_login(user)
        for name in ("dashboard", "data", "recommendations", "professor_survey"):
            self.assertRedirects(self.client.get(reverse(name)), reverse("student_dashboard"),
                                 fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("feedback")).status_code, 200)
        self.assertNotContains(self.client.get(reverse("feedback")), "data-survey=\"uat\"")
        r = self.client.post(reverse("survey_submit"), data=json.dumps({"type": "uat", "rows": [{}]}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 403)
        # a logged-in learner retaking the survey is linked directly
        r = self.submit("alumni_survey_submit", employment={"employed": False},
                        personal_info={"name": "A B", "ue_email": "a@ue.edu.ph", "course": "BSIT",
                                       "student_number": "1", "year_graduated": "2026"})
        self.assertEqual(r.json()["next_url"], reverse("student_dashboard"))

    def test_role_save_and_generate_validation(self):
        user = CustomUser.objects.create_user(email="s@ue.edu.ph", password="secret123",
                                              first_name="S", last_name="T", role=CustomUser.Role.STUDENT)
        self.client.force_login(user)
        self.client.post(reverse("student_role"), {"role": "mobile"})
        user.refresh_from_db()
        self.assertEqual(user.target_role, "mobile")
        self.client.post(reverse("student_role"), {"role": "not-a-role"})
        user.refresh_from_db()
        self.assertEqual(user.target_role, "")
        self.assertEqual(self.client.post(reverse("student_generate"), {}).status_code, 400)


class ProfessorSurveyAndTargetsTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.prof = CustomUser.objects.create_user(email="prof@ue.edu.ph", password="secret123",
                                                   first_name="P", last_name="Q")
        self.client.force_login(self.prof)

    def test_professor_survey_links_account_without_personal_info(self):
        from .models import CurriculumSurveyResponse
        self.assertEqual(self.client.get(reverse("professor_survey")).status_code, 200)
        payload = {"consent": True, "personal_info": {"name": "ignored"},
                   "subjects": [{"program": "BSIT", "code": "CFD 1101", "skills": [{"name": "SQL", "level": "applied"}]}]}
        r = self.client.post(reverse("professor_survey_submit"), data=json.dumps(payload),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        resp = CurriculumSurveyResponse.objects.get()
        self.assertEqual(resp.user, self.prof)
        self.assertNotIn("personal_info", resp.data)
        page = self.client.get(reverse("recommendations"))
        self.assertContains(page, "Subjects you teach")

    def test_subject_targets(self):
        from . import gap_analysis
        t = gap_analysis.subject_targets("CFD 1101")
        if not t["exists"]:
            self.skipTest("no extracted_skills.csv")
        self.assertIn("SQL", [r["skill"] for r in t["targets"]])
        r = self.client.get(reverse("recommendations"), {"subject": "CFD 1101"})
        self.assertContains(r, "Fundamentals of Database Systems")
        # the older PROGRAM|CODE links still work
        self.assertContains(self.client.get(reverse("recommendations"), {"subject": "BSIT|CFD 1101"}),
                            "Fundamentals of Database Systems")

    def test_shared_subject_code_is_one_subject(self):
        from . import curriculum_data, gap_analysis
        from .models import CurriculumSurveyResponse
        info = curriculum_data.subject_by_code()["CDS 1101"]   # Data Structures, in both programs
        self.assertEqual(sorted(info["programs"]), ["BSCS", "BSIT"])
        pools = curriculum_data.professor_term_pools("1")
        codes = [s["code"] for pool in pools.values() for s in pool]
        self.assertEqual(len(codes), len(set(codes)))
        CurriculumSurveyResponse.objects.create(
            respondent_type=CurriculumSurveyResponse.PROFESSOR,
            data={"subjects": [{"code": "CDS 1101", "skills": [{"name": "Python", "level": "applied"}]}]})
        for program in ("BSIT", "BSCS"):
            responses, _ = gap_analysis._academic_responses(program)
            self.assertIn("CDS 1101", responses[0]["subjects"])
        labels = [label for _, label in self.client.get(reverse("recommendations")).context["subject_choices"]]
        self.assertEqual(sum(1 for l in labels if l.startswith("CDS 1101")), 1)
        self.assertFalse(any(l.startswith(("BSIT", "BSCS")) for l in labels))

    def test_practicum_research_capstone_not_in_professor_survey(self):
        from . import curriculum_data
        for slot in ("1", "2", "summer"):
            codes = {s["code"] for pool in curriculum_data.professor_term_pools(slot).values() for s in pool}
            self.assertFalse(codes & curriculum_data.NOT_TAUGHT_BY_PROFESSORS)
        values = [v for v, _ in self.client.get(reverse("recommendations")).context["subject_choices"]]
        self.assertNotIn("CCS 4970", values)
        self.assertIn("CFD 1101", values)


    def test_electives_hidden_and_custom_subject_added(self):
        from . import curriculum_data, gap_analysis
        from .models import CurriculumSurveyResponse
        for slot in ("1", "2", "summer"):
            codes = {s["code"] for pool in curriculum_data.professor_term_pools(slot).values() for s in pool}
            self.assertFalse(codes & curriculum_data.PROFESSIONAL_ELECTIVES)
        self.assertNotIn("CIT EL01", dict(self.client.get(reverse("recommendations")).context["subject_choices"]))

        def submit(subj):
            return self.client.post(reverse("professor_survey_submit"), content_type="application/json",
                                    data=json.dumps({"consent": True, "subjects": [subj]}))
        skills = [{"name": "Docker", "level": "applied"}]
        # neither BSIT nor BSCS, a code already in the curriculum, a hidden or unknown code: refused
        self.assertEqual(submit({"custom": True, "code": "ELX 4101", "name": "Cloud", "programs": [], "skills": skills}).status_code, 400)
        self.assertEqual(submit({"custom": True, "code": "CFD 1101", "name": "X", "programs": ["BSIT"], "skills": skills}).status_code, 400)
        self.assertEqual(submit({"code": "CIT EL01", "skills": skills}).status_code, 400)
        self.assertEqual(submit({"code": "NOPE 1", "skills": skills}).status_code, 400)
        r = submit({"custom": True, "code": " elx  4101 ", "name": "Cloud Computing", "programs": ["BSIT"], "skills": skills})
        self.assertEqual(r.status_code, 200, r.content)
        subj = CurriculumSurveyResponse.objects.get().data["subjects"][0]
        self.assertEqual((subj["code"], subj["programs"], subj["custom"]), ("ELX 4101", ["BSIT"], True))
        # counts for BSIT only, and shows up under "Subjects you teach"
        self.assertTrue(gap_analysis._academic_responses("BSIT")[0])
        self.assertFalse(gap_analysis._academic_responses("BSCS")[0])
        page = self.client.get(reverse("recommendations"), {"subject": "ELX 4101"})
        self.assertIn(("ELX 4101", "ELX 4101 — Cloud Computing"), page.context["my_subjects"])
        self.assertEqual(page.context["subject_value"], "ELX 4101")

    def test_custom_subject_editable_on_my_skills(self):
        from .models import CurriculumSurveyResponse
        resp = CurriculumSurveyResponse.objects.create(
            respondent_type="professor", user=self.prof,
            data={"subjects": [{"code": "CFD 1101", "skills": [{"name": "SQL", "level": "applied"}]}]})
        save = lambda subjects: self.client.post(reverse("my_skills_save"), content_type="application/json",
                                                 data=json.dumps({"subjects": subjects}))
        keep = {"code": "CFD 1101", "skills": [{"name": "SQL", "level": "applied"}]}
        r = save([keep, {"custom": True, "code": "ELX 4102", "name": "Game Dev", "programs": ["BSCS"],
                         "skills": [{"name": "Unity", "level": "practiced"}]}])
        self.assertEqual(r.status_code, 200, r.content)
        resp.refresh_from_db()
        added = resp.data["subjects"][1]
        self.assertEqual((added["code"], added["name"], added["programs"], added["custom"]), ("ELX 4102", "Game Dev", ["BSCS"], True))
        boot = json.loads(self.client.get(reverse("professor_survey")).content.decode().split('id="cs-bootstrap">', 1)[1].split("</script>", 1)[0])
        self.assertTrue(boot["record"][1]["custom"])
        self.assertEqual(save([keep, {"custom": True, "code": "ELX 4102", "name": "Game Dev", "programs": ["BSXX"],
                                      "skills": []}]).status_code, 400)

    def test_subject_term_tags(self):
        from . import curriculum_data
        tags = curriculum_data.subject_term_tags()
        self.assertIn({"tag": "Y1S1IT", "program": "BSIT", "year": 1, "sem": 1}, tags["CCP 1101"])
        self.assertEqual({t["program"] for t in tags["CDS 1101"]}, {"BSIT", "BSCS"})   # shared: one tag each
        self.assertTrue(any(t["tag"] == "Y2S3IT" for ts in tags.values() for t in ts))   # summer is S3

    def test_professor_subjects_sorted_year_sem_course(self):
        from . import curriculum_data
        tags = curriculum_data.subject_term_tags()
        for pool in curriculum_data.professor_term_pools("1").values():
            keys = [curriculum_data.subject_sort_key(s["code"], tags) for s in pool]
            self.assertEqual(keys, sorted(keys))
        # shared subject goes where BSIT has it
        it = [t for t in tags["CDS 1101"] if t["program"] == "BSIT"][0]
        self.assertEqual(curriculum_data.subject_sort_key("CDS 1101", tags)[:3], (it["year"], it["sem"], 0))
        values = [v for v, _ in self.client.get(reverse("recommendations")).context["subject_choices"]]
        self.assertEqual(values, sorted(values, key=lambda c: curriculum_data.subject_sort_key(c, tags)))

class RecommendationKeyRotationTests(TestCase):
    def _run(self, keys, outcomes, skills):
        """outcomes: {key: exception or None (success)}; returns (result, keys used per call)."""
        from unittest import mock
        from . import recommendations

        used = []
        fake_genai = mock.MagicMock()
        fake_genai.Client.side_effect = lambda api_key: api_key

        def call(client, model, skill, audience, context):
            used.append(client)
            exc = outcomes[client]
            if exc:
                raise exc
            return [{"type": "Course", "name": "X", "provider": "", "link": "https://e.com", "photo": "", "verified": "no"}]

        fake_google = mock.MagicMock(genai=fake_genai)
        with mock.patch.object(recommendations.pipeline, "read_api_keys_text", return_value="\n".join(keys)), \
                mock.patch.object(recommendations, "_call_gemini", side_effect=call), \
                mock.patch.dict("sys.modules", {"google": fake_google, "google.genai": fake_genai}), \
                mock.patch.object(recommendations, "_write_recommendations"), \
                mock.patch.object(recommendations, "RPM", 6000):
            return recommendations.generate_for_skills(skills, "student"), used

    def _err(self, code, msg):
        class ApiErr(Exception):
            pass
        e = ApiErr(msg)
        e.code, e.status, e.message = code, "X", msg
        return e

    def test_failed_key_moves_on_to_the_next(self):
        out, used = self._run(["k1", "k2", "k3"],
                              {"k1": self._err(429, "quota"), "k2": self._err(401, "bad key"), "k3": None},
                              ["SQL", "R"])
        self.assertEqual(set(out["results"]), {"SQL", "R"})
        self.assertEqual(used, ["k1", "k2", "k3", "k3"])   # dead keys are not retried for the next skill
        self.assertEqual([k["key"] for k in out["key_errors"]], ["Key 1", "Key 2"])

    def test_all_keys_failing_reports_each_key(self):
        out, used = self._run(["k1", "k2"],
                              {"k1": self._err(429, "quota"), "k2": self._err(401, "bad key")},
                              ["SQL", "R"])
        self.assertEqual(out["results"], {})
        self.assertEqual(len(out["key_errors"]), 2)
        self.assertIn("quota", out["key_errors"][0]["error"])
        self.assertIn("bad key", out["key_errors"][1]["error"])
        self.assertIn("SQL", out["errors"])
        self.assertIn("R", out["errors"])
        self.assertEqual(used, ["k1", "k2"])   # second skill is skipped, no wasted calls


class RecommendationGroundingFallbackTests(TestCase):
    def test_grounding_quota_error_falls_back_to_plain_call(self):
        from unittest import mock
        from . import recommendations

        class QuotaError(Exception):
            code = 429

        ok = mock.MagicMock(text='{"resources": [{"type": "Course", "name": "SQL Basics", "link": "https://example.com"}]}')
        client = mock.MagicMock()
        client.models.generate_content.side_effect = [QuotaError("RESOURCE_EXHAUSTED"), ok, ok]
        types = mock.MagicMock()
        fake_google = mock.MagicMock()
        fake_google.genai.types = types
        with mock.patch.dict("sys.modules", {"google": fake_google, "google.genai": fake_google.genai,
                                             "google.genai.types": types}), \
                mock.patch.object(recommendations, "_grounding_unavailable", False), \
                mock.patch.object(recommendations, "_check_links", side_effect=lambda rows: rows):
            rows = recommendations._call_gemini(client, "m", "SQL", "student")
            self.assertEqual(rows[0]["verified"], "no (ungrounded)")
            self.assertTrue(recommendations._grounding_unavailable)
            recommendations._call_gemini(client, "m", "R", "student")
        self.assertEqual(client.models.generate_content.call_count, 3)  # second skill skipped search


class RecommendationLinkCheckTests(TestCase):
    """verify_resource() opens each link Gemini suggests; requests is faked here."""

    class _Resp:
        def __init__(self, status=200, url="", body="", ctype="text/html; charset=utf-8", json_data=None):
            self.status_code, self.url, self._body = status, url, body.encode()
            self.headers, self.encoding, self._json = {"Content-Type": ctype}, "utf-8", json_data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_content(self, n):
            yield self._body

        def json(self):
            return self._json

    def _verify(self, link, name, resp=None, exc=None):
        from unittest import mock
        import requests
        from . import recommendations

        def get(url, **kw):
            if exc:
                raise exc
            r = resp(url, kw) if callable(resp) else resp
            if not r.url:
                r.url = url
            return r
        with mock.patch.object(requests, "get", side_effect=get):
            return recommendations.verify_resource(link, name)

    def test_real_course_page_passes(self):
        page = "<html><head><title>Introduction to Structured Query Language (SQL) | Coursera</title></head></html>"
        self.assertEqual(self._verify("https://www.coursera.org/learn/intro-sql",
                                      "Introduction to Structured Query Language (SQL)", self._Resp(body=page)), "ok")

    def test_404_and_missing_domain_are_dropped(self):
        import requests
        self.assertEqual(self._verify("https://www.coursera.org/learn/made-up", "Made Up Course",
                                      self._Resp(status=404)), "dead")
        err = requests.exceptions.ConnectionError("Failed to resolve 'fake-academy.io' ([Errno -2] Name or service not known)")
        self.assertEqual(self._verify("https://fake-academy.io/sql", "SQL Mastery", exc=err), "dead")

    def test_homepage_redirect_and_wrong_page_are_dropped(self):
        self.assertEqual(self._verify("https://www.freecodecamp.org/", "Data Analyst Certification",
                                      self._Resp(body="<title>freeCodeCamp</title>")), "dead")
        self.assertEqual(self._verify("https://www.edx.org/course/kubernetes-wizardry", "Kubernetes Wizardry",
                                      self._Resp(url="https://www.edx.org/", body="<title>edX</title>")), "dead")
        self.assertEqual(self._verify("https://example.com/courses/advanced-rust", "Advanced Rust Systems Programming",
                                      self._Resp(body="<title>Cooking with Herbs</title>" + "x" * 30000)), "dead")

    def test_bot_wall_is_kept_but_not_marked_checked(self):
        from unittest import mock
        from . import recommendations

        self.assertEqual(self._verify("https://www.udemy.com/course/sql-bootcamp/", "SQL Bootcamp",
                                      self._Resp(status=403)), "unknown")
        rows = [{"name": "A", "link": "https://a.com/x"}, {"name": "B", "link": "https://b.com/y"},
                {"name": "C", "link": "https://c.com/z"}]
        verdicts = {"A": "unknown", "B": "ok", "C": "dead"}
        with mock.patch.object(recommendations, "verify_resource", side_effect=lambda link, name: verdicts[name]):
            kept = recommendations._check_links(rows)
        self.assertEqual([(r["name"], r["verified"]) for r in kept],
                         [("B", recommendations.LINK_CHECKED), ("A", recommendations.LINK_UNCHECKABLE)])

    def test_youtube_uses_oembed_title(self):
        def resp(url, kw):
            if "oembed" in url:
                vid = kw["params"]["url"]
                if vid.endswith("fake"):
                    return self._Resp(status=400)
                return self._Resp(json_data={"title": "PostgreSQL Tutorial for Beginners", "author_name": "freeCodeCamp.org"})
            raise AssertionError("watch page should not be fetched")
        self.assertEqual(self._verify("https://www.youtube.com/watch?v=qw--VYLpxG4",
                                      "PostgreSQL Tutorial for Beginners", resp), "ok")
        self.assertEqual(self._verify("https://www.youtube.com/watch?v=fake", "PostgreSQL Tutorial", resp), "dead")
        self.assertEqual(self._verify("https://www.youtube.com/watch?v=qw--VYLpxG4",
                                      "Kotlin Coroutines Deep Dive", resp), "dead")

    def test_all_fake_links_ask_gemini_again(self):
        from unittest import mock
        from . import recommendations

        ok = mock.MagicMock(text='{"resources": [{"type": "Course", "name": "Fake", "link": "https://x.com/fake"}]}')
        client = mock.MagicMock()
        client.models.generate_content.return_value = ok
        types = mock.MagicMock()
        fake_google = mock.MagicMock()
        fake_google.genai.types = types
        with mock.patch.dict("sys.modules", {"google": fake_google, "google.genai": fake_google.genai,
                                             "google.genai.types": types}), \
                mock.patch.object(recommendations, "verify_resource", return_value="dead"):
            with self.assertRaises(recommendations.RecommendationError):
                recommendations._call_gemini(client, "m", "SQL", "student")


class MySkillsTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        from .models import CurriculumSurveyResponse
        self.user = CustomUser.objects.create_user(email="juan@ue.edu.ph", password="secret123",
                                                   first_name="Juan", last_name="D", role=CustomUser.Role.STUDENT)
        self.old = CurriculumSurveyResponse.objects.create(
            respondent_type="student", user=self.user,
            data={"personal_info": {"course": "BSIT"},
                  "subjects": [{"code": "CCP 1101", "skills": [{"name": "Java", "level": "expert"}]}]})
        self.resp = CurriculumSurveyResponse.objects.create(
            respondent_type="student", user=self.user,
            data={"personal_info": {"course": "BSIT"}, "target_role": "data-analyst",
                  "subjects": [{"code": "CCP 1101", "term": "current", "term_label": "1st Sem",
                                "skills": [{"name": "Python", "level": "advanced"}]}]})
        self.client.force_login(self.user)

    def save(self, payload):
        return self.client.post(reverse("my_skills_save"), data=json.dumps(payload), content_type="application/json")

    def test_page_shows_current_record(self):
        r = self.client.get(reverse("my_skills"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "My subjects &amp; skills")
        boot = json.loads(r.content.decode().split('id="cs-bootstrap">', 1)[1].split("</script>", 1)[0])
        self.assertEqual(boot["subjects"][0]["skills"], [{"name": "Python", "level": "advanced"}])   # latest only
        self.assertEqual(boot["subjects"][0]["name"], "Computer Programming 1")

    def test_edit_replaces_the_latest_response(self):
        from .models import CurriculumSurveyResponse
        r = self.save({"subjects": [
            {"code": "CCP 1101", "skills": [{"name": "Python", "level": "expert"}]},
            {"code": "CFD 1101", "skills": [{"name": "SQL", "level": "intermediate"}]}]})
        self.assertEqual(r.status_code, 200, r.content)
        self.resp.refresh_from_db()
        subs = {s["code"]: s for s in self.resp.data["subjects"]}
        self.assertEqual(subs["CCP 1101"]["skills"], [{"name": "Python", "level": "expert"}])
        self.assertEqual(subs["CCP 1101"]["term_label"], "1st Sem")      # earlier details are kept
        self.assertEqual(subs["CFD 1101"]["name"], "Fundamentals of Database Systems")
        self.assertEqual(self.resp.data["target_role"], "data-analyst")
        self.assertIn("edited_at", self.resp.data)
        self.assertEqual(CurriculumSurveyResponse.objects.count(), 2)     # edited in place, nothing added

    def test_bad_input_is_refused(self):
        self.assertEqual(self.save({"subjects": [{"code": "NOPE 1", "skills": []}]}).status_code, 400)
        self.assertEqual(self.save({"subjects": [{"code": "CCP 1101", "skills": [{"name": "Python", "level": ""}]}]}).status_code, 400)
        self.assertEqual(self.save({"nothing": 1}).status_code, 400)

    def test_only_latest_response_counts(self):
        from . import gap_analysis, student_views
        responses, by_type = gap_analysis._academic_responses()
        self.assertEqual(by_type["student"], 1)
        mine = student_views._my_skills(self.user)
        names = {m["skill"] for m in mine.values()}
        self.assertIn("Python", names)
        self.assertNotIn("Java", names)

    def test_tab_is_open_to_learners_only(self):
        self.assertContains(self.client.get(reverse("student_dashboard")), reverse("my_skills"))
        staff = CustomUser.objects.create_user(email="f@ue.edu.ph", password="secret123", first_name="F", last_name="G")
        self.client.force_login(staff)
        self.assertRedirects(self.client.get(reverse("my_skills")), reverse("professor_survey"))   # professors edit on the survey page


class ProfessorMySkillsTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        from .models import CurriculumSurveyResponse
        self.prof = CustomUser.objects.create_user(email="p@ue.edu.ph", password="secret123",
                                                   first_name="P", last_name="R", role=CustomUser.Role.FACULTY)
        CurriculumSurveyResponse.objects.create(
            respondent_type="professor", user=self.prof,
            data={"subjects": [{"code": "CFD 1101", "skills": [{"name": "Java", "level": "applied"}]}]})
        self.resp = CurriculumSurveyResponse.objects.create(
            respondent_type="professor", user=self.prof,
            data={"subjects": [{"code": "CCP 1101", "term": "current",
                                "skills": [{"name": "Python", "level": "practiced"}]}]})
        self.client.force_login(self.prof)

    def save(self, payload):
        return self.client.post(reverse("my_skills_save"), data=json.dumps(payload), content_type="application/json")

    def boot(self, url):
        return json.loads(self.client.get(url).content.decode().split('id="cs-bootstrap">', 1)[1].split("</script>", 1)[0])

    def test_survey_page_is_the_editable_record(self):
        self.assertRedirects(self.client.get(reverse("my_skills")), reverse("professor_survey"))
        boot = self.boot(reverse("professor_survey"))
        self.assertEqual([s["code"] for s in boot["record"]], ["CCP 1101"])     # latest only
        self.assertEqual(boot["record"][0]["skills"], [{"name": "Python", "level": "practiced"}])
        self.assertFalse(boot["consented"])   # these test records never recorded consent

    def test_professor_edit_in_place(self):
        r = self.save({"subjects": [{"code": "CCP 1101", "skills": [{"name": "Python", "level": "applied"}]}]})
        self.assertEqual(r.status_code, 200, r.content)
        self.resp.refresh_from_db()
        self.assertEqual(self.resp.data["subjects"][0]["skills"], [{"name": "Python", "level": "applied"}])
        self.assertEqual(self.resp.respondent_type, "professor")

    def test_learner_levels_and_untaught_subjects_refused(self):
        self.assertEqual(self.save({"subjects": [{"code": "CCP 1101", "skills": [{"name": "Python", "level": "beginner"}]}]}).status_code, 400)
        self.assertEqual(self.save({"subjects": [{"code": "CCS 4970", "skills": [{"name": "Python", "level": "applied"}]}]}).status_code, 400)

    def test_only_latest_professor_record_counts(self):
        from . import gap_analysis, views
        _, by_type = gap_analysis._academic_responses()
        self.assertEqual(by_type["professor"], 1)
        self.assertEqual([code for code, _ in views._my_subjects(self.prof)], ["CCP 1101"])

    def test_resubmitting_updates_record_and_consent_is_one_time(self):
        from .models import CurriculumSurveyResponse
        def submit(level):
            return self.client.post(reverse("professor_survey_submit"), content_type="application/json", data=json.dumps(
                {"consent": True, "subjects": [{"code": "CCP 1101", "skills": [{"name": "Python", "level": level}]}]}))
        CurriculumSurveyResponse.objects.filter(user=self.prof).delete()
        page = self.client.get(reverse("professor_survey"))
        self.assertContains(page, 'id="professor-consent"')                       # first visit: accept the notice
        self.assertEqual(submit("introduced").json()["created"], True)
        page = self.client.get(reverse("professor_survey"))
        self.assertNotContains(page, 'id="professor-consent"')                    # accepted once ...
        self.assertContains(page, "Data Privacy Notice")                          # ... still viewable
        self.assertContains(page, "Save changes")
        self.assertEqual(submit("applied").json()["created"], False)
        self.assertEqual(CurriculumSurveyResponse.objects.filter(user=self.prof).count(), 1)   # edited in place
        data = CurriculumSurveyResponse.objects.get(user=self.prof).data
        self.assertEqual(data["subjects"][0]["skills"], [{"name": "Python", "level": "applied"}])
        self.assertIn("consent_at", data)
        self.assertIn("edited_at", data)


class EnvApiKeyTests(TestCase):
    """Gemini keys can come from GEMINI_API_KEYS as well as api_keys.txt."""

    def test_env_keys_are_added_to_file_keys_without_duplicates(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock
        from django.test import override_settings
        from .pipeline import manager as pipeline

        with tempfile.TemporaryDirectory() as tmp:
            keys_file = Path(tmp) / "api_keys.txt"
            keys_file.write_text("key-a\n# comment\nkey-b\n", encoding="utf-8")
            with override_settings(API_KEYS_FILE=keys_file):
                with mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("GEMINI_API_KEYS", None)
                    self.assertEqual(pipeline.env_api_keys(), [])
                    self.assertEqual(pipeline.count_api_keys(), 2)
                with mock.patch.dict(os.environ, {"GEMINI_API_KEYS": "key-b, key-c"}):
                    self.assertEqual(pipeline.env_api_keys(), ["key-b", "key-c"])
                    self.assertEqual(pipeline.count_api_keys(), 3)
                    # The editable file on the Data page is left as it is.
                    self.assertNotIn("key-c", pipeline.read_api_keys_text())


class IdleTimeoutTests(TestCase):
    """Every role is logged out after IDLE_TIMEOUT_SECONDS without activity."""

    def login_as(self, role, email):
        user = CustomUser.objects.create_user(email=email, password="secret123",
                                              first_name="I", last_name="T", role=role)
        self.client.force_login(user)
        return user

    def age_session(self, seconds):
        import time
        session = self.client.session
        session["last_activity"] = int(time.time()) - seconds
        session.save()

    def test_idle_users_of_every_role_are_logged_out(self):
        pages = {CustomUser.Role.ADMINISTRATOR: "dashboard", CustomUser.Role.FACULTY: "dashboard",
                 CustomUser.Role.STUDENT: "student_dashboard", CustomUser.Role.ALUMNI: "student_dashboard"}
        for i, (role, page) in enumerate(pages.items()):
            with self.subTest(role=role):
                self.client.logout()
                self.login_as(role, f"idle{i}@ue.edu.ph")
                self.assertEqual(self.client.get(reverse(page)).status_code, 200)
                self.age_session(31 * 60)
                r = self.client.get(reverse(page))
                self.assertEqual(r.status_code, 302)
                self.assertTrue(r["Location"].startswith(reverse("login") + "?timeout=1"))
                self.assertNotIn("_auth_user_id", self.client.session)
                login = self.client.get(r["Location"])
                self.assertContains(login, "logged out after 30 minutes of inactivity")

    def test_activity_within_the_limit_keeps_the_session(self):
        self.login_as(CustomUser.Role.FACULTY, "active@ue.edu.ph")
        self.client.get(reverse("dashboard"))
        self.age_session(29 * 60)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.age_session(29 * 60)  # the request above refreshed the clock
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_ping_counts_as_activity(self):
        self.login_as(CustomUser.Role.STUDENT, "ping@ue.edu.ph")
        self.client.get(reverse("student_dashboard"))
        self.age_session(20 * 60)
        self.assertEqual(self.client.post(reverse("session_ping")).json(), {"ok": True})
        self.age_session(0)
        self.assertGreater(self.client.session["last_activity"], 0)

    def test_background_requests_do_not_keep_session_alive(self):
        self.login_as(CustomUser.Role.ADMINISTRATOR, "poll@ue.edu.ph")
        self.client.get(reverse("dashboard"))
        self.age_session(20 * 60)
        before = self.client.session["last_activity"]
        self.client.get(reverse("dashboard"), HTTP_X_BACKGROUND_REQUEST="1")
        self.assertEqual(self.client.session["last_activity"], before)
        self.age_session(31 * 60)
        r = self.client.get(reverse("dashboard"), HTTP_X_BACKGROUND_REQUEST="1")
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.json()["session_expired"])

    def test_expired_json_request_gets_401_not_redirect(self):
        self.login_as(CustomUser.Role.STUDENT, "json@ue.edu.ph")
        self.client.get(reverse("student_dashboard"))
        self.age_session(31 * 60)
        r = self.client.post(reverse("session_ping"), HTTP_ACCEPT="application/json")
        self.assertEqual(r.status_code, 401)


@override_settings(REQUIRE_EMAIL_VERIFICATION=True)
class EmailVerificationTests(TestCase):
    """Nobody has to confirm their email to use UEnvision. Students/alumni are reminded to; faculty aren't asked."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def signup(self, email="new@ue.edu.ph"):
        return self.client.post(reverse("signup"), {"last_name": "Cruz", "first_name": "Ana", "email": email,
                                                    "password": "longenough1", "password2": "longenough1"})

    def link_from_outbox(self):
        import re
        from django.core import mail
        return re.search(r"http://testserver(/verify-email/\S+/)", mail.outbox[-1].body).group(1)

    def unconfirmed_student(self, email="stu@ue.edu.ph"):
        return CustomUser.objects.create_user(email=email, password="longenough1", first_name="S", last_name="T",
                                              role=CustomUser.Role.STUDENT, email_verified=False)

    def test_faculty_signup_needs_no_confirmation(self):
        from django.core import mail
        r = self.signup()
        self.assertRedirects(r, reverse("dashboard"), fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertTrue(CustomUser.objects.get(email="new@ue.edu.ph").email_verified)
        self.assertFalse([m for m in mail.outbox if m.to == ["new@ue.edu.ph"]])

    def test_unconfirmed_student_can_log_in_and_confirm_later(self):
        from django.core import mail
        self.unconfirmed_student()
        r = self.client.post(reverse("login"), {"email": "stu@ue.edu.ph", "password": "longenough1"})
        self.assertRedirects(r, reverse("student_dashboard"), fetch_redirect_response=False)
        page = self.client.get(reverse("student_dashboard"))
        self.assertContains(page, "Please confirm your email.")
        settings_page = self.client.get(reverse("settings"))
        self.assertContains(settings_page, "Not confirmed")
        self.assertContains(settings_page, "Send confirmation link")
        r = self.client.post(reverse("send_my_verification"), {"next": reverse("student_dashboard")}, follow=True)
        self.assertContains(r, "We sent a confirmation link to stu@ue.edu.ph")
        self.assertEqual(mail.outbox[-1].to, ["stu@ue.edu.ph"])
        link = self.link_from_outbox()
        self.assertContains(self.client.get(link), "Email confirmed")
        self.assertTrue(CustomUser.objects.get(email="stu@ue.edu.ph").email_verified)
        self.assertContains(self.client.get(link), "This link doesn't work")  # only works once
        self.assertNotContains(self.client.get(reverse("student_dashboard")), "Please confirm your email.")
        self.assertContains(self.client.get(reverse("settings")), "Confirmed")

    def test_bad_link_is_rejected(self):
        self.unconfirmed_student()
        self.client.post(reverse("login"), {"email": "stu@ue.edu.ph", "password": "longenough1"})
        self.client.post(reverse("send_my_verification"))
        link = self.link_from_outbox()
        self.assertContains(self.client.get(link[:-3] + "xx/"), "This link doesn't work")
        self.assertFalse(CustomUser.objects.get(email="stu@ue.edu.ph").email_verified)

    def test_resend_is_rate_limited_and_does_not_reveal_accounts(self):
        from django.core import mail
        self.unconfirmed_student()
        self.client.post(reverse("resend_verification"), {"email": "stu@ue.edu.ph"})
        self.assertEqual(len(mail.outbox), 1)
        r = self.client.post(reverse("resend_verification"), {"email": "stu@ue.edu.ph"})
        self.assertContains(r, "wait a minute")
        self.assertEqual(len(mail.outbox), 1)
        r = self.client.post(reverse("resend_verification"), {"email": "nobody@ue.edu.ph"})
        self.assertContains(r, "If <strong>nobody@ue.edu.ph</strong> has an account")
        self.assertEqual(len(mail.outbox), 1)

    def test_student_changes_email_in_settings(self):
        from django.core import mail
        user = self.unconfirmed_student()
        user.email_verified = True
        user.save()
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("settings") + "?edit=1"), 'name="email" value="stu@ue.edu.ph"')
        r = self.client.post(reverse("update_account"), {"first_name": "S", "last_name": "T", "email": "gmail@example.com"})
        self.assertRedirects(r, reverse("settings") + "?edit=1", fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertEqual(user.email, "stu@ue.edu.ph")
        r = self.client.post(reverse("update_account"), {"first_name": "Sam", "middle_name": "Q", "last_name": "Tan",
                                                         "email": "sam.tan@ue.edu.ph"}, follow=True)
        self.assertContains(r, "We sent a confirmation link to sam.tan@ue.edu.ph")
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.middle_name, user.last_name, user.email),
                         ("Sam", "Q", "Tan", "sam.tan@ue.edu.ph"))
        self.assertFalse(user.email_verified)
        self.assertEqual(mail.outbox[-1].to, ["sam.tan@ue.edu.ph"])

    def test_faculty_changes_email_without_confirming(self):
        from django.core import mail
        user = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="longenough1", first_name="F",
                                              last_name="C", role=CustomUser.Role.FACULTY)
        CustomUser.objects.create_user(email="taken@ue.edu.ph", password="longenough1", first_name="T", last_name="K")
        self.client.force_login(user)
        r = self.client.post(reverse("update_account"), {"first_name": "F", "last_name": "C", "email": "taken@ue.edu.ph"},
                             follow=True)
        self.assertContains(r, "An account with this email already exists.")
        self.client.post(reverse("update_account"), {"first_name": "F", "last_name": "C", "email": "fac2@gmail.com"})
        user.refresh_from_db()
        self.assertEqual(user.email, "fac2@gmail.com")
        self.assertTrue(user.email_verified)
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotContains(self.client.get(reverse("settings")), "Not confirmed")

    def test_existing_and_admin_made_accounts_need_no_confirmation(self):
        user = CustomUser.objects.create_user(email="old@ue.edu.ph", password="secret123",
                                              first_name="O", last_name="L")
        self.assertTrue(user.email_verified)
        r = self.client.post(reverse("login"), {"email": "old@ue.edu.ph", "password": "secret123"})
        self.assertEqual(r.status_code, 302)

    @override_settings(REQUIRE_EMAIL_VERIFICATION=False)
    def test_without_email_settings_signup_logs_in_directly(self):
        r = self.signup("direct@ue.edu.ph")
        self.assertRedirects(r, reverse("dashboard"), fetch_redirect_response=False)
        self.assertTrue(CustomUser.objects.get(email="direct@ue.edu.ph").email_verified)


@override_settings(REQUIRE_EMAIL_VERIFICATION=True)
class StudentRegisterVerificationTests(StudentFlowTests):
    """Students/alumni registering after the survey get in right away and confirm their email later."""

    def test_survey_register_dashboard(self):
        from django.core import mail
        reg = self.submit().json()["register_url"]
        token = reg.split("t=", 1)[1]
        r = self.client.post(reverse("register"), {"t": token, "email": "juan@ue.edu.ph",
                                                   "password": "secret123", "password2": "secret123"})
        self.assertRedirects(r, reverse("student_dashboard"), fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(mail.outbox[-1].to, ["juan@ue.edu.ph"])
        self.assertContains(self.client.get(reverse("student_dashboard")), "Please confirm your email.")
        link = mail.outbox[-1].body.split("http://testserver", 1)[1].split()[0]
        self.assertContains(self.client.get(link), "Email confirmed")
        self.assertNotContains(self.client.get(reverse("student_dashboard")), "Please confirm your email.")


class DummyAccountTests(IsolatedDataMixin, TestCase):
    """Dummy Student / Dummy Faculty answers live in their own data set."""

    def setUp(self):
        super().setUp()
        self.admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                                    last_name="D", role=CustomUser.Role.ADMINISTRATOR)

    def make(self, kind, email):
        self.client.force_login(self.admin)
        self.client.post(reverse("account_create"), {"last_name": "T", "first_name": "Tester", "email": email,
                                                     "role": kind, "password": "secret123"})
        return CustomUser.objects.get(email=email)

    def student_payload(self, email):
        return {"consent": True,
                "personal_info": {"name": "Dummy Kid", "ue_email": email, "course": "BSIT",
                                  "student_number": "2099-1", "year_level": 1},
                "has_previous": False, "target_role": "data-analyst",
                "subjects": [{"code": "CCP 1101", "term": "current",
                              "skills": [{"name": "Python", "level": "advanced"}]}]}

    def test_admin_can_create_dummy_accounts(self):
        ds = self.make("dummy_student", "ds@ue.edu.ph")
        df = self.make("dummy_faculty", "df@ue.edu.ph")
        self.assertEqual((ds.role, ds.is_dummy, ds.role_label), ("student", True, "Dummy Student"))
        self.assertEqual((df.role, df.is_dummy, df.role_label), ("faculty", True, "Dummy Faculty"))
        self.assertContains(self.client.get(reverse("accounts")), "Dummy Faculty")

    def test_dummy_answers_are_kept_out_of_the_real_analysis(self):
        from . import gap_analysis
        from .models import CurriculumSurveyResponse
        ds = self.make("dummy_student", "ds@ue.edu.ph")
        df = self.make("dummy_faculty", "df@ue.edu.ph")
        self.client.force_login(ds)
        r = self.client.post(reverse("student_survey_submit"), data=json.dumps(self.student_payload("ds@ue.edu.ph")),
                             content_type="application/json")
        self.assertEqual(r.json()["next_url"], reverse("student_dashboard"))
        self.client.force_login(df)
        self.client.post(reverse("professor_survey_submit"), content_type="application/json", data=json.dumps(
            {"consent": True, "subjects": [{"code": "CCP 1101", "skills": [{"name": "SQL", "level": "applied"}]}]}))
        self.assertEqual(CurriculumSurveyResponse.objects.filter(is_dummy=True).count(), 2)
        self.assertEqual(CurriculumSurveyResponse.objects.get(user=ds).is_dummy, True)

        # a real public answer
        self.client.logout()
        self.client.post(reverse("student_survey_submit"), data=json.dumps(self.student_payload("real@ue.edu.ph")),
                         content_type="application/json")
        real = CurriculumSurveyResponse.objects.get(is_dummy=False)

        _, real_counts = gap_analysis._academic_responses()
        _, dummy_counts = gap_analysis._academic_responses(dummy=True)
        self.assertEqual(real_counts, {"student": 1, "alumni": 0, "professor": 0})
        self.assertEqual(dummy_counts, {"student": 1, "alumni": 0, "professor": 1})
        self.assertEqual(real.user, None)

    def test_dashboard_uses_the_users_data_set(self):
        from unittest import mock
        ds = self.make("dummy_student", "ds@ue.edu.ph")
        real_student = CustomUser.objects.create_user(email="rs@ue.edu.ph", password="secret123", first_name="R",
                                                      last_name="S", role=CustomUser.Role.STUDENT)
        self.client.force_login(real_student)
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("student_dashboard"),
                             fetch_redirect_response=False)
        self.client.force_login(ds)
        page = self.client.get(reverse("dashboard"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Test account.")
        with mock.patch("myapp.views.pipeline.skills_dashboard", return_value={"exists": True}), \
                mock.patch("myapp.views.gap_analysis.compute", return_value={"exists": False}) as compute:
            self.client.get(reverse("dashboard_skills"))
            self.assertTrue(compute.call_args.kwargs["dummy"])
            self.client.force_login(self.admin)
            self.client.get(reverse("dashboard_skills"))
            self.assertFalse(compute.call_args.kwargs["dummy"])


class SurveyResponsesAdminTests(TestCase):
    def setUp(self):
        from .models import CurriculumSurveyResponse as C
        self.admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                                    last_name="D", role=CustomUser.Role.ADMINISTRATOR)
        self.faculty = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="secret123", first_name="F",
                                                      last_name="C", role=CustomUser.Role.FACULTY)
        info = lambda n, e: {"name": n, "ue_email": e, "course": "BSIT", "student_number": "2023-9", "year_level": 2}
        self.juan = C.objects.create(respondent_type="student", data={"personal_info": info("Juan Cruz", "juan@ue.edu.ph"),
            "subjects": [{"code": "CCP 1101", "skills": [{"name": "Python", "level": "advanced"}]}]})
        self.maria = C.objects.create(respondent_type="alumni", data={"personal_info": info("Maria Santos", "maria@ue.edu.ph"),
            "subjects": [{"code": "CFD 1101", "skills": [{"name": "SQL", "level": "beginner"}]}]})
        self.dummy = C.objects.create(respondent_type="student", is_dummy=True,
            data={"personal_info": info("Test Kid", "t@ue.edu.ph"), "subjects": []})
        self.prof = C.objects.create(respondent_type="professor", user=self.faculty,
            data={"subjects": [{"code": "CCP 1101", "skills": [{"name": "Java", "level": "applied"}]}]})

    def test_admin_only(self):
        self.client.force_login(self.faculty)
        self.assertEqual(self.client.get(reverse("survey_responses")).status_code, 403)
        self.assertEqual(self.client.post(reverse("survey_responses_delete"), {"ids": [self.juan.pk]}).status_code, 403)

    def test_search_and_filters(self):
        self.client.force_login(self.admin)
        url = reverse("survey_responses")
        r = self.client.get(url)
        self.assertContains(r, "Juan Cruz")
        self.assertContains(r, "Maria Santos")
        self.assertContains(r, "fac@ue.edu.ph")          # professor shown by their account
        self.assertNotContains(r, "Test Kid")             # dummy answers hidden by default
        r = self.client.get(url, {"q": "sql"})
        self.assertContains(r, "Maria Santos")
        self.assertNotContains(r, "Juan Cruz")
        r = self.client.get(url, {"q": "juan@ue"})
        self.assertContains(r, "Juan Cruz")
        self.assertNotContains(r, "Maria Santos")
        r = self.client.get(url, {"type": "professor"})
        self.assertContains(r, "fac@ue.edu.ph")
        self.assertNotContains(r, "Juan Cruz")
        r = self.client.get(url, {"set": "dummy"})
        self.assertContains(r, "Test Kid")
        self.assertNotContains(r, "Juan Cruz")

    def test_delete_selected(self):
        from .models import CurriculumSurveyResponse as C
        self.client.force_login(self.admin)
        r = self.client.post(reverse("survey_responses_delete"),
                             {"ids": [self.juan.pk, self.maria.pk], "next": reverse("survey_responses") + "?q=x"})
        self.assertRedirects(r, reverse("survey_responses") + "?q=x", fetch_redirect_response=False)
        self.assertEqual(set(C.objects.values_list("pk", flat=True)), {self.dummy.pk, self.prof.pk})
        r = self.client.post(reverse("survey_responses_delete"), {"ids": [self.prof.pk], "next": "https://evil.example/"})
        self.assertRedirects(r, reverse("survey_responses"), fetch_redirect_response=False)


class DummyToggleTests(TestCase):
    def test_switching_an_account_to_dummy_moves_its_answers(self):
        from .models import CurriculumSurveyResponse as C
        admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                               last_name="D", role=CustomUser.Role.ADMINISTRATOR)
        stu = CustomUser.objects.create_user(email="me@ue.edu.ph", password="secret123", first_name="Pa",
                                             last_name="Eng", role=CustomUser.Role.STUDENT)
        old = C.objects.create(respondent_type="student", user=stu, data={"subjects": []})
        other = C.objects.create(respondent_type="student", data={"subjects": []})
        self.client.force_login(admin)
        fields = {"last_name": "Eng", "first_name": "Pa", "email": "me@ue.edu.ph"}
        r = self.client.post(reverse("account_edit", args=[stu.pk]), {**fields, "account_type": "dummy_student"}, follow=True)
        self.assertContains(r, "Role changed from Student to Dummy Student. 1 survey answer moved to dummy (test) data")
        stu.refresh_from_db(); old.refresh_from_db(); other.refresh_from_db()
        self.assertTrue(stu.is_dummy)
        self.assertTrue(old.is_dummy)
        self.assertFalse(other.is_dummy)
        # editing without touching the role keeps it
        self.client.post(reverse("account_edit", args=[stu.pk]), fields)
        stu.refresh_from_db()
        self.assertTrue(stu.is_dummy)
        # back to a real student moves them back
        self.client.post(reverse("account_edit", args=[stu.pk]), {**fields, "account_type": "student"})
        old.refresh_from_db()
        self.assertFalse(old.is_dummy)
        # an administrator can't change their own role
        r = self.client.post(reverse("account_edit", args=[admin.pk]),
                             {"last_name": "D", "first_name": "A", "email": "adm@ue.edu.ph", "account_type": "faculty"},
                             follow=True)
        self.assertContains(r, "change your own role")
        admin.refresh_from_db()
        self.assertEqual(admin.role, "administrator")

    def test_change_role_and_sort(self):
        admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                               last_name="Admin", role=CustomUser.Role.ADMINISTRATOR)
        fac = CustomUser.objects.create_user(email="zed@ue.edu.ph", password="secret123", first_name="Zed",
                                             last_name="Zamora", role=CustomUser.Role.FACULTY)
        self.client.force_login(admin)
        fields = {"last_name": "Zamora", "first_name": "Zed", "email": "zed@ue.edu.ph"}
        self.client.post(reverse("account_edit", args=[fac.pk]), {**fields, "account_type": "administrator"})
        fac.refresh_from_db()
        self.assertEqual((fac.role, fac.is_dummy), ("administrator", False))
        self.client.post(reverse("account_edit", args=[fac.pk]), {**fields, "account_type": "nonsense"})
        fac.refresh_from_db()
        self.assertEqual(fac.role, "administrator")
        self.client.post(reverse("account_edit", args=[fac.pk]), {**fields, "account_type": "dummy_faculty"})
        fac.refresh_from_db()
        self.assertEqual((fac.role, fac.is_dummy), ("faculty", True))

        page = lambda sort: self.client.get(reverse("accounts"), {"sort": sort}).content.decode()
        self.assertLess(page("name").index("adm@ue.edu.ph"), page("name").index("zed@ue.edu.ph"))
        self.assertLess(page("-name").index("zed@ue.edu.ph"), page("-name").index("adm@ue.edu.ph"))
        self.assertLess(page("-joined").index("zed@ue.edu.ph"), page("-joined").index("adm@ue.edu.ph"))


class ForgotPasswordTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = CustomUser.objects.create_user(email="Paeng@ue.edu.ph", password="oldpass123",
                                                   first_name="Pa", last_name="Eng")

    def test_reset_by_email_link(self):
        from django.core import mail
        r = self.client.post(reverse("forgot_password"), {"email": "paeng@UE.edu.ph"})   # any letter case
        self.assertContains(r, "emailed it a link to reset")
        self.assertEqual(mail.outbox[0].to, ["Paeng@ue.edu.ph"])
        link = mail.outbox[0].body.split("http://testserver", 1)[1].split()[0]
        self.assertContains(self.client.get(link), "Choose a new password")
        r = self.client.post(link, {"password": "short", "password2": "short"})
        self.assertContains(r, "at least 8")
        r = self.client.post(link, {"password": "newpass123", "password2": "newpass123"})
        self.assertContains(r, "Password changed")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("newpass123"))
        # the link only works once
        self.assertContains(self.client.get(link), "This link doesn")

    def test_unknown_email_gets_the_same_answer_and_no_email(self):
        from django.core import mail
        r = self.client.post(reverse("forgot_password"), {"email": "nobody@ue.edu.ph"})
        self.assertContains(r, "If <strong>nobody@ue.edu.ph</strong> has a UEnvision account")
        self.assertEqual(len(mail.outbox), 0)

    def test_rate_limited(self):
        from django.core import mail
        self.client.post(reverse("forgot_password"), {"email": "paeng@ue.edu.ph"})
        r = self.client.post(reverse("forgot_password"), {"email": "paeng@ue.edu.ph"})
        self.assertContains(r, "wait a minute")
        self.assertEqual(len(mail.outbox), 1)

    def test_old_reset_address_redirects(self):
        self.assertRedirects(self.client.get(reverse("reset_password")), reverse("forgot_password"))



class FacultyApprovalTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                                    last_name="Dmin", role=CustomUser.Role.ADMINISTRATOR)
        self.admin2 = CustomUser.objects.create_user(email="adm2@ue.edu.ph", password="secret123", first_name="B",
                                                     last_name="Dmin", role=CustomUser.Role.ADMINISTRATOR,
                                                     notify_by_email=True)

    def signup(self):
        return self.client.post(reverse("signup"), {"last_name": "Santos", "first_name": "Prof", "email": "prof@ue.edu.ph",
                                                    "password": "longenough1", "password2": "longenough1"})

    def test_bell_poll_returns_live_count_and_dropdown(self):
        self.client.force_login(self.admin)
        url = reverse("notifications_poll")
        first = self.client.get(url, {"page": "/accounts/"}, HTTP_X_BACKGROUND_REQUEST="1").json()
        self.assertEqual(first["unread"], 0)
        self.assertIn("No notifications yet", first["html"])
        self.client.logout()
        self.signup()                                   # a professor signs up while the admin's page is open
        self.client.force_login(self.admin)
        data = self.client.get(url, {"page": "/accounts/?q=x"}, HTTP_X_BACKGROUND_REQUEST="1").json()
        self.assertEqual(data["unread"], 1)
        self.assertIn("Prof Santos (prof@ue.edu.ph) signed up", data["html"])
        self.assertIn('name="next" value="/accounts/?q=x"', data["html"])   # Approve comes back to the same page
        evil = self.client.get(url, {"page": "https://evil.example/"}).json()
        self.assertNotIn("evil.example", evil["html"])
        # admins only
        prof = CustomUser.objects.get(email="prof@ue.edu.ph")
        prof.is_approved = True
        prof.save()
        self.client.force_login(prof)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_signup_can_use_app_right_away_and_admins_are_notified(self):
        from django.core import mail
        from .models import Notification
        r = self.signup()
        self.assertRedirects(r, reverse("dashboard"), fetch_redirect_response=False)
        prof = CustomUser.objects.get(email="prof@ue.edu.ph")
        self.assertFalse(prof.is_approved)
        self.assertTrue(prof.email_verified)
        # not blocked while waiting for approval
        self.assertEqual(self.client.get(reverse("data")).status_code, 200)
        self.assertRedirects(self.client.get(reverse("pending_approval")), reverse("dashboard"), fetch_redirect_response=False)
        # both admins get a notification; only the one who opted in gets an email
        self.assertEqual(Notification.objects.filter(subject_user=prof).count(), 2)
        self.assertEqual([m.to for m in mail.outbox], [["adm2@ue.edu.ph"]])
        self.assertIn("Prof Santos", mail.outbox[0].subject)

        self.client.force_login(self.admin)
        page = self.client.get(reverse("accounts"))
        self.assertContains(page, '<span class="notif-bell-count" id="notif-bell-count">1</span>', html=True)
        self.assertContains(page, "1 faculty sign-up</strong> not approved yet")
        self.assertContains(page, "Prof Santos (prof@ue.edu.ph) signed up")          # in the bell's dropdown
        self.assertEqual(self.client.post(reverse("notifications_read")).json(), {"ok": True})  # dropdown opened
        self.assertNotContains(self.client.get(reverse("accounts")), "notif-bell-count")
        self.assertContains(self.client.get(reverse("notifications")), "Prof Santos (prof@ue.edu.ph) signed up")

        sent = len(mail.outbox)
        self.client.post(reverse("account_approve", args=[prof.pk]))
        prof.refresh_from_db()
        self.assertTrue(prof.is_approved)
        self.assertEqual(len(mail.outbox), sent)  # they already use UEnvision, so no "approved" email
        self.assertFalse(Notification.objects.filter(subject_user=prof, read_at__isnull=True).exists())
        self.client.force_login(prof)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_removing_an_unapproved_signup_also_removes_their_answers(self):
        from .models import CurriculumSurveyResponse
        self.signup()
        prof = CustomUser.objects.get(email="prof@ue.edu.ph")
        CurriculumSurveyResponse.objects.create(respondent_type=CurriculumSurveyResponse.PROFESSOR, user=prof, data={})
        SurveyResponse.objects.create(survey_type=SurveyResponse.SUS, user=prof, data={})
        approved = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="secret123", first_name="F",
                                                  last_name="C", role=CustomUser.Role.FACULTY)
        kept = CurriculumSurveyResponse.objects.create(respondent_type=CurriculumSurveyResponse.PROFESSOR,
                                                       user=approved, data={})
        self.client.force_login(self.admin)
        self.assertContains(self.client.post(reverse("account_delete", args=[prof.pk]), follow=True),
                            "and its survey answers were removed")
        self.assertFalse(CustomUser.objects.filter(email="prof@ue.edu.ph").exists())
        self.assertFalse(CurriculumSurveyResponse.objects.exclude(pk=kept.pk).exists())
        self.assertEqual(SurveyResponse.objects.count(), 0)
        # an approved account's answers are kept (unlinked) as before
        self.client.post(reverse("account_delete", args=[approved.pk]))
        kept.refresh_from_db()
        self.assertIsNone(kept.user)

    def test_admin_made_and_student_accounts_need_no_approval(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("account_create"), {"last_name": "F", "first_name": "G", "email": "f@ue.edu.ph",
                                                     "role": "faculty", "password": "secret123"})
        self.assertTrue(CustomUser.objects.get(email="f@ue.edu.ph").is_approved)

    def test_only_admins_approve(self):
        self.signup()
        prof = CustomUser.objects.get(email="prof@ue.edu.ph")
        other = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="secret123", first_name="F",
                                               last_name="C", role=CustomUser.Role.FACULTY)
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse("account_approve", args=[prof.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("notifications")).status_code, 403)
        prof.refresh_from_db()
        self.assertFalse(prof.is_approved)

    def test_email_alert_setting(self):
        self.assertFalse(self.admin.notify_by_email)          # off by default
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("settings")), "Email me when a faculty member signs up")
        self.client.post(reverse("notification_settings"), {"notify_by_email": "1"})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.notify_by_email)
        self.client.post(reverse("notification_settings"), {})
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.notify_by_email)

    def test_accounts_search_and_filter(self):
        self.signup()
        CustomUser.objects.create_user(email="juan@ue.edu.ph", password="secret123", first_name="Juan",
                                       last_name="Cruz", role=CustomUser.Role.STUDENT)
        self.client.force_login(self.admin)
        url = reverse("accounts")

        def table(**params):  # just the accounts table (the bell's dropdown also names the sign-up)
            html = self.client.get(url, params).content.decode()
            start = html.index('id="accounts-table"')
            return html[start:html.index("</table>", start)]

        self.assertIn("juan@ue.edu.ph", table(q="cruz"))
        self.assertNotIn("prof@ue.edu.ph", table(q="cruz"))
        self.assertIn("prof@ue.edu.ph", table(status="pending"))
        self.assertNotIn("juan@ue.edu.ph", table(status="pending"))
        self.assertIn("juan@ue.edu.ph", table(status="student"))
        self.assertNotIn("adm2@ue.edu.ph", table(status="student"))
        self.assertIn("No accounts match", table(q="nobody-here"))


class DeveloperRoleTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                                    last_name="Dmin", role=CustomUser.Role.ADMINISTRATOR)

    def test_developer_is_an_admin_whose_survey_answers_are_dummy(self):
        from . import gap_analysis
        self.client.force_login(self.admin)
        self.client.post(reverse("account_create"), {"last_name": "Dev", "first_name": "Paeng", "email": "dev@ue.edu.ph",
                                                     "role": "developer", "password": "longenough1"})
        dev = CustomUser.objects.get(email="dev@ue.edu.ph")
        self.assertEqual(dev.role_label, "Developer")
        self.assertTrue(dev.is_administrator)
        self.assertFalse(dev.is_dummy)

        self.client.force_login(dev)
        # every admin page, the real dashboard and the bell
        for name in ("accounts", "data_import", "survey_responses", "console"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, 'id="notif-bell"')
        self.assertContains(self.client.get(reverse("professor_survey")), "Developer account:")
        # their professor survey goes to the dummy data set only
        self.client.post(reverse("professor_survey_submit"), content_type="application/json", data=json.dumps(
            {"consent": True, "subjects": [{"code": "CCP 1101", "skills": [{"name": "SQL", "level": "applied"}]}]}))
        self.assertTrue(dev.curriculum_survey_responses.get().is_dummy)
        self.assertEqual(gap_analysis._academic_responses()[1]["professor"], 0)
        self.assertEqual(gap_analysis._academic_responses(dummy=True)[1]["professor"], 1)

    def test_switching_to_and_from_developer_moves_answers(self):
        from .models import CurriculumSurveyResponse as C
        fac = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="secret123", first_name="F",
                                             last_name="Ac", role=CustomUser.Role.FACULTY)
        answer = C.objects.create(respondent_type="professor", user=fac, data={"subjects": []})
        self.client.force_login(self.admin)
        fields = {"last_name": "Ac", "first_name": "F", "email": "fac@ue.edu.ph"}
        r = self.client.post(reverse("account_edit", args=[fac.pk]), {**fields, "account_type": "developer"}, follow=True)
        self.assertContains(r, "Role changed from Faculty to Developer. 1 survey answer moved to dummy (test) data")
        answer.refresh_from_db()
        self.assertTrue(answer.is_dummy)
        # Developer -> Dummy Faculty: still dummy, nothing moves
        r = self.client.post(reverse("account_edit", args=[fac.pk]), {**fields, "account_type": "dummy_faculty"}, follow=True)
        self.assertNotContains(r, "moved")
        answer.refresh_from_db()
        self.assertTrue(answer.is_dummy)
        self.client.post(reverse("account_edit", args=[fac.pk]), {**fields, "account_type": "administrator"})
        answer.refresh_from_db()
        self.assertFalse(answer.is_dummy)
        # Developers show up under their own filter and get sign-up notifications
        CustomUser.objects.filter(pk=fac.pk).update(role=CustomUser.Role.DEVELOPER)
        r = self.client.get(reverse("accounts"), {"status": "developer"})
        self.assertContains(r, "fac@ue.edu.ph")
        from . import notifications
        self.assertIn(fac, list(notifications._admins()))

    def test_developer_can_switch_between_real_and_dummy_results(self):
        from unittest import mock
        dev = CustomUser.objects.create_user(email="dev@ue.edu.ph", password="secret123", first_name="D",
                                             last_name="Ev", role=CustomUser.Role.DEVELOPER)
        self.client.force_login(dev)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, 'value="real" class="results-switch-btn is-active"')
        with mock.patch("myapp.views.gap_analysis.compute", return_value={"exists": False}) as compute:
            self.client.get(reverse("recommendations"))
            self.assertEqual(compute.call_args.kwargs["dummy"], False)
            r = self.client.post(reverse("developer_results"), {"results": "dummy", "next": "/recommendations/"})
            self.assertRedirects(r, "/recommendations/", fetch_redirect_response=False)
            self.assertContains(self.client.get(reverse("recommendations")),
                                'value="dummy" class="results-switch-btn is-active"')
            self.assertEqual(compute.call_args.kwargs["dummy"], True)
            self.client.post(reverse("developer_results"), {"results": "real"})
            self.client.get(reverse("recommendations"))
            self.assertEqual(compute.call_args.kwargs["dummy"], False)
        # only developers get the switch
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse("dashboard")), "results-switch")
        self.assertEqual(self.client.post(reverse("developer_results"), {"results": "dummy"}).status_code, 403)


def _temporary_password(response):
    """The temporary password from the success message after Create account / Reset password."""
    for m in get_messages(response.wsgi_request):
        found = re.search(r"Temporary password: (\S+)", str(m))
        if found:
            return found.group(1)
    raise AssertionError("no temporary password in the messages")


class TemporaryPasswordTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            "temp@ue.edu.ph", "Tmp4Xk9pQ2wz", first_name="Tem", last_name="Porary", must_change_password=True)

    def login(self):
        return self.client.post(reverse("login"), {"email": "temp@ue.edu.ph", "password": "Tmp4Xk9pQ2wz"})

    def test_login_goes_to_settings_and_other_pages_are_blocked(self):
        self.assertRedirects(self.login(), reverse("settings"))
        self.assertContains(self.client.get(reverse("settings")), "temporary password")
        for name in ("dashboard", "recommendations", "data", "professor_survey"):
            self.assertRedirects(self.client.get(reverse(name)), reverse("settings"), msg_prefix=name)
        resp = self.client.get(reverse("dashboard_skills"), HTTP_ACCEPT="application/json")
        self.assertEqual(resp.status_code, 403)

    def test_changing_password_lifts_the_block(self):
        self.login()
        resp = self.client.post(reverse("change_password"), {
            "current_password": "Tmp4Xk9pQ2wz", "new_password": "my-own-pass-1", "confirm_password": "my-own-pass-1"})
        self.assertRedirects(resp, reverse("dashboard"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.must_change_password)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_learner_with_temporary_password(self):
        self.user.role = CustomUser.Role.STUDENT
        self.user.save()
        self.assertRedirects(self.login(), reverse("settings"))
        self.assertRedirects(self.client.get(reverse("student_dashboard")), reverse("settings"))

    def test_forgot_password_reset_clears_it(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        url = reverse("reset_password_confirm", args=[uid, default_token_generator.make_token(self.user)])
        self.client.post(url, {"password": "brand-new-pass", "password2": "brand-new-pass"})
        self.user.refresh_from_db()
        self.assertFalse(self.user.must_change_password)

    def test_login_page_has_no_demo_account(self):
        with self.settings(DEBUG=True):
            self.assertNotContains(self.client.get(reverse("login")), "rizal123")


class SharedPasswordMigrationTests(TestCase):
    def test_flags_accounts_still_using_an_old_shared_password(self):
        import importlib

        from django.apps import apps

        migration = importlib.import_module("myapp.migrations.0010_must_change_password")
        old = CustomUser.objects.create_user("old@ue.edu.ph", "default123", first_name="O", last_name="Ld")
        demo = CustomUser.objects.create_user("demo@ue.edu.ph", "rizal123", first_name="D", last_name="Emo")
        fine = CustomUser.objects.create_user("fine@ue.edu.ph", "something-else-9", first_name="F", last_name="Ine")
        migration.flag_shared_passwords(apps, None)
        flags = dict(CustomUser.objects.values_list("email", "must_change_password"))
        self.assertEqual(flags, {old.email: True, demo.email: True, fine.email: False})


class LoginLimitTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            "limit@ue.edu.ph", "right-password1", first_name="Li", last_name="Mit")

    def attempt(self, email="limit@ue.edu.ph", password="wrong-password", ip="10.0.0.1"):
        return self.client.post(reverse("login"), {"email": email, "password": password}, REMOTE_ADDR=ip)

    def test_five_wrong_passwords_pause_that_email(self):
        for _ in range(5):
            self.assertEqual(self.attempt().status_code, 200)
        resp = self.attempt(password="right-password1")
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, "Too many login attempts. Try again in 15 minutes", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)
        # from another computer too (it's the account that is paused)
        self.assertEqual(self.attempt(password="right-password1", ip="10.0.0.2").status_code, 429)
        # other accounts are fine
        CustomUser.objects.create_user("other@ue.edu.ph", "other-password1", first_name="O", last_name="T")
        self.assertRedirects(self.attempt("other@ue.edu.ph", "other-password1"), reverse("dashboard"))

    def test_pause_ends_after_the_window(self):
        from unittest import mock

        from . import login_limits

        for _ in range(5):
            self.attempt()
        later = login_limits.time.time() + login_limits.WINDOW_SECONDS + 1
        with mock.patch.object(login_limits.time, "time", return_value=later):
            self.assertRedirects(self.attempt(password="right-password1"), reverse("dashboard"))

    def test_successful_login_resets_the_count(self):
        for _ in range(4):
            self.attempt()
        self.assertRedirects(self.attempt(password="right-password1"), reverse("dashboard"))
        self.client.logout()
        for _ in range(4):
            self.assertEqual(self.attempt().status_code, 200)

    def test_same_message_for_emails_without_an_account(self):
        for _ in range(5):
            self.attempt("nobody@ue.edu.ph")
        self.assertContains(self.attempt("nobody@ue.edu.ph"), "Too many login attempts", status_code=429)

    def test_twenty_failures_from_one_computer_pause_it(self):
        for i in range(20):
            self.attempt(f"guess{i}@ue.edu.ph")
        self.assertEqual(self.attempt(password="right-password1").status_code, 429)
        self.assertRedirects(self.attempt(password="right-password1", ip="10.0.0.9"), reverse("dashboard"))

    def test_nginx_real_ip_header_is_used(self):
        for i in range(20):
            self.client.post(reverse("login"), {"email": f"g{i}@ue.edu.ph", "password": "x"},
                             REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="203.0.113.5")
        blocked = self.client.post(reverse("login"), {"email": "limit@ue.edu.ph", "password": "right-password1"},
                                   REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="203.0.113.5")
        self.assertEqual(blocked.status_code, 429)
        ok = self.client.post(reverse("login"), {"email": "limit@ue.edu.ph", "password": "right-password1"},
                              REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="203.0.113.6")
        self.assertRedirects(ok, reverse("dashboard"))

    def test_password_reset_link_lifts_the_pause(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        for _ in range(5):
            self.attempt()
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        url = reverse("reset_password_confirm", args=[uid, default_token_generator.make_token(self.user)])
        self.client.post(url, {"password": "brand-new-pass", "password2": "brand-new-pass"})
        self.assertRedirects(self.attempt(password="brand-new-pass"), reverse("dashboard"))

    def test_admin_login_goes_through_the_limited_login_page(self):
        resp = self.client.get("/admin/login/?next=/admin/")
        self.assertRedirects(resp, reverse("login") + "?next=%2Fadmin%2F", fetch_redirect_response=False)
        self.assertRedirects(self.client.get("/admin/"), "/admin/login/?next=/admin/", fetch_redirect_response=False)


class TemporaryPasswordEmailTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            "admin@ue.edu.ph", "adminpass1", first_name="Ada", last_name="Min", role=CustomUser.Role.ADMINISTRATOR)
        self.faculty = CustomUser.objects.create_user("fac@ue.edu.ph", "facpass123", first_name="Fay", last_name="Culty")
        self.client.force_login(self.admin)

    @override_settings(EMAIL_HOST="smtp.example.com", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_reset_emails_the_temporary_password_and_hides_it_from_the_admin(self):
        from django.core import mail

        resp = self.client.post(reverse("account_reset_password", args=[self.faculty.pk]))
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["fac@ue.edu.ph"])
        password = re.search(r"Temporary password: (\S+)", sent.body).group(1)
        self.faculty.refresh_from_db()
        self.assertTrue(self.faculty.check_password(password))
        self.assertIn(reverse("login"), sent.body)
        shown = " ".join(str(m) for m in get_messages(resp.wsgi_request))
        self.assertIn("emailed", shown)
        self.assertNotIn(password, shown)

    @override_settings(EMAIL_HOST="smtp.example.com", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_new_account_with_blank_password_gets_an_email(self):
        from django.core import mail

        self.client.post(reverse("account_create"), {"last_name": "Cruz", "first_name": "Juan",
                                                     "email": "juan@ue.edu.ph", "role": "faculty"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("created a UEnvision account", mail.outbox[0].body)
        password = re.search(r"Temporary password: (\S+)", mail.outbox[0].body).group(1)
        self.assertTrue(CustomUser.objects.get(email="juan@ue.edu.ph").check_password(password))
        # a password the administrator typed isn't emailed
        self.client.post(reverse("account_create"), {"last_name": "Cruz", "first_name": "Ana", "email": "ana@ue.edu.ph",
                                                     "role": "faculty", "password": "typed-pass-1"})
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_HOST="smtp.example.com")
    def test_admin_sees_the_password_when_the_email_fails(self):
        from unittest import mock

        with mock.patch("myapp.notifications.send_mail", side_effect=OSError("smtp down")):
            resp = self.client.post(reverse("account_reset_password", args=[self.faculty.pk]))
        password = _temporary_password(resp)
        self.faculty.refresh_from_db()
        self.assertTrue(self.faculty.check_password(password))


class HelpPageTests(TestCase):
    def page_for(self, role, **extra):
        user = CustomUser.objects.create_user(email=f"{role}@ue.edu.ph", password="x" * 12, first_name="A",
                                              last_name="B", role=role, **extra)
        self.client.force_login(user)
        return self.client.get(reverse("help"))

    def test_each_role_sees_its_own_steps(self):
        r = self.page_for("student")
        self.assertEqual(r.status_code, 200)  # students may open it
        self.assertContains(r, "Students and alumni")
        self.assertNotContains(r, "Administrators</h2>")
        r = self.page_for("faculty")
        self.assertContains(r, "Faculty</h2>")
        self.assertNotContains(r, "Students and alumni")
        r = self.page_for("administrator")
        self.assertContains(r, "Administrators</h2>")
        r = self.page_for("developer")
        for title in ("Students and alumni", "Faculty</h2>", "Administrators</h2>"):
            self.assertContains(r, title)

    def test_linked_from_the_sidebar(self):
        r = self.page_for("faculty")
        self.assertContains(r, f'href="{reverse("help")}"')


@override_settings(REQUIRE_PROFESSOR_SURVEY=True)
class ProfessorSurveyFirstTests(IsolatedDataMixin, TestCase):
    def make(self, role="faculty", email="prof@ue.edu.ph"):
        return CustomUser.objects.create_user(email=email, password="x" * 12, first_name="Prof",
                                              last_name="Cruz", role=role)

    def submit(self):
        return self.client.post(reverse("professor_survey_submit"), content_type="application/json", data=json.dumps(
            {"consent": True, "subjects": [{"code": "CCP 1101", "skills": [{"name": "Python", "level": "applied"}]}]}))

    def test_new_faculty_answer_the_survey_before_anything_else(self):
        self.client.force_login(self.make())
        for name in ("dashboard", "recommendations", "data", "feedback"):
            r = self.client.get(reverse(name))
            self.assertRedirects(r, reverse("professor_survey") + "?first=1", fetch_redirect_response=False)
        page = self.client.get(reverse("professor_survey"))
        self.assertContains(page, "Please answer this survey once before using the rest of the site")
        self.assertEqual(self.client.get(reverse("settings")).status_code, 200)   # account basics still open
        r = self.submit()
        self.assertEqual(r.json()["next_url"], reverse("dashboard"))
        dash = self.client.get(reverse("dashboard"))
        self.assertEqual(dash.status_code, 200)
        self.assertContains(dash, "Edit your data")

    def test_administrators_and_developers_are_not_held(self):
        for i, role in enumerate(("administrator", "developer")):
            self.client.force_login(self.make(role, f"staff{i}@ue.edu.ph"))
            r = self.client.get(reverse("dashboard"))
            self.assertEqual(r.status_code, 200)
            self.assertNotContains(r, "Edit your data")   # no record yet, so nothing to edit


class FeedbackNudgeTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="x" * 12,
                                                   first_name="Ana", last_name="Reyes")
        self.client.force_login(self.user)

    def test_banner_shows_after_a_few_uses_until_answered(self):
        from .feedback_nudge import USES_BEFORE_ASKING
        for _ in range(USES_BEFORE_ASKING - 1):
            self.client.get(reverse("dashboard"))
        self.assertNotContains(self.client.get(reverse("about")), "Help us evaluate UEnvision")
        self.client.get(reverse("dashboard"))
        page = self.client.get(reverse("about"))
        self.assertContains(page, "Help us evaluate UEnvision")
        self.assertContains(page, "SUS evaluation, UAT survey and test case sheet")
        self.assertContains(page, reverse("feedback") + "?survey=sus")
        self.assertNotContains(self.client.get(reverse("feedback")), "Help us evaluate UEnvision")
        for kind in ("sus", "uat", "functional"):
            SurveyResponse.objects.create(survey_type=kind, user=self.user, data={})
        self.assertNotContains(self.client.get(reverse("about")), "Help us evaluate UEnvision")

    def test_later_hides_it_for_a_few_days(self):
        CustomUser.objects.filter(pk=self.user.pk).update(app_uses=10)
        r = self.client.post(reverse("feedback_later"), {"next": reverse("about")})
        self.assertRedirects(r, reverse("about"))
        self.assertNotContains(self.client.get(reverse("about")), "Help us evaluate UEnvision")
        CustomUser.objects.filter(pk=self.user.pk).update(feedback_snoozed_until=None)
        self.assertContains(self.client.get(reverse("about")), "Help us evaluate UEnvision")

    def test_students_are_only_asked_for_the_sus(self):
        from .feedback_nudge import missing_surveys
        student = CustomUser.objects.create_user(email="stu@ue.edu.ph", password="x" * 12, first_name="S",
                                                 last_name="T", role="student")
        self.assertEqual([k for k, _ in missing_surveys(student)], ["sus"])


class SurveyTrackerTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        mk = lambda email, role: CustomUser.objects.create_user(email=email, password="x" * 12, first_name=email[:3],
                                                                 last_name="L", role=role)
        self.dev = mk("dev@ue.edu.ph", "developer")
        self.fac = mk("fac@ue.edu.ph", "faculty")
        self.stu = mk("stu@ue.edu.ph", "student")
        self.admin = mk("adm@ue.edu.ph", "administrator")

    def test_developers_only(self):
        for u in (self.admin, self.fac):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("survey_tracker")).status_code, 403)
        self.client.force_login(self.dev)
        page = self.client.get(reverse("data"))
        self.assertContains(page, reverse("survey_tracker"))

    def test_shows_who_is_missing_and_sends_one_reminder_a_day(self):
        from django.core import mail
        from .models import CurriculumSurveyResponse
        SurveyResponse.objects.create(survey_type="sus", user=self.stu, data={})
        CurriculumSurveyResponse.objects.create(respondent_type="student", user=self.stu, data={})
        self.client.force_login(self.dev)
        page = self.client.get(reverse("survey_tracker"))
        self.assertNotContains(page, "stu@ue.edu.ph")      # answered everything a student is asked
        self.assertContains(page, "fac@ue.edu.ph")
        self.assertContains(self.client.get(reverse("survey_tracker"), {"show": "all"}), "stu@ue.edu.ph")
        r = self.client.post(reverse("survey_tracker_remind"), {"ids": [self.fac.pk, self.stu.pk]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual([m.to for m in mail.outbox], [["fac@ue.edu.ph"]])
        self.assertIn("the SUS evaluation", mail.outbox[0].body)
        self.client.post(reverse("survey_tracker_remind"), {"ids": [self.fac.pk]})
        self.assertEqual(len(mail.outbox), 1)              # not twice in a day


class PrivacyConsentTests(TestCase):
    def test_consent_checkbox_is_at_the_top_and_above_submit(self):
        for name, main in (("student_survey", "student-consent"), ("alumni_survey", "alumni-consent")):
            page = self.client.get(reverse(name))
            self.assertContains(page, f'id="{main}"')
            self.assertContains(page, f'data-mirror="{main}"')
        prof = CustomUser.objects.create_user(email="p@ue.edu.ph", password="x" * 12, first_name="P", last_name="Q")
        self.client.force_login(prof)
        page = self.client.get(reverse("professor_survey"))
        self.assertContains(page, 'id="professor-consent"')
        self.assertContains(page, 'data-mirror="professor-consent"')


class DeleteDataFileTests(IsolatedDataMixin, TestCase):
    """Data > View Data: administrators can delete some CSVs, never the raw scraped job postings."""

    def setUp(self):
        super().setUp()
        from pathlib import Path
        from django.conf import settings
        self.dir = Path(settings.DATA_DIR)
        (self.dir / ".state").mkdir(exist_ok=True)
        for name in ("compiled_kalibrr.csv", "hard_skills.csv", "soft_skills.csv", ".state/extracted_skills.json"):
            (self.dir / name).write_text("x\n", encoding="utf-8")
        self.admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                                    last_name="D", role=CustomUser.Role.ADMINISTRATOR)

    def test_delete_extracted_also_removes_what_is_built_from_it(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("data"))
        self.assertContains(page, 'id="delete-file-form"')
        self.assertContains(page, "data-delete-note=")
        r = self.client.post(reverse("data_delete", args=["extracted"]), follow=True)
        self.assertContains(r, "Deleted Extracted Skills.")
        for name in ("extracted_skills.csv", "hard_skills.csv", "soft_skills.csv", ".state/extracted_skills.json"):
            self.assertFalse((self.dir / name).exists(), name)
        self.assertTrue((self.dir / "compiled_kalibrr.csv").exists())

    def test_raw_job_postings_and_derived_files_cannot_be_deleted(self):
        self.client.force_login(self.admin)
        for key in ("kalibrr", "trabajo", "hard_skills", "soft_skills"):
            r = self.client.post(reverse("data_delete", args=[key]), follow=True)
            self.assertContains(r, "can&#x27;t be deleted here")
        self.assertTrue((self.dir / "compiled_kalibrr.csv").exists())
        self.assertTrue((self.dir / "hard_skills.csv").exists())

    def test_only_administrators_and_only_post(self):
        fac = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="secret123", first_name="F",
                                             last_name="C", role=CustomUser.Role.FACULTY)
        self.client.force_login(fac)
        self.assertEqual(self.client.post(reverse("data_delete", args=["extracted"])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("data")), 'id="delete-file-form"')
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("data_delete", args=["extracted"])).status_code, 405)
        self.assertTrue((self.dir / "extracted_skills.csv").exists())


class ExtractionColumnsTests(TestCase):
    def test_extracted_csv_has_the_tech_job_columns(self):
        from .pipeline.skills_schema import JOB_FLAG_COLUMNS, UNIVERSAL_COLUMNS, normalize_record
        for col in ("COMPUTER SCIENCE", "INFORMATION TECHNOLOGY", "isTechJob"):
            self.assertIn(col, UNIVERSAL_COLUMNS)
        self.assertEqual(set(JOB_FLAG_COLUMNS.values()), {"COMPUTER SCIENCE", "INFORMATION TECHNOLOGY", "isTechJob"})
        rec = normalize_record({"job_id": "1", "job_title": "Dev", "isTechJob": True})
        self.assertIs(rec["isTechJob"], True)
        self.assertIsNone(rec["COMPUTER SCIENCE"])   # blank until Gemini answers


class TechJobColumnsTests(IsolatedDataMixin, TestCase):
    """Homepage + Dashboard count postings by isTechJob, and narrow BSCS / BSIT by the
    COMPUTER SCIENCE / INFORMATION TECHNOLOGY columns."""

    def setUp(self):
        super().setUp()
        import csv
        from django.conf import settings
        rows = [
            # job_name, function, hard_skills, CS, IT, isTechJob
            ("ML Engineer", "", "Python; TensorFlow", "True", "False", "True"),
            ("Network Administrator", "", "Cisco; Linux", "False", "True", "True"),
            ("Full Stack Developer", "", "JavaScript; Python", "True", "True", "True"),
            ("Accountant", "IT and Software", "Excel", "False", "False", "False"),   # IT function, but not tech
            ("Talent Wrangler", "", "Kubernetes", "False", "True", "True"),         # no role group, still counted
            ("Software Developer", "", "Java", "", "", ""),                         # not answered yet: old rules
        ]
        with open(settings.DATA_DIR / "extracted_skills.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["job_id", "job_name", "source", "function", "date", "hard_skills", "soft_skills",
                        "experience_level", "COMPUTER SCIENCE", "INFORMATION TECHNOLOGY", "isTechJob"])
            for i, (name, fn, hard, cs, it, tech) in enumerate(rows):
                w.writerow([i, name, "kalibrr", fn, "2026-01-05", hard, "Teamwork", "Entry", cs, it, tech])

    def test_only_tech_jobs_count_and_programs_narrow_them(self):
        from . import job_roles
        names = lambda prog="": sorted(p["role"] or "-" for p in job_roles.it_postings(program=prog))
        self.assertEqual(len(job_roles.it_postings()), 5)          # the accountant is left out
        self.assertEqual(len(job_roles.it_postings(program="BSCS")), 3)   # ML, full stack, unanswered
        self.assertEqual(len(job_roles.it_postings(program="BSIT")), 4)   # network, full stack, wrangler, unanswered
        self.assertIn("-", names())                                 # tech job without a role group still counts

    def test_homepage_program_picker(self):
        page = self.client.get(reverse("home"), {"program": "BSIT"})
        self.assertContains(page, '<option value="BSIT" selected>Information Technology</option>', html=True)
        self.assertContains(page, "Top skills across all Information Technology jobs")
        self.assertContains(page, "According to 4 Information Technology job postings")
        self.assertContains(self.client.get(reverse("home")), "According to 5 IT/CS job postings")
        self.assertEqual(self.client.get(reverse("role_skills"), {"program": "BSCS"}).json()["overall"]["postings"], 3)

    def test_dashboard_program_filter(self):
        admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                               last_name="D", role=CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(admin)
        url = reverse("dashboard_skills")
        self.assertEqual(self.client.get(url).json()["stats"]["postings"], 5)
        cs = self.client.get(url, {"program": "BSCS"}).json()
        self.assertEqual(cs["stats"]["postings"], 3)
        self.assertNotIn("Cisco", [b["skill"] for b in cs["bars"]])
        self.assertEqual(cs["gap"]["postings_considered"], 3)

    def test_dashboard_bars_split_by_source(self):
        import csv
        from django.conf import settings
        path = settings.DATA_DIR / "extracted_skills.csv"
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        rows[2][2] = rows[5][2] = "trabajo"     # network admin + talent wrangler come from Trabajo
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
        from .pipeline import manager as pipeline
        dash = pipeline.skills_dashboard("hard", 10)
        self.assertEqual(dash["bar_sources"], ["kalibrr", "trabajo"])
        bars = {b["skill"]: b for b in dash["bars"]}
        self.assertEqual(bars["Python"]["by_source"], [{"source": "kalibrr", "count": 2}])
        self.assertEqual(bars["Cisco"]["by_source"], [{"source": "trabajo", "count": 1}])
        for b in dash["bars"]:
            self.assertEqual(sum(p["count"] for p in b["by_source"]), b["count"])
        only = pipeline.skills_dashboard("hard", 10, source="trabajo")
        self.assertEqual(only["bar_sources"], ["trabajo"])


class TrabajoDedupeTests(TestCase):
    """Trabajo repeats one ad per city / feed under new job_ids; only Trabajo data is merged."""
    DESC = ("We are hiring a ServiceNow developer to design configure and build workflow automation "
            "on the ServiceNow platform with a focus on customer service management and integrations")

    def _row(self, jid, city, posted, company="ATOS Information Technology Inc.", desc=None, title="ServiceNow Dev"):
        return {"job_id": jid, "job_title": title, "company_name": company, "city": city,
                "date_posted": posted, "description": desc if desc is not None else self.DESC}

    def test_exact_and_near_copies_merge_into_the_earliest(self):
        from .pipeline.dedupe_trabajo import dedupe_rows
        reworded = self.DESC + " apply now"
        rows = [self._row("a", "Pasig", "2026-10-28T10:00:00+01:00"),
                self._row("b", "Cebu City", "2026-10-27T10:00:00+01:00", company="Atos Information Technology"),
                self._row("c", "Pasig", "2026-10-28T11:00:00+01:00", desc=reworded, title="ServiceNow Developer"),
                self._row("d", "Taguig", "2026-10-28T10:00:00+01:00", company="Another Company"),
                self._row("e", "Manila", "", desc="")]
        kept, stats = dedupe_rows(rows)
        self.assertEqual([r["job_id"] for r in kept], ["b", "d", "e"])
        self.assertEqual(stats["removed"], 2)
        self.assertEqual(kept[0]["duplicate_count"], 2)
        self.assertEqual(kept[0]["merged_job_ids"], "a; c")
        self.assertEqual(kept[0]["other_locations"], "Pasig")
        self.assertEqual(kept[1]["duplicate_count"], 0)       # another company's identical ad stays

    def test_merging_again_keeps_the_earlier_merges(self):
        from .pipeline.dedupe_trabajo import dedupe_rows, merged_job_ids
        first, _ = dedupe_rows([self._row("a", "Pasig", "2026-10-28T10:00:00+01:00"),
                                self._row("b", "Cebu City", "2026-10-28T12:00:00+01:00")])
        again, stats = dedupe_rows(first + [self._row("c", "Makati", "2026-10-20T10:00:00+01:00")])
        self.assertEqual([r["job_id"] for r in again], ["c"])
        self.assertEqual(merged_job_ids(again), {"a", "b"})
        self.assertEqual(again[0]["other_locations"], "Pasig; Cebu City")

    def test_compile_merges_trabajo_but_not_kalibrr(self):
        import csv, tempfile
        from pathlib import Path
        from .pipeline import compile_jobs_to_csv as cj
        tmp = Path(tempfile.mkdtemp())
        for i, city in enumerate(["Pasig", "Cebu City", "Taguig"]):
            (tmp / f"job-{i}.json").write_text(json.dumps({
                "job_id": f"1943-{i}", "title": "ServiceNow Dev", "description_text": self.DESC,
                "company": {"name": "ATOS"}, "location": {"locality": city},
                "date_posted": f"2026-10-2{i}T10:00:00+01:00"}), encoding="utf-8")
        cj.compile_to_csv("trabajo", tmp, tmp / "out.csv")
        with open(tmp / "out.csv", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["job_id"], "1943-0")
        self.assertEqual(rows[0]["merged_job_ids"], "1943-1; 1943-2")
        self.assertNotIn("merged_job_ids", cj.KALIBRR_FIELDNAMES)

    def test_import_merges_trabajo_csv_only(self):
        import csv, io, tempfile
        from pathlib import Path
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .pipeline import manager

        def upload():
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=["job_id", "job_title", "company_name", "city", "description"])
            w.writeheader()
            for jid, city in (("1", "Pasig"), ("2", "Cebu City"), ("3", "Taguig")):
                w.writerow({"job_id": jid, "job_title": "Dev", "company_name": "ATOS", "city": city,
                            "description": self.DESC})
            return SimpleUploadedFile("jobs.csv", buf.getvalue().encode("utf-8"), content_type="text/csv")

        with override_settings(DATA_DIR=Path(tempfile.mkdtemp())):
            res = manager.import_csv("trabajo", upload(), merge=True)
            self.assertEqual((res["added"], res["merged"], res["total"]), (1, 2, 1))
            res = manager.import_csv("kalibrr", upload(), merge=True)
            self.assertEqual((res["added"], res["merged"], res["total"]), (3, 0, 3))


class ViewDataSortFilterClearTests(IsolatedDataMixin, TestCase):
    """View Data: per-column sort / filter, and clearing one job source from Extracted Skills."""

    def setUp(self):
        super().setUp()
        import csv
        from pathlib import Path
        from django.conf import settings
        from .pipeline import manager
        self.manager = manager
        self.dir = Path(settings.DATA_DIR)
        (self.dir / ".state").mkdir(exist_ok=True)
        rows = [("k1", "Data Analyst", "kalibrr", "SQL; Excel", "10"),
                ("t1", "Web Developer", "trabajo", "JavaScript", "9"),
                ("k2", "Network Engineer", "kalibrr", "Cisco", "100"),
                ("t2", "QA Tester", "trabajo", "Selenium", "")]
        with open(self.dir / "extracted_skills.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["job_id", "job_name", "source", "hard_skills", "salary"])
            w.writerows(rows)
        (self.dir / ".state" / "extracted_skills.json").write_text(json.dumps(
            [{"job_id": r[0], "job_name": r[1], "source": r[2], "hard_skills": r[3].split("; ")} for r in rows]),
            encoding="utf-8")
        manager._table_cache.clear()
        self.admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                                    last_name="D", role=CustomUser.Role.ADMINISTRATOR)

    def ids(self, **params):
        self.client.force_login(self.admin)
        d = self.client.get(reverse("data_table"), {"source": "extracted", **params}).json()
        return [r[0] for r in d["rows"]]

    def test_sort_numbers_as_numbers_and_blanks_last(self):
        self.assertEqual(self.ids(sort=4, dir="asc"), ["t1", "k1", "k2", "t2"])
        self.assertEqual(self.ids(sort=4, dir="desc"), ["k2", "k1", "t1", "t2"])
        self.assertEqual(self.ids(sort=1, dir="asc"), ["k1", "k2", "t2", "t1"])

    def test_filter_by_column(self):
        self.assertEqual(self.ids(f2="TRABAJO"), ["t1", "t2"])
        self.assertEqual(self.ids(f2="kalibrr", f3="cisco"), ["k2"])
        self.assertEqual(self.ids(f2="kalibrr", sort=0, dir="desc"), ["k2", "k1"])
        self.assertEqual(self.ids(f9="ignored"), ["k1", "t1", "k2", "t2"])   # unknown column

    def test_clear_one_source_keeps_the_other_and_rebuilds_skills(self):
        import csv
        self.client.force_login(self.admin)
        page = self.client.get(reverse("data"))
        self.assertContains(page, 'data-clear-source="trabajo"')
        r = self.client.post(reverse("data_clear_source", args=["trabajo"]), follow=True)
        self.assertContains(r, "Cleared 2 Trabajo job posting(s)")
        self.assertEqual(self.ids(), ["k1", "k2"])
        state = json.loads((self.dir / ".state" / "extracted_skills.json").read_text(encoding="utf-8"))
        self.assertEqual([s["job_id"] for s in state], ["k1", "k2"])
        with open(self.dir / "hard_skills.csv", encoding="utf-8-sig") as f:
            skills = [row["skill"] for row in csv.DictReader(f)]
        self.assertEqual(sorted(skills), ["Cisco", "Excel", "SQL"])
        r = self.client.post(reverse("data_clear_source", args=["trabajo"]), follow=True)
        self.assertContains(r, "has no Trabajo job postings")

    def test_clear_is_administrator_only_and_post_only(self):
        fac = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="secret123", first_name="F",
                                             last_name="C", role=CustomUser.Role.FACULTY)
        self.client.force_login(fac)
        self.assertEqual(self.client.post(reverse("data_clear_source", args=["kalibrr"])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("data")), 'id="clear-source-form"')
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("data_clear_source", args=["kalibrr"])).status_code, 405)
        self.assertEqual(self.client.post(reverse("data_clear_source", args=["indeed"])).status_code, 404)
        self.assertEqual(len(self.ids()), 4)


class KeepFormInputsTests(IsolatedDataMixin, TestCase):
    """A failed login/sign-up keeps what was typed (never the login password), and
    the login page can be posted with fetch() so it doesn't reload."""

    def setUp(self):
        super().setUp()
        self.user = CustomUser.objects.create_user("keep@ue.edu.ph", "right-password1",
                                                   first_name="Ke", last_name="Ep")

    def test_failed_login_keeps_the_email_but_not_the_password(self):
        r = self.client.post(reverse("login"), {"email": "keep@ue.edu.ph", "password": "wrong-password"})
        self.assertContains(r, "Invalid email or password.")
        self.assertContains(r, 'value="keep@ue.edu.ph"')
        self.assertNotContains(r, "wrong-password")

    def test_login_with_fetch_answers_in_json(self):
        ajax = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        r = self.client.post(reverse("login"), {"email": "keep@ue.edu.ph", "password": "wrong"}, **ajax)
        self.assertEqual(r.json(), {"ok": False, "error": "Invalid email or password."})
        self.assertNotIn("_auth_user_id", self.client.session)
        r = self.client.post(reverse("login") + "?next=/settings/",
                             {"email": "keep@ue.edu.ph", "password": "right-password1"}, **ajax)
        self.assertEqual(r.json(), {"ok": True, "redirect": "/settings/"})
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        r = self.client.post(reverse("login"), {"email": "keep@ue.edu.ph", "password": "right-password1",
                                                "next": "https://evil.example/"}, **ajax)
        self.assertEqual(r.json()["redirect"], reverse("dashboard"))

    def test_paused_login_with_fetch(self):
        ajax = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        for _ in range(5):
            self.client.post(reverse("login"), {"email": "keep@ue.edu.ph", "password": "wrong"}, **ajax)
        r = self.client.post(reverse("login"), {"email": "keep@ue.edu.ph", "password": "right-password1"}, **ajax)
        self.assertEqual(r.status_code, 429)
        self.assertIn("Too many login attempts", r.json()["error"])

    def test_failed_signup_keeps_every_field(self):
        r = self.client.post(reverse("signup"), {
            "last_name": "Cruz", "first_name": "Ana", "middle_name": "Reyes", "email": "keep@ue.edu.ph",
            "password": "long-enough1", "password2": "long-enough1"})
        self.assertContains(r, "An account with this email already exists.")
        for value in ("Cruz", "Ana", "Reyes", "keep@ue.edu.ph", "long-enough1"):
            self.assertContains(r, f'value="{value}"')

    def test_signup_and_register_show_the_password_requirement(self):
        r = self.client.get(reverse("signup"))
        self.assertContains(r, 'data-min-length="8">At least 8 characters</li>')
        self.assertContains(r, 'minlength="8"')

    def test_failed_register_keeps_the_typed_values(self):
        payload = {"consent": True, "personal_info": {"name": "Juan Dela Cruz", "ue_email": "juan@ue.edu.ph",
                   "course": "BSIT", "student_number": "2023-1", "year_level": 1}, "has_previous": False,
                   "subjects": [{"code": "CCP 1101", "term": "current", "skills": []}]}
        reg = self.client.post(reverse("student_survey_submit"), data=json.dumps(payload),
                               content_type="application/json").json()["register_url"]
        token = reg.split("t=", 1)[1]
        r = self.client.post(reverse("register"), {"t": token, "email": "juan@ue.edu.ph",
                                                   "password": "secret123", "password2": "secret124"})
        self.assertContains(r, "Passwords do not match.")
        self.assertContains(r, 'value="juan@ue.edu.ph"')
        self.assertContains(r, 'value="secret123"')
        self.assertContains(r, 'data-min-length="8">At least 8 characters</li>')


class SurveyDraftKeyTests(IsolatedDataMixin, TestCase):
    """curriculum-survey.js keeps unfinished answers only when the page gives it a
    draft key: logged-in users answering for the first time."""

    def boot(self, url_name):
        r = self.client.get(reverse(url_name))
        m = re.search(r'<script type="application/json" id="cs-bootstrap">(.*?)</script>', r.content.decode(), re.S)
        return json.loads(m.group(1))

    def test_no_drafts_when_logged_out(self):
        self.assertIsNone(self.boot("student_survey")["draftKey"])
        self.assertIsNone(self.boot("alumni_survey")["draftKey"])

    def test_logged_in_learners_get_a_key_of_their_own(self):
        user = CustomUser.objects.create_user(email="s@ue.edu.ph", password="secret123", first_name="S",
                                              last_name="T", role=CustomUser.Role.STUDENT)
        self.client.force_login(user)
        self.assertEqual(self.boot("student_survey")["draftKey"], f"ue_survey_draft:student:{user.pk}")
        self.assertEqual(self.boot("alumni_survey")["draftKey"], f"ue_survey_draft:alumni:{user.pk}")

    def test_professor_draft_only_before_the_first_answer(self):
        prof = CustomUser.objects.create_user(email="p@ue.edu.ph", password="secret123", first_name="P",
                                              last_name="C", role=CustomUser.Role.FACULTY)
        self.client.force_login(prof)
        self.assertEqual(self.boot("professor_survey")["draftKey"], f"ue_survey_draft:professor:{prof.pk}")
        self.client.post(reverse("professor_survey_submit"), content_type="application/json", data=json.dumps(
            {"consent": True, "subjects": [{"code": "CCP 1101", "skills": [{"name": "Python", "level": "applied"}]}]}))
        self.assertIsNone(self.boot("professor_survey")["draftKey"])   # editing the saved record: no draft
