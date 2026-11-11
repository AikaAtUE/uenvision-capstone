from django.urls import include, path
from django.views.generic import RedirectView

from . import google_auth, student_views, survey_admin, survey_tracker, views
from .recs_lab import live as recs_live
from .views import rec_admin

urlpatterns = [
    # Public site
    path("", student_views.home_view, name="home"),
    path("roles/skills/", student_views.role_skills_view, name="role_skills"),
    path("check-skill-gap/", student_views.check_gap_view, name="check_gap"),
    path("skills/search/", student_views.skill_search_view, name="skill_search"),
    path("skills/add/", student_views.skill_add_view, name="skill_add"),
    path("register/", student_views.register_view, name="register"),

    # Students / alumni
    path("me/", student_views.student_dashboard_view, name="student_dashboard"),
    path("me/skills/", student_views.my_skills_view, name="my_skills"),
    path("me/skills/save/", student_views.my_skills_save_view, name="my_skills_save"),
    path("me/role/", student_views.student_role_view, name="student_role"),
    path("me/about/", student_views.learner_about_save_view, name="learner_about_save"),
    path("me/recommendations/generate/", student_views.student_generate_view, name="student_generate"),
    path("me/recommendations/find/", recs_live.find_view, name="recs_live_find"),
    path("me/assumed-skills/", student_views.assumed_skill_view, name="assumed_skill"),

    path("login/", views.login_view, name="login"),
    path("session/ping/", views.session_ping_view, name="session_ping"),
    path("signup/", views.signup_view, name="signup"),
    path("signup/google/", google_auth.start_google_signup_view, name="google_signup_start"),
    path("verify-email/resend/", views.resend_verification_view, name="resend_verification"),
    path("verify-email/<uidb64>/<token>/", views.verify_email_view, name="verify_email"),
    path("forgot-password/", views.forgot_password_view, name="forgot_password"),
    path("reset-password/", views.reset_password_view, name="reset_password"),
    path("reset-password/<uidb64>/<token>/", views.reset_password_confirm_view, name="reset_password_confirm"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("dashboard/skills/", views.dashboard_skills_view, name="dashboard_skills"),
    path("job-market/", views.job_market_view, name="job_market"),
    path("job-market/data/", views.job_market_data_view, name="job_market_data"),
    # The new recommendation system (recs_lab/live.py). The original page keeps running at classic/, developers only.
    path("recommendations/", recs_live.recommendations_view, name="recommendations"),
    path("recommendations/classic/", recs_live.classic_view, name="recommendations_classic"),
    path("recommendations/generate/", views.recommendations_generate_view, name="recommendations_generate"),
    path("recommendations/download/", views.recommendations_download_view, name="recommendations_download"),
    path("data/", views.data_view, name="data"),
    path("data/table/", views.data_table_view, name="data_table"),
    path("data/download/<str:key>/", views.data_download_view, name="data_download"),
    path("data/failed-saves/delete/", views.failed_saves_delete_view, name="failed_saves_delete"),
    path("data/failed-saves/<str:name>/", views.failed_saves_download_view, name="failed_saves_download"),
    path("data/delete/<str:key>/", views.data_delete_view, name="data_delete"),
    path("data/clear/<str:source>/", views.data_clear_source_view, name="data_clear_source"),
    path("data/import/", views.data_import_view, name="data_import"),
    path("data/ghost-jobs/", views.data_ghost_jobs_view, name="data_ghost_jobs"),
    path("data/extraction/", views.data_extraction_view, name="data_extraction"),
    path("data/scrape/", views.data_scrape_view, name="data_scrape"),      # old address -> Data Extraction
    path("data/scrape/status/", views.scrape_status_view, name="scrape_status"),
    path("console/", views.console_view, name="console"),
    path("console/stop/", views.console_stop_view, name="console_stop"),
    path("data/extract/", views.data_extract_view, name="data_extract"),   # old address -> Data Extraction
    path("data/extract/api-keys/", views.api_keys_save_view, name="api_keys_save"),
    path("feedback/", views.feedback_view, name="feedback"),
    path("feedback/submit/", views.survey_submit_view, name="survey_submit"),
    path("feedback/later/", views.feedback_later_view, name="feedback_later"),
    path("feedback/form/<str:key>/", views.feedback_form_save_view, name="feedback_form_save"),
    path("about/", views.about_view, name="about"),
    path("help/", views.help_view, name="help"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/change-password/", views.change_password_view, name="change_password"),
    path("settings/account/", views.update_account_view, name="update_account"),
    path("settings/theme/", views.theme_save_view, name="theme_save"),
    path("tour/seen/", views.tour_seen_view, name="tour_seen"),
    path("settings/photo/", views.profile_photo_upload_view, name="profile_photo_upload"),
    path("photo/<int:pk>/", views.profile_photo_view, name="profile_photo"),
    path("settings/confirm-email/", views.send_my_verification_view, name="send_my_verification"),
    path("accounts/", views.accounts_view, name="accounts"),
    path("accounts/create/", views.account_create_view, name="account_create"),
    path("accounts/<int:pk>/edit/", views.account_edit_view, name="account_edit"),
    path("accounts/<int:pk>/approve/", views.account_approve_view, name="account_approve"),
    path("accounts/<int:pk>/move-to-student/", views.account_move_to_student_view, name="account_move_to_student"),
    path("notifications/", views.notifications_view, name="notifications"),
    path("notifications/read/", views.notifications_read_view, name="notifications_read"),
    path("notifications/poll/", views.notifications_poll_view, name="notifications_poll"),
    path("developer/results/", views.developer_results_view, name="developer_results"),
    path("settings/notifications/", views.notification_settings_view, name="notification_settings"),
    path("pending-approval/", views.pending_approval_view, name="pending_approval"),
    path("accounts/<int:pk>/reset-password/", views.account_reset_password_view, name="account_reset_password"),
    path("accounts/<int:pk>/delete/", views.account_delete_view, name="account_delete"),
    path("logout/", views.logout_view, name="logout"),

    # Curriculum-mapping surveys: Student / Alumni are public; the Professor survey
    # lives under Data and needs a faculty/administrator login.
    path("survey/student/", views.student_survey_view, name="student_survey"),
    path("survey/student/submit/", views.student_survey_submit_view, name="student_survey_submit"),
    path("survey/alumni/", views.alumni_survey_view, name="alumni_survey"),
    path("survey/alumni/submit/", views.alumni_survey_submit_view, name="alumni_survey_submit"),
    path("data/survey-responses/", survey_admin.survey_responses_view, name="survey_responses"),
    path("data/survey-responses/delete/", survey_admin.survey_responses_delete_view, name="survey_responses_delete"),
    path("data/survey-responses/csv/", survey_admin.survey_responses_csv_view, name="survey_responses_csv"),
    path("data/feedback-responses/<str:kind>/csv/", survey_admin.feedback_csv_view, name="feedback_responses_csv"),
    path("data/survey-tracker/", survey_tracker.survey_tracker_view, name="survey_tracker"),
    path("data/recommendations/", rec_admin.rec_settings_view, name="rec_settings"),
    path("data/survey-tracker/remind/", survey_tracker.survey_tracker_remind_view, name="survey_tracker_remind"),
    path("data/professor-survey/", views.professor_survey_view, name="professor_survey"),
    path("data/professor-survey/submit/", views.professor_survey_submit_view, name="professor_survey_submit"),
    path("survey/professor/", RedirectView.as_view(pattern_name="professor_survey", permanent=False)),

    # Recommendations Lab: the experimental recommendation system, developers only, not linked anywhere.
    path("recs-lab/", include("myapp.recs_lab.urls")),
]
