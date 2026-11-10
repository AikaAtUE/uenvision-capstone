"""Import Data > Public job dataset CSV: any CSV with one job posting per row (e.g. a Hugging Face
dataset) is saved as data/datasets/<name>.csv, and the ticked steps (skill extraction,
standardizing, ghost job detection) run on it."""
import csv
import json
from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .. import ghost_jobs
from ..models import CustomUser
from ..pipeline import manager as pipeline
from .helpers import IsolatedDataMixin

HF_CSV = (
    "record_id,source_job_id,source_name,posting_date,job_title,job_description,company_name,source_job_category\n"
    "JOB-000001,abc,djinni,2023-01-03,Front-end Developer,\"React, TypeScript and CSS\",Acme,\n"
    "JOB-000002,def,djinni,2023-01-04,Data Analyst,SQL and Power BI,,Data\n"
    "JOB-000003,ghi,djinni,2023-01-05,No description,,Acme,\n"
)


def upload(text=HF_CSV, name="hf.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


class ImportDatasetTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                                    last_name="B", role=CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(self.admin)

    def post(self, **over):
        data = {"import_type": "csv_dataset", "dataset_name": "djinni", "mode": "merge",
                "files": upload(), "ds_extract": "on", "ds_standardize": "on", "ds_ghost": "on"}
        data.update(over)
        return self.client.post(reverse("data_import"), {k: v for k, v in data.items() if v is not None})

    def rows(self, name="djinni"):
        with open(pipeline.dataset_csv(name), encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def test_page_offers_the_dataset_option_and_steps(self):
        page = self.client.get(reverse("data_import"))
        self.assertContains(page, 'value="csv_dataset"')
        for text in ("Extract skills with Gemini into", "Standardize hard skills using the skills ontology",
                     "Ghost job detection: check the postings and report how many are marked"):
            self.assertContains(page, text)

    def test_columns_are_matched_and_ids_prefixed(self):
        res = pipeline.import_dataset("djinni", upload(), merge=True)
        self.assertEqual((res["added"], res["skipped"], res["total"]), (2, 1, 2))
        rows = self.rows()
        self.assertEqual(list(rows[0]), list(pipeline.DATASET_COLUMNS))
        self.assertEqual(rows[0]["job_id"], "djinni-JOB-000001")
        self.assertEqual(rows[0]["created_at"], "2023-01-03")
        self.assertEqual(rows[1]["function"], "Data")
        self.assertEqual(res["columns"]["description"], "job_description")
        # importing again adds nothing; replace starts the file over
        self.assertEqual(pipeline.import_dataset("djinni", upload(), merge=True)["added"], 0)
        self.assertEqual(pipeline.import_dataset("djinni", upload(), merge=False)["total"], 2)
        self.assertEqual(pipeline.list_datasets(), ["djinni"])

    def test_bad_names_and_missing_columns(self):
        for name in ("kalibrr", "Bad Name", "../x", "a"):
            with self.assertRaises(ValueError):
                pipeline.import_dataset(name, upload(), merge=True)
        with self.assertRaisesRegex(ValueError, "description"):
            pipeline.import_dataset("djinni", upload("id,title\n1,Dev\n"), merge=True)

    def test_import_only_when_no_step_is_ticked(self):
        with mock.patch.object(pipeline, "start_run") as start:
            resp = self.post(ds_extract=None, ds_standardize=None, ds_ghost=None)
        self.assertRedirects(resp, reverse("data_import"))
        start.assert_not_called()
        self.assertEqual(len(self.rows()), 2)

    def test_ticked_steps_run_on_the_dataset(self):
        with mock.patch.object(pipeline, "start_run", return_value=None) as start:
            resp = self.post()
        self.assertRedirects(resp, reverse("console"), fetch_redirect_response=False)
        cfg = start.call_args.args[0]
        steps = pipeline.build_steps(cfg)
        self.assertEqual([s["name"] for s in steps], ["extract_dataset_djinni", "standardize", "ghost"])
        argv = steps[0]["argv"]
        self.assertIn(str(pipeline.dataset_csv("djinni")), argv)
        self.assertIn("--source-label=djinni", argv)
        self.assertIn("--text-columns=description", argv)
        self.assertIn("--job-cols=function,created_at", argv)

        with mock.patch.object(pipeline, "start_run", return_value=None) as start:
            self.post(ds_extract=None, ds_standardize=None)
        self.assertEqual([s["name"] for s in pipeline.build_steps(start.call_args.args[0])], ["ghost"])

    def test_run_needs_api_keys(self):
        with self.settings(API_KEYS_FILE=settings.DATA_DIR / "none.txt"):
            resp = self.post(ds_standardize=None, ds_ghost=None)
        self.assertRedirects(resp, reverse("data_import"))
        self.assertFalse((settings.DATA_DIR / ".state" / "run.json").is_file())

    def test_ghost_check_leaves_dataset_postings_out(self):
        # Imported datasets such as Djinni are not job board postings, so ghost job detection
        # neither checks nor lists them (like the Dashboard, which never counts them).
        pipeline.import_dataset("djinni", upload(), merge=True)
        pipeline.ensure_dirs()
        with open(pipeline.extracted_csv(), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["job_id", "source", "job_name", "company_name", "date", "salary_shown", "hard_skills"])
            w.writerow(["djinni-JOB-000001", "djinni", "Front-end Developer", "Acme", "2023-01-03", "", "React"])
            w.writerow(["djinni-JOB-000002", "djinni", "Data Analyst", "", "2023-01-04", "", "SQL"])
            w.writerow(["9", "kalibrr", "Data Analyst", "Beta", "2026-09-01", "False", "SQL"])
        ghost_jobs.save_settings({**ghost_jobs.DEFAULT_SETTINGS, "weak_signs_needed": 1})
        ghost_jobs._CACHE.update(key=None, value=None)
        found = ghost_jobs.detect()
        self.assertEqual(list(found), [("kalibrr", "9")])
        self.assertEqual([r["source"] for r in ghost_jobs.flagged_postings()], ["kalibrr"])
        out = StringIO()
        call_command("ghost_job_check", stdout=out)
        self.assertIn("kalibrr: 1 of 1 posting(s) marked", out.getvalue())
        self.assertNotIn("djinni", out.getvalue())
