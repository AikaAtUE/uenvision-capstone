"""The "Help us evaluate UEnvision" banner.

Asks for the Feedback surveys only after someone has actually used UEnvision (SUS answers
from people who haven't used it don't mean much): each visit to a main page (My skill gap,
finding resources, the Dashboard, Recommendations) counts as a use, and after
USES_BEFORE_ASKING uses the banner shows on every page until the account has answered.
"Later" hides it for SNOOZE_DAYS days."""
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

USES_BEFORE_ASKING = 3
SNOOZE_DAYS = 3


def record_use(user):
    from .models import CustomUser

    if user.is_authenticated:
        CustomUser.objects.filter(pk=user.pk).update(app_uses=F("app_uses") + 1)


def snooze(user):
    user.feedback_snoozed_until = timezone.now() + timedelta(days=SNOOZE_DAYS)
    user.save(update_fields=["feedback_snoozed_until"])


def missing_surveys(user):
    """[(survey_type, label)] of the Feedback surveys this account still has to answer.
    Students and alumni only get the SUS; everyone else also gets the UAT and test sheet."""
    from .models import SurveyResponse

    wanted = [(SurveyResponse.SUS, "SUS evaluation")]
    if not user.is_learner:
        wanted += [(SurveyResponse.UAT, "UAT survey"), (SurveyResponse.FUNCTIONAL, "test case sheet")]
    done = set(SurveyResponse.objects.filter(user=user).values_list("survey_type", flat=True).distinct())
    return [(kind, label) for kind, label in wanted if kind not in done]


def banner(request):
    """Context processor: {"feedback_nudge": {"missing": [...], "first": survey_type}} or {}."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or user.app_uses < USES_BEFORE_ASKING:
        return {}
    if user.feedback_snoozed_until and user.feedback_snoozed_until > timezone.now():
        return {}
    match = getattr(request, "resolver_match", None)
    if match is not None and match.url_name == "feedback":
        return {}
    missing = missing_surveys(user)
    if not missing:
        return {}
    labels = [label for _, label in missing]
    text = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]
    return {"feedback_nudge": {"text": text, "first": missing[0][0]}}
