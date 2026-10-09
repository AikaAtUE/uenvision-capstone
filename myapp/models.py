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

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.FACULTY)
    last_name = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)  # optional, per signup.html

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