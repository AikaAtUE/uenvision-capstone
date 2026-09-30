from django.urls import path
from . import views

urlpatterns = [
    path("", views.login_view, name="login"),
    path("signup/", views.signup_view, name="signup"),
    path("forgot-password/", views.forgot_password_view, name="forgot_password"),
    path("reset-password/", views.reset_password_view, name="reset_password"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("data/", views.data_view, name="data"),
    path("feedback/", views.feedback_view, name="feedback"),
    path("feedback/submit/", views.survey_submit_view, name="survey_submit"),
    path("about/", views.about_view, name="about"),
    path("settings/", views.settings_view, name="settings"),
    path("logout/", views.logout_view, name="logout"),
]