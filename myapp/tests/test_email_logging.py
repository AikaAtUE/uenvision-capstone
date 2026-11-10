"""Every email UEnvision sends leaves a line in the server log (journalctl -u uenvision),
so on the live server you can tell whether an email went out or why it didn't."""
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from ..models import CustomUser


class EmailLogTests(TestCase):
    def setUp(self):
        cache.clear()
        self.request = RequestFactory().get("/")
        self.user = CustomUser.objects.create_user(email="ana@ue.edu.ph", password="secret123",
                                                   first_name="Ana", last_name="Cruz")

    def test_every_email_logger_is_shown_at_info(self):
        for name in ("myapp.email_verification", "myapp.notifications", "myapp.survey_tracker"):
            self.assertEqual(settings.LOGGING["loggers"][name]["level"], "INFO", name)

    def test_confirmation_email(self):
        from .. import email_verification
        with self.assertLogs("myapp.email_verification", "INFO") as logs:
            self.assertTrue(email_verification.send_verification_email(self.request, self.user))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Sent a confirmation email to ana@ue.edu.ph", logs.output[0])

    def test_password_reset_email(self):
        from .. import email_verification
        with self.assertLogs("myapp.email_verification", "INFO") as logs:
            self.assertTrue(email_verification.send_password_reset_email(self.request, self.user))
        self.assertIn("Sent a password reset email to ana@ue.edu.ph", logs.output[0])

    @override_settings(EMAIL_HOST="smtp.example.com")
    def test_temporary_password_email(self):
        from .. import notifications
        with self.assertLogs("myapp.notifications", "INFO") as logs:
            self.assertTrue(notifications.send_temporary_password(self.request, self.user, "Temp-pass-123"))
        self.assertIn("Emailed a temporary password to ana@ue.edu.ph", logs.output[0])

    def test_faculty_signup_alert(self):
        from .. import notifications
        CustomUser.objects.create_user(email="boss@ue.edu.ph", password="secret123", first_name="B", last_name="O",
                                       role=CustomUser.Role.ADMINISTRATOR, notify_by_email=True)
        with self.assertLogs("myapp.notifications", "INFO") as logs:
            notifications.notify_faculty_signup(self.request, self.user)
        self.assertEqual(mail.outbox[0].to, ["boss@ue.edu.ph"])
        self.assertIn("Emailed 1 administrator(s) about the faculty sign-up of ana@ue.edu.ph", logs.output[0])

    def test_faculty_signup_alert_failure_is_not_logged_as_sent(self):
        from .. import notifications
        CustomUser.objects.create_user(email="boss@ue.edu.ph", password="secret123", first_name="B", last_name="O",
                                       role=CustomUser.Role.ADMINISTRATOR, notify_by_email=True)
        with mock.patch("myapp.notifications.send_mail", side_effect=OSError("smtp down")), \
                self.assertLogs("myapp.notifications", "INFO") as logs:
            notifications.notify_faculty_signup(self.request, self.user)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Could not email administrators", logs.output[0])

    def test_survey_reminder(self):
        from .. import survey_tracker
        with self.assertLogs("myapp.survey_tracker", "INFO") as logs:
            self.assertTrue(survey_tracker.send_reminder(self.request, self.user, ["sus"]))
        self.assertIn("Sent a survey reminder to ana@ue.edu.ph", logs.output[0])
