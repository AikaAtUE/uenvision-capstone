import json

from django.test import TestCase, override_settings
from django.urls import reverse

import re


from ..models import CurriculumSurveyResponse, CustomUser

from .helpers import IsolatedDataMixin


class CurriculumCalendarTests(TestCase):
    def test_period_follows_calendar(self):
        from datetime import date
        from .. import curriculum_data as cd
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
        from .. import curriculum_data as cd
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
        from .. import curriculum_data as cd
        elig = cd.build_student_eligibility("2")
        self.assertEqual(elig["BSCS"]["1"]["current"]["term_key"], "y1s2")
        self.assertEqual(elig["BSCS"]["1"]["previous"]["term_key"], "y1s1")
        self.assertEqual(elig["BSCS"]["1"]["previous_summer"], [])

    def test_summer_eligibility(self):
        from .. import curriculum_data as cd
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
                              "student_number": "2023-1", "year_level": 3, "section": "TN31"},
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

    def test_student_section_is_required_and_saved(self):
        from ..models import CurriculumSurveyResponse
        for blank in ("", "   ", None):
            p = self.payload()
            p["personal_info"]["section"] = blank
            r = self.post(p)
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["error"], "Please enter your section.")
        p = self.payload()
        p["personal_info"]["section"] = "X" * 31
        self.assertEqual(self.post(p).status_code, 400)
        p = self.payload()
        p["personal_info"]["section"] = "  TN31 "
        self.assertEqual(self.post(p).status_code, 200)
        self.assertEqual(CurriculumSurveyResponse.objects.get().data["personal_info"]["section"], "TN31")

    def test_section_is_asked_of_students_not_alumni(self):
        self.assertContains(self.client.get(reverse("student_survey")), 'id="student-section"')
        self.assertNotContains(self.client.get(reverse("alumni_survey")), "Section</span>")

    def test_requires_previous_semester(self):
        p = self.payload()
        p["subjects"] = p["subjects"][:1]
        self.assertEqual(self.post(p).status_code, 400)

    def test_survey_pages_render(self):
        for name in ("student_survey", "alumni_survey"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        # the professor survey needs a faculty/administrator login
        self.assertEqual(self.client.get(reverse("professor_survey")).status_code, 302)


class SkillCatalogTests(IsolatedDataMixin, TestCase):
    def test_curated_suggestions_are_subject_specific(self):
        from .. import ontology
        skills = ontology.subject_skill_map()
        self.assertIn("SQL", skills["CFD 1101"])
        self.assertIn("Cisco Packet Tracer", skills["CIT 2201"])
        self.assertEqual(skills["CIT EL01"], [])

    def test_curated_names_missing_from_ontology_are_seeded(self):
        from .. import skills_catalog
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
        from ..job_roles import role_for
        self.assertEqual(role_for("Android Developer", "IT and Software"), "mobile")
        self.assertEqual(role_for("QA Automation Engineer, Hybrid", "IT and Software"), "qa")
        self.assertIsNone(role_for("Tax Accountant", "Accounting and Finance"))

    def test_check_gap_page(self):
        r = self.client.get(reverse("check_gap"), {"role": "qa"})
        self.assertContains(r, "?role=qa")

    def test_homepage_dashboard_and_gap_show_the_same_numbers(self):
        from .. import gap_analysis, job_roles
        from ..pipeline import manager as pipeline
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
        from ..gap_analysis import _standardize
        self.assertEqual(_standardize("JIRA")[0], _standardize(" Jira ")[0])
        self.assertNotEqual(_standardize("REST APIs")[0], _standardize("RESTful APIs")[0])
        self.assertEqual(_standardize("REST APIs")[1], "REST APIs")

    def test_tech_company_industries_are_merged(self):
        from ..pipeline.skills_schema import TECH_INDUSTRY, normalize_record
        for name in ("IT and Software", "Information Technology / IT", "Computer Software / Engineering", "Internet"):
            self.assertEqual(normalize_record({"company_industry": name})["company_industry"], TECH_INDUSTRY)
        self.assertEqual(normalize_record({"company_industry": "Financial Services "})["company_industry"], "Financial Services")
        self.assertEqual(normalize_record({"company_industry": "Insurance"})["company_industry"], "Insurance")


class StudentFlowTests(IsolatedDataMixin, TestCase):
    def submit(self, url_name="student_survey_submit", **extra):
        payload = {
            "consent": True,
            "personal_info": {"name": "Juan Dela Cruz", "ue_email": "juan@ue.edu.ph", "course": "BSIT",
                              "student_number": "2023-1", "year_level": 1, "section": "TN11"},
            "has_previous": False,
            "target_role": "data-analyst",
            "subjects": [{"code": "CCP 1101", "term": "current",
                          "skills": [{"name": "Python", "level": "advanced"}, {"name": "SQL", "level": "beginner"}]}],
        }
        payload.update(extra)
        return self.client.post(reverse(url_name), data=json.dumps(payload), content_type="application/json")

    def test_survey_register_dashboard(self):
        from ..models import CurriculumSurveyResponse
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
        from ..models import CurriculumSurveyResponse
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
        from .. import gap_analysis
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
        from .. import curriculum_data, gap_analysis
        from ..models import CurriculumSurveyResponse
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
        from .. import curriculum_data
        for slot in ("1", "2", "summer"):
            codes = {s["code"] for pool in curriculum_data.professor_term_pools(slot).values() for s in pool}
            self.assertFalse(codes & curriculum_data.NOT_TAUGHT_BY_PROFESSORS)
        values = [v for v, _ in self.client.get(reverse("recommendations")).context["subject_choices"]]
        self.assertNotIn("CCS 4970", values)
        self.assertIn("CFD 1101", values)


    def test_electives_hidden_and_custom_subject_added(self):
        from .. import curriculum_data, gap_analysis
        from ..models import CurriculumSurveyResponse
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
        from ..models import CurriculumSurveyResponse
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
        from .. import curriculum_data
        tags = curriculum_data.subject_term_tags()
        self.assertIn({"tag": "Y1S1IT", "program": "BSIT", "year": 1, "sem": 1}, tags["CCP 1101"])
        self.assertEqual({t["program"] for t in tags["CDS 1101"]}, {"BSIT", "BSCS"})   # shared: one tag each
        self.assertTrue(any(t["tag"] == "Y2S3IT" for ts in tags.values() for t in ts))   # summer is S3

    def test_professor_subjects_sorted_year_sem_course(self):
        from .. import curriculum_data
        tags = curriculum_data.subject_term_tags()
        for pool in curriculum_data.professor_term_pools("1").values():
            keys = [curriculum_data.subject_sort_key(s["code"], tags) for s in pool]
            self.assertEqual(keys, sorted(keys))
        # shared subject goes where BSIT has it
        it = [t for t in tags["CDS 1101"] if t["program"] == "BSIT"][0]
        self.assertEqual(curriculum_data.subject_sort_key("CDS 1101", tags)[:3], (it["year"], it["sem"], 0))
        values = [v for v, _ in self.client.get(reverse("recommendations")).context["subject_choices"]]
        self.assertEqual(values, sorted(values, key=lambda c: curriculum_data.subject_sort_key(c, tags)))


class MySkillsTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        from ..models import CurriculumSurveyResponse
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
        from ..models import CurriculumSurveyResponse
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
        from .. import gap_analysis, student_views
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
        from ..models import CurriculumSurveyResponse
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
        from .. import gap_analysis, views
        _, by_type = gap_analysis._academic_responses()
        self.assertEqual(by_type["professor"], 1)
        self.assertEqual([code for code, _ in views._my_subjects(self.prof)], ["CCP 1101"])

    def test_resubmitting_updates_record_and_consent_is_one_time(self):
        from ..models import CurriculumSurveyResponse
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


class SurveyInstructionsTests(IsolatedDataMixin, TestCase):
    def test_each_survey_says_how_to_answer(self):
        self.assertContains(self.client.get(reverse("student_survey")), 'id="student-steps"')
        self.assertContains(self.client.get(reverse("alumni_survey")), 'id="alumni-steps"')
        prof = CustomUser.objects.create_user(email="pr@ue.edu.ph", password="secret123", first_name="P", last_name="R")
        self.client.force_login(prof)
        r = self.client.get(reverse("professor_survey"))
        self.assertContains(r, 'id="professor-steps"')
        self.assertContains(r, "<strong>Introduced</strong>, <strong>Practiced</strong> or <strong>Applied</strong>")

    def test_privacy_notices_give_the_research_team_email(self):
        for name in ("student_survey", "alumni_survey"):
            r = self.client.get(reverse(name))
            self.assertContains(r, "mailto:inquiries@uenvision.tech")
            self.assertNotContains(r, "through your course adviser")
        prof = CustomUser.objects.create_user(email="pr2@ue.edu.ph", password="secret123", first_name="P", last_name="R")
        self.client.force_login(prof)
        self.assertContains(self.client.get(reverse("professor_survey")), "mailto:inquiries@uenvision.tech")

    def test_alumni_last_semester_list_waits_for_the_course(self):
        r = self.client.get(reverse("alumni_survey"))
        self.assertContains(r, '<select id="alumni-term" disabled><option value="">Choose your course first</option></select>', html=False)
        self.assertContains(r, 'id="alumni-earlier-subjects"')


class HigherYearSubjectTests(TestCase):
    def test_students_are_offered_every_later_term_as_optional(self):
        from .. import curriculum_data
        elig = curriculum_data.build_student_eligibility("1")
        first = elig["BSIT"]["1"]
        later_keys = [t["term_key"] for t in first["later"]]
        seq = [t["key"] for t in curriculum_data.term_sequence("BSIT")]
        self.assertEqual(later_keys, seq[seq.index(first["current"]["term_key"]) + 1:])
        self.assertTrue(later_keys)
        last_year = max(elig["BSIT"], key=int)
        cur = elig["BSIT"][last_year]["current"]["term_key"]
        self.assertEqual([t["term_key"] for t in elig["BSIT"][last_year]["later"]], seq[seq.index(cur) + 1:])

    def test_a_higher_year_subject_can_be_submitted(self):
        from .. import curriculum_data
        elig = curriculum_data.build_student_eligibility()
        y1 = elig["BSIT"]["1"]
        later = y1["later"][0]["subjects"][0]
        payload = {"consent": True, "has_previous": False,
                   "personal_info": {"name": "S", "ue_email": "s@ue.edu.ph", "course": "BSIT", "student_number": "1",
                                     "year_level": 1, "section": "A"},
                   "subjects": [{"code": y1["current"]["subjects"][0]["code"], "term": "current", "skills": []},
                                {"code": later["code"], "term": "later", "skills": [{"name": "Python", "level": "beginner"}]}]}
        r = self.client.post(reverse("student_survey_submit"), content_type="application/json", data=json.dumps(payload))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(CurriculumSurveyResponse.objects.get().data["subjects"][1]["term"], "later")


class CurriculumSuggestionTests(IsolatedDataMixin, TestCase):
    def test_suggestions_only_list_subjects_with_skills_to_add(self):
        from ..views.dashboard import _curriculum_suggestions
        admin = CustomUser.objects.create_user(email="ad@ue.edu.ph", password="secret123", first_name="A", last_name="D",
                                               role=CustomUser.Role.ADMINISTRATOR)
        gap = {"exists": True, "by_subject": [
            {"code": "CFD 1101", "name": "DB", "could_add": [{"skill": "PostgreSQL", "industry_pct": 10.0}]},
            {"code": "CCP 1101", "name": "Prog", "could_add": []}]}
        self.assertEqual([r["code"] for r in _curriculum_suggestions(admin, gap)], ["CFD 1101"])
        self.assertEqual(_curriculum_suggestions(admin, gap, "CCP 1101"), [])
        self.assertEqual(len(gap["by_subject"]), 2)  # the page's own gap data is left alone


class LearnerElectiveTests(TestCase):
    """Students and alumni don't get the "Professional Elective 1-4" placeholders; they add
    the elective they took as a subject of their own, like professors do."""

    def student_payload(self, extra):
        from .. import curriculum_data
        y1 = curriculum_data.build_student_eligibility()["BSIT"]["1"]
        return {"consent": True, "has_previous": False,
                "personal_info": {"name": "S", "ue_email": "s@ue.edu.ph", "course": "BSIT", "student_number": "1",
                                  "year_level": 1, "section": "A"},
                "subjects": [{"code": y1["current"]["subjects"][0]["code"], "term": "current", "skills": []}] + extra}

    def test_elective_placeholders_are_not_offered(self):
        from .. import curriculum_data
        codes = set()
        for years in curriculum_data.build_student_eligibility().values():
            for e in years.values():
                for t in [e["current"], e["previous"] or {"subjects": []}] + e["previous_summer"] + e["earlier"] + e["later"]:
                    codes |= {s["code"] for s in t["subjects"]}
        for terms in curriculum_data.learner_subjects_by_term().values():
            for subs in terms.values():
                codes |= {s["code"] for s in subs}
        self.assertFalse(codes & curriculum_data.PROFESSIONAL_ELECTIVES)
        self.assertNotContains(self.client.get(reverse("alumni_survey")), "Professional Elective 1")

    def test_student_can_add_a_subject_that_is_not_listed(self):
        r = self.client.post(reverse("student_survey_submit"), content_type="application/json", data=json.dumps(
            self.student_payload([{"code": "cit  4105", "name": " Cloud  Computing ", "custom": True, "programs": ["BSCS"],
                                   "skills": [{"name": "AWS", "level": "beginner"}]}])))
        self.assertEqual(r.status_code, 200, r.content)
        added = CurriculumSurveyResponse.objects.get().data["subjects"][1]
        self.assertEqual((added["code"], added["name"], added["programs"], added["term"], added["custom"]),
                         ("CIT 4105", "Cloud Computing", ["BSIT"], "added", True))   # their own course, not what was sent

    def test_added_subject_must_not_reuse_a_listed_code(self):
        r = self.client.post(reverse("student_survey_submit"), content_type="application/json", data=json.dumps(
            self.student_payload([{"code": "CIT EL02", "name": "Elective", "custom": True, "skills": []}])))
        self.assertEqual(r.status_code, 400)

    def test_alumni_can_add_a_subject_and_the_page_offers_it(self):
        self.assertContains(self.client.get(reverse("alumni_survey")), 'id="alumni-other-subject"')
        self.assertContains(self.client.get(reverse("student_survey")), 'id="student-other-subject"')
        from .. import curriculum_data
        last = curriculum_data.learner_subjects_for_term("BSIT", curriculum_data.term_sequence("BSIT")[-1]["key"])[0]
        payload = {"consent": True,
                   "personal_info": {"name": "A", "ue_email": "a@ue.edu.ph", "course": "BSIT", "student_number": "1",
                                     "year_graduated": "2025"},
                   "subjects": [{"code": last["code"], "skills": []},
                                {"code": "CIT 4199", "name": "Game Development", "custom": True, "skills": []}],
                   "employment": {"status": "unemployed"}}
        r = self.client.post(reverse("alumni_survey_submit"), content_type="application/json", data=json.dumps(payload))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(CurriculumSurveyResponse.objects.get().data["subjects"][1]["programs"], ["BSIT"])

    def test_my_skills_lets_a_student_add_a_subject(self):
        user = CustomUser.objects.create_user(email="st@ue.edu.ph", password="secret123", first_name="S", last_name="T",
                                              role=CustomUser.Role.STUDENT)
        CurriculumSurveyResponse.objects.create(respondent_type="student", user=user, data={
            "personal_info": {"course": "BSCS"}, "subjects": []})
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("my_skills")), 'id="ms-other-subject"')
        r = self.client.post(reverse("my_skills_save"), content_type="application/json", data=json.dumps({"subjects": [
            {"code": "CCS 4199", "name": "Game Development", "custom": True, "skills": [{"name": "Unity", "level": "beginner"}]}]}))
        self.assertEqual(r.status_code, 200, r.content)
        subj = CurriculumSurveyResponse.objects.get().data["subjects"][0]
        self.assertEqual((subj["code"], subj["programs"], subj["custom"]), ("CCS 4199", ["BSCS"], True))
