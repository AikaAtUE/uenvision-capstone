import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import CustomUserManager

# Minimum length for every password set through the app (change password,
# signup, new accounts). Passwords are stored hashed, so this can only be
# enforced when a password is set, never on the stored value.
MIN_PASSWORD_LENGTH = 8
# Passwords that used to be handed out by "Reset password" / blank new accounts, or shown
# on the login page as a demo account. Accounts still using one must pick a new password
# (migration 0010 flags them).
OLD_SHARED_PASSWORDS = ("default123", "rizal123")
_TEMP_PASSWORD_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"  # no 0/O, 1/l/I


def make_temporary_password(length=12):
    """A one-time password for "Reset password" and new accounts made on the Accounts
    page. The administrator passes it on, and the user must change it after logging in."""
    return "".join(secrets.choice(_TEMP_PASSWORD_CHARS) for _ in range(length))


class CustomUser(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model.
    - Login identifier: email (matches login.html / signup.html)
    - Password: inherited from AbstractBaseUser, always stored hashed
      (never store or query the raw password anywhere).
    """

    class Role(models.TextChoices):
        ADMINISTRATOR = "administrator", "Administrator"
        # An administrator in every way, except that their own survey answers are
        # saved as dummy (test) data, like a dummy account's. For testing the live site.
        DEVELOPER = "developer", "Developer"
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
    # Students/alumni only: the personal information they gave when they registered
    # (student_number, course, and year_level + section for students or year_graduated
    # for alumni). The student/alumni survey fills its "About you" part from this.
    learner_info = models.JSONField(default=dict, blank=True)

    # False only for self sign-ups that haven't clicked the link in their
    # confirmation email yet (see email_verification.py). Accounts made by an
    # administrator, createsuperuser, and accounts from before this existed count as confirmed.
    email_verified = models.BooleanField(default=True)
    # Dummy (test) accounts: a Dummy Student is a student and a Dummy Faculty is a
    # faculty member in every way, except that their survey answers are marked
    # is_dummy, are left out of the real skill gap analysis, and the dashboards
    # they see are computed from dummy answers only.
    is_dummy = models.BooleanField(default=False)
    # Faculty who sign up themselves can use UEnvision right away, but show as "not approved yet"
    # on the Accounts page until an administrator approves (or removes) them. Accounts an
    # administrator creates (and every account from before this) are approved.
    is_approved = models.BooleanField(default=True)
    # Administrators only: also email me when there's something to review
    # (e.g. a new faculty sign-up). Off unless they turn it on in Settings.
    notify_by_email = models.BooleanField(default=False)
    # Set when an administrator reset the password or created the account with a temporary
    # one (and for accounts still on an old shared password): the user can
    # only open Settings until they choose their own password (ForcePasswordChangeMiddleware).
    must_change_password = models.BooleanField(default=False)
    # Feedback reminder (feedback_nudge.py): how many times the account has used the main
    # pages, and until when the "Help us evaluate UEnvision" banner is hidden after "Later".
    app_uses = models.PositiveIntegerField(default=0)
    feedback_snoozed_until = models.DateTimeField(null=True, blank=True)
    # When the profile picture (ProfilePhoto) was last set; None = no picture. Kept here so
    # the sidebar knows whether to show one without loading the image itself.
    photo_updated = models.DateTimeField(null=True, blank=True)
    # Colour theme picked in Settings (or with the theme button in the top bar):
    # "light" (the default), "dark", or "system" (follow the phone / computer setting).
    THEMES = ("light", "dark", "system")
    theme = models.CharField(max_length=10, default="light", blank=True)
    # Onboarding tours (onboarding-tour.js) this account has finished or skipped:
    # "survey" (how to answer the survey), "results" (My skill gap / Dashboard),
    # "extraction" (Data Extraction page) and "accounts" (Accounts page). Promoting someone to
    # administrator takes the two admin tours out again (views.accounts.account_edit_view).
    TOURS = ("survey", "results", "extraction", "accounts")
    ADMIN_TOURS = ("extraction", "accounts")
    tours_seen = models.JSONField(default=list, blank=True)

    def seen_tours(self):
        """tours_seen, known tours only. "admin" was the old combined Data Extraction and
        Accounts tour: an account that saw it has seen both of the tours it became."""
        seen = []
        for t in self.tours_seen or []:
            for name in (self.ADMIN_TOURS if t == "admin" else (t,)):
                if name in self.TOURS and name not in seen:
                    seen.append(name)
        return seen

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]  # asked for when using createsuperuser

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        # Emails are not case-sensitive: every way an account is made or changed (sign-up,
        # register, Google, Accounts, Settings) ends up here, so they are all saved in lowercase.
        if self.email:
            self.email = self.email.strip().lower()
        # Only faculty sign-ups wait for an administrator's approval; every other role is approved.
        if self.role != self.Role.FACULTY and not self.is_approved:
            self.is_approved = True
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"is_approved"}
        super().save(*args, **kwargs)

    @property
    def is_administrator(self):
        """Administrators and developers: full access to every admin page."""
        return self.role in (self.Role.ADMINISTRATOR, self.Role.DEVELOPER)

    @property
    def is_developer(self):
        return self.role == self.Role.DEVELOPER

    @property
    def answers_are_dummy(self):
        """Survey answers from this account go to the dummy (test) data set."""
        return self.is_dummy or self.is_developer

    @property
    def is_learner(self):
        """Students and alumni: they only get their own dashboard, SUS and settings."""
        return self.role in (self.Role.STUDENT, self.Role.ALUMNI)

    @property
    def role_label(self):
        """Role as shown in the app, e.g. "Faculty" or "Dummy Faculty"."""
        label = self.get_role_display()
        return f"Dummy {label}" if self.is_dummy else label

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
    # Submitted by a dummy (test) account; kept out of the real results.
    is_dummy = models.BooleanField(default=False, db_index=True)
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
    # Submitted by a dummy (test) account; kept out of the real results.
    is_dummy = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_respondent_type_display()} curriculum survey #{self.pk}"


class Notification(models.Model):
    """An item in an administrator's Notifications page (e.g. a faculty sign-up to approve)."""

    FACULTY_SIGNUP = "faculty_signup"
    KINDS = [(FACULTY_SIGNUP, "Faculty sign-up")]

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=30, choices=KINDS)
    message = models.CharField(max_length=300)
    link = models.CharField(max_length=300, blank=True)
    # The account the notification is about, if any (deleting it removes the notification).
    subject_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
                                     related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.message

    @property
    def when(self):
        """"Just now" or e.g. "5 minutes ago", as shown in the bell's dropdown."""
        from django.utils import timezone
        from django.utils.timesince import timesince

        if (timezone.now() - self.created_at).total_seconds() < 60:
            return "Just now"
        return f"{timesince(self.created_at)} ago"


class ProfilePhoto(models.Model):
    """A user's profile picture, set on Settings. A small JPEG/PNG (resized in the browser
    first) kept in the database, so no media folder or extra server setup is needed. It
    lives in its own table so it isn't loaded with the user on every page."""

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, primary_key=True, related_name="profile_photo")
    data = models.BinaryField()
    content_type = models.CharField(max_length=20)
    updated_at = models.DateTimeField(auto_now=True)


class FeedbackForm(models.Model):
    """A developer's edited copy of one Feedback page survey's contents (purpose, instructions,
    questions / test cases). No row = the defaults in feedback_forms.py are used."""

    key = models.CharField(max_length=20, unique=True)   # "sus", "uat" or "functional"
    content = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    def __str__(self):
        return f"Feedback form: {self.key}"


# ---------------------------------------------------------------------------
# Context-aware recommendations (subject_profiles.py, rec_context.py, rec_queue.py)
# ---------------------------------------------------------------------------
class SubjectSkillStat(models.Model):
    """One row per (data set, program, subject, skill): the "subject profile" built from the
    curriculum survey answers by subject_profiles.rebuild(). Derived data only: it is
    deleted and rebuilt after every survey submit or edit, never typed by hand.

    A subject is identified by its NAME (normalized, after the admin's subject aliases), so a
    subject both programs share, or an elective two professors added with slightly different
    codes, is one subject. `year` is the subject's year level in that program's curriculum
    (None for a subject someone added that isn't in the curriculum)."""

    is_dummy = models.BooleanField(default=False, db_index=True)
    program = models.CharField(max_length=10, blank=True)       # "BSIT" / "BSCS"
    subject_key = models.CharField(max_length=160, db_index=True)
    subject_name = models.CharField(max_length=160)
    codes = models.CharField(max_length=200, blank=True)        # the subject codes seen, "CCP 1101, ..."
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    skill_key = models.CharField(max_length=120)
    skill = models.CharField(max_length=120)
    professors = models.PositiveIntegerField(default=0)         # how many professors reported it here
    learners = models.PositiveIntegerField(default=0)           # how many students / alumni reported it here
    professor_depth = models.FloatField(null=True, blank=True)  # mean level weight, 0-1
    learner_depth = models.FloatField(null=True, blank=True)
    rebuilt_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["is_dummy", "program", "subject_key"])]

    @property
    def respondents(self):
        return self.professors + self.learners


class SubjectAlias(models.Model):
    """Set on Data > Recommendations: "this subject name is the same subject as that one",
    for subjects that are named differently but taught the same (or electives people added
    with different spellings). Both are matched by their normalized name."""

    alias_key = models.CharField(max_length=160, unique=True)
    alias_name = models.CharField(max_length=160)
    same_as_key = models.CharField(max_length=160)
    same_as_name = models.CharField(max_length=160)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["alias_name"]

    def __str__(self):
        return f"{self.alias_name} = {self.same_as_name}"


class AssumedSkillChoice(models.Model):
    """A student's answer to a skill UEnvision assumed they have (from earlier year levels):
    "I have this" (confirmed) or "Remove" (removed)."""

    CONFIRMED = "confirmed"
    REMOVED = "removed"
    CHOICES = [(CONFIRMED, "I have this"), (REMOVED, "Removed")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assumed_skill_choices")
    skill_key = models.CharField(max_length=120)
    choice = models.CharField(max_length=10, choices=CHOICES)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "skill_key"], name="one_choice_per_assumed_skill")]


class RecommendationJob(models.Model):
    """One skill waiting for Gemini to find learning resources (rec_queue.py). Queued after
    every survey submit for the recommended skills that have no resources yet, and worked
    through in the background, a few at a time."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    STATUSES = [(PENDING, "Waiting"), (RUNNING, "Running"), (DONE, "Done"), (FAILED, "Failed")]

    audience = models.CharField(max_length=10)          # "student" / "professor"
    skill_key = models.CharField(max_length=120)
    skill = models.CharField(max_length=120)
    role = models.CharField(max_length=60, blank=True)  # job_roles key; "" = general list
    context = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [models.UniqueConstraint(fields=["audience", "skill_key", "role"], name="one_job_per_skill_role")]

    def __str__(self):
        return f"{self.audience}: {self.skill} ({self.role or 'general'}) {self.status}"
