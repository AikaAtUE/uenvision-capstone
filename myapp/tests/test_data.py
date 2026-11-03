import json

from django.test import TestCase, override_settings
from django.urls import reverse


from ..models import CustomUser, SurveyResponse

from .helpers import IsolatedDataMixin


class SurveyResponsesAdminTests(TestCase):
    def setUp(self):
        from ..models import CurriculumSurveyResponse as C
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
        from ..models import CurriculumSurveyResponse as C
        self.client.force_login(self.admin)
        r = self.client.post(reverse("survey_responses_delete"),
                             {"ids": [self.juan.pk, self.maria.pk], "next": reverse("survey_responses") + "?q=x"})
        self.assertRedirects(r, reverse("survey_responses") + "?q=x", fetch_redirect_response=False)
        self.assertEqual(set(C.objects.values_list("pk", flat=True)), {self.dummy.pk, self.prof.pk})
        r = self.client.post(reverse("survey_responses_delete"), {"ids": [self.prof.pk], "next": "https://evil.example/"})
        self.assertRedirects(r, reverse("survey_responses"), fetch_redirect_response=False)


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
        from ..models import CurriculumSurveyResponse
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
        from ..pipeline.skills_schema import JOB_FLAG_COLUMNS, UNIVERSAL_COLUMNS, normalize_record
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
        from .. import job_roles
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

    def test_dashboard_filters_are_in_the_filter_drawer(self):
        admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                               last_name="D", role=CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(admin)
        page = self.client.get(reverse("dashboard")).content.decode()
        drawer = page[page.index('id="filter-drawer"'):]
        for ctl in ("ctl-kind", "ctl-top", "ctl-program", "ctl-source", "ctl-level", "ctl-months", "filter-apply"):
            self.assertEqual(page.count(f'id="{ctl}"'), 1, ctl)
            self.assertIn(f'id="{ctl}"', drawer, ctl)
        self.assertNotIn("skill-controls", page)
        self.assertNotIn("Snowflake", drawer)  # the old mock-up's fixed skill list is gone

    def test_dashboard_bars_split_by_source(self):
        import csv
        from django.conf import settings
        path = settings.DATA_DIR / "extracted_skills.csv"
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        rows[2][2] = rows[5][2] = "trabajo"     # network admin + talent wrangler come from Trabajo
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
        from ..pipeline import manager as pipeline
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
        from ..pipeline.dedupe_trabajo import dedupe_rows
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
        from ..pipeline.dedupe_trabajo import dedupe_rows, merged_job_ids
        first, _ = dedupe_rows([self._row("a", "Pasig", "2026-10-28T10:00:00+01:00"),
                                self._row("b", "Cebu City", "2026-10-28T12:00:00+01:00")])
        again, stats = dedupe_rows(first + [self._row("c", "Makati", "2026-10-20T10:00:00+01:00")])
        self.assertEqual([r["job_id"] for r in again], ["c"])
        self.assertEqual(merged_job_ids(again), {"a", "b"})
        self.assertEqual(again[0]["other_locations"], "Pasig; Cebu City")

    def test_compile_merges_trabajo_but_not_kalibrr(self):
        import csv, tempfile
        from pathlib import Path
        from ..pipeline import compile_jobs_to_csv as cj
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
        from ..pipeline import manager

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
        from ..pipeline import manager
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
