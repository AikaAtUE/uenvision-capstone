"""UEnvision tests, split by area (accounts, auth, surveys, feedback, data, analysis).
Run them all with:  python manage.py test myapp"""
# Most tests log in as a plain Faculty account to test other things, so the "answer the
# Professor Survey first" redirect is off by default here; ProfessorSurveyFirstTests turns it on.
from django.conf import settings as _settings

_settings.REQUIRE_PROFESSOR_SURVEY = False
