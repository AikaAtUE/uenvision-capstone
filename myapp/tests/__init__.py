"""UEnvision tests, split by area (accounts, auth, surveys, feedback, data, analysis).
Run them all with:  python manage.py test myapp"""
# Most tests log in as a plain Faculty account to test other things, so the "answer the
# Professor Survey first" redirect is off by default here; ProfessorSurveyFirstTests turns it on.
# Likewise for students/alumni ("answer your survey first"); LearnerSurveyFirstTests turns it on.
from django.conf import settings as _settings

_settings.REQUIRE_PROFESSOR_SURVEY = False
_settings.REQUIRE_LEARNER_SURVEY = False
# The recommendations queue never starts its background thread (and never calls Gemini) in tests.
_settings.REC_QUEUE_AUTOSTART = False
# The Recommendations Lab's resource finder doesn't start either, and the site keeps showing the
# classic recommendation pages unless a test turns the new system on (test_recs_lab.LiveTests).
_settings.RECS_LAB_WORKER_AUTOSTART = False
_settings.RECS_SYSTEM = "classic"   # the original pages; LiveTests turn the new system on
