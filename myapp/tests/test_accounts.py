import json

from django.test import TestCase, override_settings
from django.urls import reverse

import re

from django.contrib.messages import get_messages

from ..models import CustomUser, SurveyResponse

from .helpers import IsolatedDataMixin


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
                                  "student_number": "2099-1", "year_level": 1, "section": "TN11"},
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
        from .. import gap_analysis
        from ..models import CurriculumSurveyResponse
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


class DummyToggleTests(TestCase):
    def test_switching_an_account_to_dummy_moves_its_answers(self):
        from ..models import CurriculumSurveyResponse as C
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
        from ..models import Notification
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
        from ..models import CurriculumSurveyResponse
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
        from .. import gap_analysis
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
        from ..models import CurriculumSurveyResponse as C
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
        from .. import notifications
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


class ProfilePhotoTests(TestCase):
    JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100

    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.upload = lambda data, name="p.jpg": SimpleUploadedFile(name, data, content_type="image/jpeg")
        self.user = CustomUser.objects.create_user(email="p@ue.edu.ph", password="secret123", first_name="P", last_name="Q",
                                                   role=CustomUser.Role.STUDENT)
        self.client.force_login(self.user)

    def test_upload_show_and_remove(self):
        from ..models import ProfilePhoto
        r = self.client.post(reverse("profile_photo_upload"), {"photo": self.upload(self.JPEG)})
        self.assertRedirects(r, reverse("settings"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.photo_updated)
        img = self.client.get(reverse("profile_photo", args=[self.user.pk]))
        self.assertEqual((img.status_code, img["Content-Type"]), (200, "image/jpeg"))
        self.assertEqual(img.content, self.JPEG)
        self.assertContains(self.client.get(reverse("settings")), 'class="avatar-img"', count=2)  # sidebar + Settings
        self.client.post(reverse("profile_photo_upload"), {"remove": "1"})
        self.user.refresh_from_db()
        self.assertIsNone(self.user.photo_updated)
        self.assertFalse(ProfilePhoto.objects.exists())
        self.assertEqual(self.client.get(reverse("profile_photo", args=[self.user.pk])).status_code, 404)

    def test_rejects_non_images_and_large_files(self):
        from ..views import MAX_PHOTO_BYTES
        self.client.post(reverse("profile_photo_upload"), {"photo": self.upload(b"<script>alert(1)</script>", "x.jpg")})
        self.client.post(reverse("profile_photo_upload"), {"photo": self.upload(self.JPEG + b"0" * MAX_PHOTO_BYTES)})
        self.user.refresh_from_db()
        self.assertIsNone(self.user.photo_updated)

    def test_needs_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("profile_photo", args=[self.user.pk])).status_code, 302)
