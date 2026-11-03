from django.test import TestCase


class GapWeightingTests(TestCase):
    def test_level_weights(self):
        from ..gap_analysis import level_weight
        self.assertAlmostEqual(level_weight("applied"), 1.0)
        self.assertAlmostEqual(level_weight("Introduced"), 1 / 3)
        self.assertAlmostEqual(level_weight("beginner"), 0.25)
        self.assertAlmostEqual(level_weight(None), 1.0)

    def test_compute_with_responses(self):
        from .. import gap_analysis
        from ..models import CurriculumSurveyResponse
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
        from ..recommendations import _normalize_type
        self.assertEqual(_normalize_type("Certification"), "Training")
        self.assertEqual(_normalize_type("Official documentation"), "Lesson")
        self.assertEqual(_normalize_type("Online course"), "Course")
        self.assertEqual(_normalize_type(None), "Course")


class RecommendationKeyRotationTests(TestCase):
    def _run(self, keys, outcomes, skills):
        """outcomes: {key: exception or None (success)}; returns (result, keys used per call)."""
        from unittest import mock
        from .. import recommendations

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
        from .. import recommendations

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
        from .. import recommendations

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
        from .. import recommendations

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
        from .. import recommendations

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


class EnvApiKeyTests(TestCase):
    """Gemini keys can come from GEMINI_API_KEYS as well as api_keys.txt."""

    def test_env_keys_are_added_to_file_keys_without_duplicates(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock
        from django.test import override_settings
        from ..pipeline import manager as pipeline

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


class ThreeSourceComparisonTests(TestCase):
    """Job postings vs faculty vs students, skill categories, and "taught in"."""

    def setUp(self):
        from ..models import CurriculumSurveyResponse
        CurriculumSurveyResponse.objects.create(respondent_type="professor", data={
            "subjects": [{"code": "CFD 1101", "skills": [{"name": "SQL", "level": "applied"}]}]})
        CurriculumSurveyResponse.objects.create(respondent_type="student", data={
            "personal_info": {"course": "BSIT"},
            "subjects": [{"code": "CCP 1101", "skills": [{"name": "Python", "level": "advanced"}]}]})

    def test_categories(self):
        from ..skill_categories import category_for
        self.assertEqual(category_for("Agile"), "Software development methods")
        self.assertEqual(category_for("Scrum"), "Software development methods")
        self.assertEqual(category_for("SQL"), "Databases & SQL")
        self.assertEqual(category_for("MySQL"), "Databases & SQL")
        self.assertEqual(category_for("Python"), "Programming languages")
        self.assertEqual(category_for("Cybersecurity"), "Security")
        self.assertEqual(category_for(""), "Other")

    def test_rows_say_which_source_mentions_each_skill(self):
        from .. import gap_analysis
        gap = gap_analysis.compute(top=30)
        if not gap["exists"]:
            self.skipTest("no extracted_skills.csv")
        rows = {r["skill"].lower(): r for c in gap["comparison"]["categories"] for r in c["rows"]}
        if "sql" not in rows or "python" not in rows:
            self.skipTest("SQL / Python not among the top skills in this data")
        self.assertEqual((rows["sql"]["faculty_reported"], rows["sql"]["students_reported"]), (True, False))
        self.assertEqual(rows["sql"]["taught_in"], ["CFD 1101"])
        self.assertEqual(rows["sql"]["category"], "Databases & SQL")
        self.assertEqual((rows["python"]["faculty_reported"], rows["python"]["students_reported"]), (False, True))
        groups = {g["key"]: g for g in gap["comparison"]["groups"]}
        self.assertIn(rows["sql"]["skill"], groups["faculty_only"]["skills"])
        self.assertIn(rows["python"]["skill"], groups["students_only"]["skills"])
        # Counts are untouched: the same skills, in the same order, as the plain gap rows.
        self.assertEqual(sum(g["count"] for g in groups.values()), len(rows))

    def test_admins_get_the_comparison_and_faculty_get_their_subjects(self):
        import json
        from unittest import mock
        from django.urls import reverse
        from ..models import CustomUser, CurriculumSurveyResponse
        gap = {"exists": True, "has_survey_data": True, "comparison": {"groups": [], "categories": []},
               "by_subject": [{"code": "CFD 1101", "could_add": []}, {"code": "CCP 1101", "could_add": []}]}
        admin = CustomUser.objects.create_user(email="ad@ue.edu.ph", password="secret123", first_name="A", last_name="D",
                                               role=CustomUser.Role.ADMINISTRATOR)
        fac = CustomUser.objects.create_user(email="fa@ue.edu.ph", password="secret123", first_name="F", last_name="A",
                                             role=CustomUser.Role.FACULTY)
        CurriculumSurveyResponse.objects.create(respondent_type="professor", user=fac, data={
            "subjects": [{"code": "CFD 1101", "skills": [{"name": "SQL", "level": "applied"}]}]})
        url = reverse("dashboard_skills")
        with mock.patch("myapp.views.pipeline.skills_dashboard", return_value={"exists": True}), \
                mock.patch("myapp.views.gap_analysis.compute", side_effect=lambda *a, **k: json.loads(json.dumps(gap))):
            self.client.force_login(admin)
            d = self.client.get(url).json()["gap"]
            self.assertEqual(d["scope"], "all")
            self.assertIn("comparison", d)
            self.assertEqual(len(d["by_subject"]), 2)
            self.client.force_login(fac)
            d = self.client.get(url).json()["gap"]
            self.assertEqual(d["scope"], "mine")
            self.assertNotIn("comparison", d)
            self.assertEqual([r["code"] for r in d["by_subject"]], ["CFD 1101"])
