from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import CustomUserManager

# Minimum length for every password set through the app (change password,
# signup, new accounts). Passwords are stored hashed, so this can only be
# enforced when a password is set, never on the stored value.
MIN_PASSWORD_LENGTH = 8
DEFAULT_PASSWORD = "default123"  # what "Reset password" sets (Accounts page)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model.
    - Login identifier: email (matches login.html / signup.html)
    - Password: inherited from AbstractBaseUser, always stored hashed
      (never store or query the raw password anywhere).
    """

    class Role(models.TextChoices):
        ADMINISTRATOR = "administrator", "Administrator"
        FACULTY = "faculty", "Faculty"
        STUDENT = "student", "Student"
        ALUMNI = "alumni", "Alumni"

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.FACULTY)
    last_name = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)  # optional, per signup.html
    # Students/alumni only: the job role picked on their dashboard (job_roles.ROLES key).
    target_role = models.CharField(max_length=60, blank=True)

    # False only for self sign-ups that haven't clicked the link in their
    # confirmation email yet (see email_verification.py). Accounts made by an
    # administrator, createsuperuser, and accounts from before this existed count as confirmed.
    email_verified = models.BooleanField(default=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]  # asked for when using createsuperuser

    def __str__(self):
        return self.email

    @property
    def is_administrator(self):
        return self.role == self.Role.ADMINISTRATOR

    @property
    def is_learner(self):
        """Students and alumni: they only get their own dashboard, SUS and settings."""
        return self.role in (self.Role.STUDENT, self.Role.ALUMNI)

    def get_full_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p)

    def get_short_name(self):
        return self.first_name

class SurveyResponse(models.Model):
    """
    One row per submitted survey record.
    - SUS and UAT: one row per submission.
    - Functional test sheet: one row per test case (rows of the same submission share
      data["submission_id"]).
    The answers themselves live in `data` (JSON) using the same field names as the old
    Supabase tables (q1..q10, sus_score, login_worked, test_case_id, ...).
    """

    SUS = "sus"
    UAT = "uat"
    FUNCTIONAL = "functional"
    SURVEY_TYPES = [
        (SUS, "System Usability Scale"),
        (UAT, "User Acceptance Testing"),
        (FUNCTIONAL, "Functional test case"),
    ]

    survey_type = models.CharField(max_length=20, choices=SURVEY_TYPES, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="survey_responses",
    )
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_survey_type_display()} #{self.pk}"


class CurriculumSurveyResponse(models.Model):
    """
    One row per submitted Student / Fresh Grad Alumni / Professor curriculum-mapping
    survey response. These are separate from SurveyResponse (above), which is for the
    logged-in-only app-evaluation surveys (SUS/UAT/Functional) — these three surveys are
    public (no login) curriculum-vs-skills data collection, so they get their own model.

    Like SurveyResponse, the actual answers live in `data` (JSON) rather than a fixed
    column per field, since the shape differs a lot between the three respondent types
    (see myapp/views.py's student_survey_submit_view / alumni_survey_submit_view /
    professor_survey_submit_view for the exact shape each one saves).
    """

    STUDENT = "student"
    ALUMNI = "alumni"
    PROFESSOR = "professor"
    RESPONDENT_TYPES = [
        (STUDENT, "Student"),
        (ALUMNI, "Fresh Graduate / Alumni"),
        (PROFESSOR, "Professor"),
    ]

    respondent_type = models.CharField(max_length=20, choices=RESPONDENT_TYPES, db_index=True)
    # Professors answer while logged in; students/alumni are linked when they register after the survey.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="curriculum_survey_responses",
    )
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_respondent_type_display()} curriculum survey #{self.pk}"
