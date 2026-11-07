"""Fixes from the group chat (Nov 7): Feedback answers that haven't been sent are kept in the
browser for this login, Accounts names sort like the Name column shows them (capital letters
don't matter), and a Dummy Alumni account type."""
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from ..models import CustomUser, SurveyResponse

STATIC = Path(__file__).resolve().parent.parent / "static" / "myapp"


def make(email, role=CustomUser.Role.FACULTY, first="F", last="L", **extra):
    return CustomUser.objects.create_user(email=email, password="secret12345", first_name=first,
                                          last_name=last, role=role, **extra)


class FeedbackDraftTests(TestCase):
    def test_page_gets_a_per_login_draft_key(self):
        user = make("stud@ue.edu.ph", role=CustomUser.Role.STUDENT)
        self.client.force_login(user)
        page = self.client.get(reverse("feedback")).content.decode()
        self.assertIn(f'data-draft-key="ue_survey_draft:feedback:{user.pk}:', page)

    def test_survey_js_keeps_and_clears_drafts(self):
        js = (STATIC / "survey.js").read_text(encoding="utf-8")
        for part in ("function writeDraft", "function readDraft", "function dropDraft",
                     "form.addEventListener('input', keepDraft)", "likertSnapshot('sus'",
                     "likertSnapshot('uat'", "rows: collectFunctionalRows()"):
            self.assertIn(part, js)

    def test_sending_again_edits_the_same_answer(self):
        user = make("stud2@ue.edu.ph", role=CustomUser.Role.STUDENT)
        self.client.force_login(user)
        url = reverse("survey_submit")
        for value in (5, 2):
            row = {f"q{n}": value for n in range(1, 11)}
            r = self.client.post(url, {"type": "sus", "rows": [row]}, content_type="application/json")
            self.assertEqual(r.status_code, 200)
        rows = SurveyResponse.objects.filter(user=user, survey_type=SurveyResponse.SUS)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().data["q1"], 2)


class AccountsNameSortTests(TestCase):
    def setUp(self):
        self.client.force_login(make("admin@ue.edu.ph", role=CustomUser.Role.ADMINISTRATOR, first="Zed", last="Admin"))
        make("zz@ue.edu.ph", first="ana", last="Zamora")        # lowercase first letter
        make("aa@ue.edu.ph", first="Carlo", last="Abad")
        make("mm@ue.edu.ph", first="Bea", last="Mendoza")

    def names(self, sort):
        page = self.client.get(reverse("accounts"), {"sort": sort})
        return [a.first_name for a in page.context["accounts"]]

    def test_name_sort_follows_the_name_column_and_ignores_capitals(self):
        self.assertEqual(self.names("name"), ["ana", "Bea", "Carlo", "Zed"])
        self.assertEqual(self.names("-name"), ["Zed", "Carlo", "Bea", "ana"])


class DummyAlumniTests(TestCase):
    def test_admin_can_make_a_dummy_alumni(self):
        admin = make("admin@ue.edu.ph", role=CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(admin)
        page = self.client.get(reverse("accounts"))
        self.assertContains(page, "Dummy Alumni")
        self.client.post(reverse("account_create"), {"last_name": "T", "first_name": "Tester", "email": "da@ue.edu.ph",
                                                     "role": "dummy_alumni", "password": "secret123"})
        user = CustomUser.objects.get(email="da@ue.edu.ph")
        self.assertEqual(user.role, CustomUser.Role.ALUMNI)
        self.assertTrue(user.is_dummy)
        self.assertEqual(user.role_label, "Dummy Alumni")
        self.assertTrue(user.answers_are_dummy)
