from django.shortcuts import redirect
from django.urls import Resolver404, resolve

# Pages a logged-in student/alumni may open. Everything else in the app (the
# faculty/administrator Dashboard, Data, Recommendations, Accounts, Console, ...)
# sends them back to their own dashboard.
LEARNER_URL_NAMES = {
    "home", "role_skills", "check_gap", "skill_search", "skill_add", "register", "login", "logout",
    "student_dashboard", "student_role", "student_generate", "my_skills", "my_skills_save",
    "student_survey", "student_survey_submit", "alumni_survey", "alumni_survey_submit",
    "feedback", "survey_submit", "about", "settings", "change_password",
}


class LearnerAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "is_learner", False):
            try:
                match = resolve(request.path_info)
            except Resolver404:
                match = None
            if match is not None and match.url_name not in LEARNER_URL_NAMES:
                return redirect("student_dashboard")
        return self.get_response(request)
