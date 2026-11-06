"""Context-aware recommendations: subject profiles, student and faculty context, the
background queue, and the pages that show them."""
from datetime import date
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import (AssumedSkillChoice, CurriculumSurveyResponse, CustomUser, RecommendationJob,
                      SubjectAlias, SubjectSkillStat)
from .helpers import IsolatedDataMixin

# 1st Semester AY 2026-2027: a BSIT 3rd year is in y3s1, previous y2s2 (+ y2sum),
# earlier = y1s1, y1s2, y2s1.
TODAY = date(2026, 11, 6)


def professor(email, subjects):
    user = CustomUser.objects.create_user(email=email, password="secret123", first_name="P", last_name="Rof",
                                          role=CustomUser.Role.FACULTY)
    CurriculumSurveyResponse.objects.create(respondent_type="professor", user=user, data={"subjects": subjects})
    return user


def subject(code, *skills, **extra):
    return {"code": code, "skills": [{"name": n, "level": lvl} for n, lvl in skills], **extra}


def student(email="stud@ue.edu.ph", year="3", course="BSIT", subjects=None, role=""):
    user = CustomUser.objects.create_user(email=email, password="secret123", first_name="S", last_name="Tudent",
                                          role=CustomUser.Role.STUDENT, target_role=role,
                                          learner_info={"course": course, "year_level": year, "section": "A1"})
    CurriculumSurveyResponse.objects.create(respondent_type="student", user=user, data={
        "personal_info": {"course": course, "year_level": year},
        "subjects": subjects if subjects is not None else [subject("CIT 3101", ("HTML", "practiced"), term="current")]})
    return user


def stats(skills, role=None):
    """A fake job_roles.skill_stats() result: skills = [(name, pct)]."""
    rows = [{"key": n.lower(), "skill": n, "count": 1, "pct": pct, "overall_pct": pct} for n, pct in skills]
    out = {"exists": True, "roles": [], "overall": {"postings": 10, "skills": [dict(r) for r in rows]},
           "role": None, "program": "", "source_label": "Kalibrr"}
    if role:
        out["role"] = {"key": role, "label": "Data Analyst", "postings": 5, "skills": rows}
    return out


@mock.patch("myapp.curriculum_data._today", lambda today=None: TODAY)
class SubjectProfileTests(TestCase):
    def test_counts_per_program_and_year(self):
        from .. import subject_profiles
        professor("p1@ue.edu.ph", [subject("CCP 1101", ("Python", "practiced"))])
        professor("p2@ue.edu.ph", [subject("CCP 1101", ("Python", "applied"), ("C", "introduced"))])
        student(subjects=[subject("CCP 1101", ("Python", "introduced"), term="earlier")])
        subject_profiles.rebuild()
        row = SubjectSkillStat.objects.get(program="BSIT", subject_key="computer programming 1", skill_key="python")
        self.assertEqual((row.professors, row.learners, row.year), (2, 1, 1))
        self.assertAlmostEqual(row.professor_depth, (2 / 3 + 1) / 2)
        self.assertEqual(subject_profiles.level_name(subject_profiles.stat_depth(row)), "Practiced")
        # counted only once 2 people report it (the default minimum)
        counted = {r.skill_key for r in subject_profiles.rows_for("BSIT", subject_keys=["computer programming 1"])}
        self.assertEqual(counted, {"python"})

    def test_rebuilds_after_a_survey_is_saved(self):
        with self.captureOnCommitCallbacks(execute=True):
            professor("p1@ue.edu.ph", [subject("CCP 1101", ("Python", "practiced"))])
        self.assertTrue(SubjectSkillStat.objects.filter(skill_key="python").exists())

    def test_aliases_merge_subjects_by_name(self):
        from .. import subject_profiles
        custom = {"custom": True, "programs": ["BSIT"]}
        professor("p1@ue.edu.ph", [subject("XWD 4101", ("React", "applied"), name="Web Dev 2", **custom)])
        professor("p2@ue.edu.ph", [subject("XWD 4102", ("React", "practiced"), name="Web Development 2", **custom)])
        subject_profiles.rebuild()
        self.assertEqual(SubjectSkillStat.objects.filter(skill_key="react").count(), 2)
        SubjectAlias.objects.create(alias_key="web dev 2", alias_name="Web Dev 2",
                                    same_as_key="web development 2", same_as_name="Web Development 2")
        subject_profiles.rebuild()
        row = SubjectSkillStat.objects.get(skill_key="react")
        self.assertEqual((row.subject_key, row.professors), ("web development 2", 2))


@mock.patch("myapp.curriculum_data._today", lambda today=None: TODAY)
class StudentContextTests(TestCase):
    def setUp(self):
        from .. import subject_profiles
        # 1st year subject: two professors report Python, one reports Git
        professor("p1@ue.edu.ph", [subject("CCP 1101", ("Python", "practiced"), ("Git", "applied")),
                                   subject("CDT 1101", ("Power BI", "practiced"))])
        professor("p2@ue.edu.ph", [subject("CCP 1101", ("Python", "practiced")),
                                   subject("CDT 1101", ("Power BI", "applied"))])
        subject_profiles.rebuild()

    def test_assumes_skills_from_earlier_year_levels(self):
        from .. import rec_context
        ctx = rec_context.student_context(student())
        self.assertEqual(set(ctx["assumed"]), {"python"})        # Git: only 1 person
        python = ctx["assumed"]["python"]
        self.assertEqual(python["level"], "Practiced")
        self.assertEqual(python["sources"][0]["subject"], "Computer Programming 1")
        self.assertIn("python", ctx["mine"])

    def test_no_assumption_for_a_subject_they_answered(self):
        from .. import rec_context
        user = student(subjects=[subject("CCP 1101", ("Java", "applied"), term="earlier")])
        self.assertNotIn("python", rec_context.student_context(user)["assumed"])

    def test_first_years_assume_nothing(self):
        from .. import rec_context
        self.assertEqual(rec_context.student_context(student(year="1"))["assumed"], {})

    def test_removed_and_confirmed(self):
        from .. import rec_context
        user = student()
        AssumedSkillChoice.objects.create(user=user, skill_key="python", choice="removed")
        ctx = rec_context.student_context(user)
        self.assertNotIn("python", ctx["mine"])
        self.assertEqual([a["key"] for a in ctx["removed"]], ["python"])
        AssumedSkillChoice.objects.filter(user=user).update(choice="confirmed")
        self.assertTrue(rec_context.student_context(user)["assumed"]["python"]["confirmed"])

    def test_later_subjects_are_coming_up(self):
        from .. import rec_context
        # CDT 1101 Data Analytics is BSIT 2nd year: later for a 1st year, earlier for a 3rd year
        self.assertIn("power bi", rec_context.student_context(student("y1@ue.edu.ph", year="1"))["later"])
        self.assertNotIn("power bi", rec_context.student_context(student())["later"])

    def test_plan_counts_assumed_skills_and_explains(self):
        from .. import rec_context
        user = student(role="data-analyst")
        with mock.patch("myapp.job_roles.skill_stats", return_value=stats(
                [("Python", 60.0), ("SQL", 50.0), ("HTML", 20.0)], role="data-analyst")):
            plan = rec_context.student_plan(user)
        self.assertEqual((plan["have"], plan["have_assumed"], plan["readiness"]), (2, 1, 67))
        self.assertEqual([s["skill"] for s in plan["to_build"]], ["SQL"])
        self.assertIn("Data Analyst job postings", plan["to_build"][0]["reason"])

    def test_alumni_get_reported_skills_only(self):
        from .. import rec_context
        user = student("alum@ue.edu.ph")
        user.role = CustomUser.Role.ALUMNI
        user.save()
        self.assertEqual(rec_context.student_context(user)["assumed"], {})


@mock.patch("myapp.curriculum_data._today", lambda today=None: TODAY)
class FacultyContextTests(TestCase):
    JOBS = ([{"sql": "SQL"}, {"sql": "SQL", "data visualization": "Data Visualization"},
             {"power bi": "Power BI"}, {"excel": "Excel"}], {"exists": True})

    def test_four_signals_and_tags(self):
        from .. import rec_context, subject_profiles
        # CFD 1101 (BSIT 1st year) builds SQL up before CIM 1101 (BSIT 2nd year)
        professor("p1@ue.edu.ph", [subject("CFD 1101", ("SQL", "practiced"))])
        professor("p2@ue.edu.ph", [subject("CFD 1101", ("SQL", "practiced"))])
        me = professor("me@ue.edu.ph", [subject("CIM 1101", ("Data Visualization", "applied"), ("Excel", "applied"))])
        for i in range(2):
            student(f"s{i}@ue.edu.ph", subjects=[subject("CIM 1101", ("Data Visualization", "introduced"),
                                                         ("Excel", "applied"), term="earlier")])
        subject_profiles.rebuild()
        with mock.patch("myapp.gap_analysis._industry_mentions", return_value=self.JOBS):
            out = rec_context.faculty_subject("CIM 1101", user=me)
        rows = {r["key"]: r for r in out["rows"]}
        self.assertEqual(rows["data visualization"]["tag"], "not_landing")
        self.assertEqual((rows["data visualization"]["learned_n"], rows["data visualization"]["learned"]), (2, "Introduced"))
        self.assertEqual(rows["sql"]["tag"], "build")
        self.assertEqual(rows["sql"]["earlier_n"], 1)
        self.assertEqual(rows["excel"]["tag"], "on_track")
        self.assertNotIn("excel", [c["key"] for c in out["cards"]])


class RoleCacheTests(IsolatedDataMixin, TestCase):
    def test_resources_are_saved_per_role(self):
        from .. import recommendations
        res = [{"type": "Course", "name": "X", "provider": "", "link": "https://e.com/x", "photo": "", "verified": "no"}]
        with mock.patch.object(recommendations.pipeline, "read_api_keys_text", return_value="k1"), \
                mock.patch("google.genai.Client"), \
                mock.patch.object(recommendations, "_call_gemini", return_value=res), \
                mock.patch.object(recommendations, "RPM", 6000):
            recommendations.generate_for_skills(["SQL"], "student", "", "data-analyst")
            recommendations.generate_for_skills(["SQL"], "student", "", "")
        loaded = recommendations.load_all_recommendations("student")
        self.assertIn(("sql", "data-analyst"), loaded)
        self.assertIn(("sql", ""), loaded)
        self.assertEqual(recommendations.resources_for("SQL", "qa", loaded=loaded), loaded[("sql", "")])


@override_settings(REC_QUEUE_AUTOSTART=False)
@mock.patch("myapp.curriculum_data._today", lambda today=None: TODAY)
class QueueTests(IsolatedDataMixin, TestCase):
    def test_enqueue_skips_skills_with_resources(self):
        from .. import rec_queue
        loaded = {("sql", "qa"): [{"name": "x"}]}
        self.assertFalse(rec_queue.enqueue("student", "SQL", "qa", loaded=loaded))
        self.assertTrue(rec_queue.enqueue("student", "SQL", "", loaded=loaded))
        self.assertTrue(rec_queue.enqueue("student", "sql", "", loaded=loaded))   # already waiting
        self.assertEqual(RecommendationJob.objects.count(), 1)

    def test_process_done_failed_and_paused(self):
        from .. import rec_queue, recommendations
        rec_queue.enqueue("student", "SQL", "qa", loaded={})
        rec_queue.enqueue("student", "Go", "qa", loaded={})
        outcomes = {"SQL": {"results": {"SQL": []}, "errors": {}, "key_errors": []},
                    "Go": {"results": {}, "errors": {"Go": "No resources."}, "key_errors": []}}
        with mock.patch.object(recommendations, "generate_for_skills",
                               side_effect=lambda skills, *a: outcomes[skills[0]]):
            rec_queue.process()
        self.assertEqual(RecommendationJob.objects.get(skill="SQL").status, "done")
        go = RecommendationJob.objects.get(skill="Go")
        self.assertEqual((go.status, go.attempts), ("pending", 1))   # tried again later, up to 3 times

        with mock.patch.object(recommendations, "generate_for_skills",
                               side_effect=recommendations.RecommendationError("No Gemini API key is set.")):
            self.assertIn("paused", rec_queue.process())
        go.refresh_from_db()
        self.assertEqual((go.status, go.attempts), ("pending", 1))   # no key: nothing spent

    def test_student_survey_queues_recommended_skills(self):
        from .. import subject_profiles
        user = student(role="data-analyst")
        subject_profiles.rebuild()
        self.client.force_login(user)
        with mock.patch("myapp.job_roles.skill_stats", return_value=stats([("SQL", 50.0), ("HTML", 20.0)],
                                                                         role="data-analyst")), \
                self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("student_role"), {"role": "data-analyst"})
        job = RecommendationJob.objects.get()
        self.assertEqual((job.skill, job.role, job.audience), ("SQL", "data-analyst", "student"))
        self.assertIn("Data Analyst", job.context)


@mock.patch("myapp.curriculum_data._today", lambda today=None: TODAY)
class PageTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        from .. import subject_profiles
        professor("p1@ue.edu.ph", [subject("CCP 1101", ("Python", "practiced"))])
        professor("p2@ue.edu.ph", [subject("CCP 1101", ("Python", "practiced"))])
        subject_profiles.rebuild()

    def test_student_dashboard_shows_assumed_skills(self):
        user = student()
        self.client.force_login(user)
        with mock.patch("myapp.job_roles.skill_stats", return_value=stats([("Python", 60.0), ("SQL", 50.0)])):
            page = self.client.get(reverse("student_dashboard"))
        self.assertContains(page, "Skills we assumed you have")
        self.assertContains(page, "Computer Programming 1")
        self.assertContains(page, "What to learn next")
        self.assertContains(page, "Why:")

    def test_assumed_skill_choice(self):
        user = student()
        self.client.force_login(user)
        r = self.client.post(reverse("assumed_skill"), {"skill_key": "python", "choice": "removed",
                                                        "next": "https://evil.example/"})
        self.assertEqual(r.url, reverse("student_dashboard") + "#assumed-skills")
        self.assertEqual(AssumedSkillChoice.objects.get(user=user).choice, "removed")
        self.client.post(reverse("assumed_skill"), {"skill_key": "python", "choice": "undo"})
        self.assertFalse(AssumedSkillChoice.objects.exists())

    def test_faculty_subject_page(self):
        me = professor("me@ue.edu.ph", [subject("CCP 1103", ("Python", "applied"))])
        self.client.force_login(me)
        jobs = ([{"python": "Python"}], {"exists": True})
        with mock.patch("myapp.gap_analysis._industry_mentions", return_value=jobs):
            page = self.client.get(reverse("recommendations") + "?subject=CCP 1103")
        self.assertContains(page, "Skills in this subject")
        self.assertContains(page, "Build on earlier years")

    def test_settings_page_is_for_administrators(self):
        self.client.force_login(CustomUser.objects.get(email="p1@ue.edu.ph"))
        self.assertEqual(self.client.get(reverse("rec_settings")).status_code, 403)
        admin = CustomUser.objects.create_user(email="a@ue.edu.ph", password="secret123", first_name="A",
                                               last_name="D", role=CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("rec_settings")), "Subject aliases")
        self.client.post(reverse("rec_settings"), {"action": "settings", "min_respondents": "3"})
        from .. import subject_profiles
        self.assertEqual(subject_profiles.min_respondents(), 3)
        self.client.post(reverse("rec_settings"), {"action": "alias_add", "alias": "Fundamentals of Programming",
                                                   "same_as": "Computer Programming 1"})
        self.assertEqual(SubjectAlias.objects.get().same_as_key, "computer programming 1")
