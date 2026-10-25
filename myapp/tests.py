import json

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CustomUser, SurveyResponse, DEFAULT_PASSWORD


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
        row = {f"q{n}": value for n in range(1, 11)}
        row.update({"respondent_role": "Student", "program": "BSIT", "sus_score": 999, "comments": None})
        return row

    def test_requires_login(self):
        resp = self.post({"type": "sus", "rows": [self.sus_row()]})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(SurveyResponse.objects.count(), 0)

    def test_sus_saved_and_score_recomputed_on_server(self):
        self.client.force_login(self.user)
        # all 5s: odd items give 4 each (5 x 4 = 20), even items give 0 -> 20 x 2.5 = 50
        resp = self.post({"type": "sus", "rows": [self.sus_row(5)]})
        self.assertEqual(resp.status_code, 200)
        saved = SurveyResponse.objects.get()
        self.assertEqual(saved.user, self.user)
        self.assertEqual(saved.data["sus_score"], 50.0)  # client's 999 is ignored

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
        self.client.post(url, base)
        u = CustomUser.objects.get(email="juan@ue.edu.ph")
        self.assertTrue(u.check_password(DEFAULT_PASSWORD))
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
        self.client.post(reverse("account_reset_password", args=[self.faculty.pk]))
        self.faculty.refresh_from_db()
        self.assertTrue(self.faculty.check_password(DEFAULT_PASSWORD))

    def test_reset_own_password_keeps_session(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("account_reset_password", args=[self.admin.pk]))
        self.assertEqual(self.client.get(reverse("accounts")).status_code, 200)

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
        gap_analysis._INDEX_CACHE = None
        job_roles._CACHE.update(key=None, value=None)
        ontology.subject_skill_map.cache_clear()

    def tearDown(self):
        import shutil
        from . import gap_analysis, job_roles, ontology, skills_catalog
        self._override.disable()
        shutil.rmtree(self._tmp, ignore_errors=True)
        skills_catalog._ENTRIES = None
        skills_catalog._CURATED_DONE = False
        gap_analysis._INDEX_CACHE = None
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
        # BSIT 3rd year's previous term is the 2nd-year summer; BSCS's is 2nd year 2nd sem
        self.assertEqual(elig["BSIT"]["3"]["previous"]["term_key"], "y2sum")
        self.assertEqual(elig["BSCS"]["3"]["previous"]["term_key"], "y2s2")
        self.assertEqual([t["term_key"] for t in elig["BSIT"]["3"]["earlier"]], ["y1s1", "y1s2", "y2s1", "y2s2"])
        codes = [s["code"] for s in elig["BSIT"]["1"]["current"]["subjects"]]
        self.assertIn("CCP 1101", codes)

    def test_second_semester_eligibility(self):
        from . import curriculum_data as cd
        elig = cd.build_student_eligibility("2")
        self.assertEqual(elig["BSCS"]["1"]["current"]["term_key"], "y1s2")
        self.assertEqual(elig["BSCS"]["1"]["previous"]["term_key"], "y1s1")


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

    def test_role_for(self):
        from .job_roles import role_for
        self.assertEqual(role_for("Android Developer", "IT and Software"), "mobile")
        self.assertEqual(role_for("QA Automation Engineer, Hybrid", "IT and Software"), "qa")
        self.assertIsNone(role_for("Tax Accountant", "Accounting and Finance"))

    def test_check_gap_page(self):
        r = self.client.get(reverse("check_gap"), {"role": "qa"})
        self.assertContains(r, "?role=qa")


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
                mock.patch.object(recommendations, "_grounding_unavailable", False):
            rows = recommendations._call_gemini(client, "m", "SQL", "student")
            self.assertEqual(rows[0]["verified"], "no (ungrounded)")
            self.assertTrue(recommendations._grounding_unavailable)
            recommendations._call_gemini(client, "m", "R", "student")
        self.assertEqual(client.models.generate_content.call_count, 3)  # second skill skipped search


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
    """Self sign-ups must click the emailed link before they can log in."""

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

    def test_signup_sends_link_and_blocks_login_until_confirmed(self):
        from django.core import mail
        r = self.signup()
        self.assertContains(r, "Check your email")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new@ue.edu.ph"])
        self.assertIn("noreply@uenvision.tech", mail.outbox[0].from_email)
        self.assertFalse(CustomUser.objects.get(email="new@ue.edu.ph").email_verified)

        r = self.client.post(reverse("login"), {"email": "new@ue.edu.ph", "password": "longenough1"})
        self.assertContains(r, "Confirm your email first")
        self.assertNotIn("_auth_user_id", self.client.session)

        link = self.link_from_outbox()
        self.assertContains(self.client.get(link), "Email confirmed")
        self.assertTrue(CustomUser.objects.get(email="new@ue.edu.ph").email_verified)
        # the link only works once
        self.assertContains(self.client.get(link), "This link doesn't work")

        r = self.client.post(reverse("login"), {"email": "new@ue.edu.ph", "password": "longenough1"})
        # faculty sign-ups still wait for an administrator after confirming
        self.assertRedirects(r, reverse("pending_approval"), fetch_redirect_response=False)

    def test_bad_link_is_rejected(self):
        self.signup()
        link = self.link_from_outbox()
        self.assertContains(self.client.get(link[:-3] + "xx/"), "This link doesn't work")
        self.assertFalse(CustomUser.objects.get(email="new@ue.edu.ph").email_verified)

    def test_resend_is_rate_limited_and_does_not_reveal_accounts(self):
        from django.core import mail
        from django.core.cache import cache
        self.signup()
        r = self.client.post(reverse("resend_verification"), {"email": "new@ue.edu.ph"})
        self.assertContains(r, "wait a minute")
        self.assertEqual(len(mail.outbox), 1)
        cache.clear()
        self.client.post(reverse("resend_verification"), {"email": "new@ue.edu.ph"})
        self.assertEqual(len(mail.outbox), 2)
        r = self.client.post(reverse("resend_verification"), {"email": "nobody@ue.edu.ph"})
        self.assertContains(r, "If <strong>nobody@ue.edu.ph</strong> has an account")
        self.assertEqual(len(mail.outbox), 2)

    def test_existing_and_admin_made_accounts_need_no_confirmation(self):
        user = CustomUser.objects.create_user(email="old@ue.edu.ph", password="secret123",
                                              first_name="O", last_name="L")
        self.assertTrue(user.email_verified)
        r = self.client.post(reverse("login"), {"email": "old@ue.edu.ph", "password": "secret123"})
        self.assertEqual(r.status_code, 302)

    @override_settings(REQUIRE_EMAIL_VERIFICATION=False)
    def test_without_email_settings_signup_logs_in_directly(self):
        r = self.signup("direct@ue.edu.ph")
        self.assertRedirects(r, reverse("pending_approval"), fetch_redirect_response=False)
        self.assertTrue(CustomUser.objects.get(email="direct@ue.edu.ph").email_verified)


@override_settings(REQUIRE_EMAIL_VERIFICATION=True)
class StudentRegisterVerificationTests(StudentFlowTests):
    """Students/alumni registering after the survey also confirm their email first."""

    def test_survey_register_dashboard(self):
        from django.core import mail
        reg = self.submit().json()["register_url"]
        token = reg.split("t=", 1)[1]
        r = self.client.post(reverse("register"), {"t": token, "email": "juan@ue.edu.ph",
                                                   "password": "secret123", "password2": "secret123"})
        self.assertContains(r, "Check your email")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(mail.outbox[-1].to, ["juan@ue.edu.ph"])
        link = mail.outbox[-1].body.split("http://testserver", 1)[1].split()[0]
        self.assertContains(self.client.get(link), "Email confirmed")
        r = self.client.post(reverse("login"), {"email": "juan@ue.edu.ph", "password": "secret123"})
        self.assertRedirects(r, reverse("student_dashboard"), fetch_redirect_response=False)


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
        r = self.client.post(reverse("account_edit", args=[stu.pk]), {**fields, "is_dummy": "1"}, follow=True)
        self.assertContains(r, "1 survey answer moved to dummy (test) data")
        stu.refresh_from_db(); old.refresh_from_db(); other.refresh_from_db()
        self.assertTrue(stu.is_dummy)
        self.assertTrue(old.is_dummy)
        self.assertFalse(other.is_dummy)
        # unticking moves them back
        self.client.post(reverse("account_edit", args=[stu.pk]), fields)
        old.refresh_from_db()
        self.assertFalse(old.is_dummy)
        # administrators can't become dummy accounts
        self.client.post(reverse("account_edit", args=[admin.pk]),
                         {"last_name": "D", "first_name": "A", "email": "adm@ue.edu.ph", "is_dummy": "1"})
        admin.refresh_from_db()
        self.assertFalse(admin.is_dummy)


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

    def test_signup_waits_for_approval_and_admins_are_notified(self):
        from django.core import mail
        from .models import Notification
        r = self.signup()
        self.assertRedirects(r, reverse("pending_approval"), fetch_redirect_response=False)
        prof = CustomUser.objects.get(email="prof@ue.edu.ph")
        self.assertFalse(prof.is_approved)
        # blocked from the app until approved
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("pending_approval"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("data")), reverse("pending_approval"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("pending_approval")), "Waiting for approval")
        # both admins get a notification; only the one who opted in gets an email
        self.assertEqual(Notification.objects.filter(subject_user=prof).count(), 2)
        self.assertEqual([m.to for m in mail.outbox], [["adm2@ue.edu.ph"]])
        self.assertIn("Prof Santos", mail.outbox[0].subject)

        self.client.force_login(self.admin)
        page = self.client.get(reverse("accounts"))
        self.assertContains(page, '<span class="nav-badge" aria-label="1 unread">1</span>', html=True)
        self.assertContains(page, "1 faculty sign-up</strong> waiting for approval")
        self.assertContains(self.client.get(reverse("notifications")), "Prof Santos (prof@ue.edu.ph) signed up")
        self.assertNotContains(self.client.get(reverse("accounts")), "nav-badge")   # read once opened

        self.client.post(reverse("account_approve", args=[prof.pk]))
        prof.refresh_from_db()
        self.assertTrue(prof.is_approved)
        self.assertEqual(mail.outbox[-1].to, ["prof@ue.edu.ph"])
        self.assertFalse(Notification.objects.filter(subject_user=prof, read_at__isnull=True).exists())
        self.client.force_login(prof)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

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
        r = self.client.get(url, {"q": "cruz"})
        self.assertContains(r, "juan@ue.edu.ph")
        self.assertNotContains(r, "prof@ue.edu.ph")
        r = self.client.get(url, {"status": "pending"})
        self.assertContains(r, "prof@ue.edu.ph")
        self.assertNotContains(r, "juan@ue.edu.ph")
        r = self.client.get(url, {"status": "student"})
        self.assertContains(r, "juan@ue.edu.ph")
        self.assertNotContains(r, "adm2@ue.edu.ph")
        r = self.client.get(url, {"q": "nobody-here"})
        self.assertContains(r, "No accounts match")
