"""UEnvision views, split by area so each file stays small:

  common.py     shared helpers (home page per role, administrator_required, dummy results)
  auth.py       log in / sign up / log out, email confirmation, forgot password
  dashboard.py  faculty/admin dashboard and Recommendations page
  pages.py      Settings, Help, About
  feedback.py   Feedback page: SUS, UAT and functional test sheet
  accounts.py   Accounts page and notifications (administrators)
  data.py       Data pages: view, import, scrape, extract skills
  surveys.py    student / alumni / professor curriculum surveys

Everything is re-exported here, so urls.py (views.login_view, ...) and
`from .views import ...` keep working unchanged."""
from .. import gap_analysis  # noqa: F401  (tests patch myapp.views.gap_analysis / .pipeline)
from ..pipeline import manager as pipeline  # noqa: F401
from .common import (  # noqa: F401
    home_url_for,
    administrator_required,
    PH_TIME,
    _sees_dummy_results,
    _safe_json,
)
from .auth import (  # noqa: F401
    login_view,
    signup_view,
    admin_login_view,
    logout_view,
    session_ping_view,
    verify_email_view,
    send_my_verification_view,
    pending_approval_view,
    resend_verification_view,
    forgot_password_view,
    reset_password_view,
    reset_password_confirm_view,
    google_cancelled_view,
    google_error_view,
)
from .dashboard import (  # noqa: F401
    dashboard_view,
    dashboard_skills_view,
    _subject_choices,
    _subject_code,
    _my_custom_subjects,
    _my_subjects,
    recommendations_view,
    recommendations_generate_view,
    recommendations_download_view,
    developer_results_view,
)
from .pages import (  # noqa: F401
    help_view,
    about_view,
    settings_view,
    update_account_view,
    change_password_view,
    MAX_PHOTO_BYTES,
    PHOTO_TYPES,
    _photo_type,
    profile_photo_upload_view,
    profile_photo_view,
)
from .feedback import (  # noqa: F401
    feedback_view,
    feedback_later_view,
    MAX_SURVEY_ROWS,
    SUS_VERSION,
    SUS_QUESTION_COUNT,
    SUS_FIRST_STATEMENTS,
    sus_audience,
    _compute_sus_score,
    survey_submit_view,
)
from .accounts import (  # noqa: F401
    _clean_account_fields,
    ACCOUNT_TYPES,
    DUMMY_TYPES,
    ACCOUNT_FILTERS,
    ACCOUNT_SORTS,
    accounts_view,
    account_create_view,
    account_edit_view,
    _account_type,
    account_approve_view,
    notifications_view,
    notifications_read_view,
    notifications_poll_view,
    notification_settings_view,
    account_reset_password_view,
    account_delete_view,
)
from .data import (  # noqa: F401
    _data_ctx,
    data_view,
    data_delete_view,
    data_clear_source_view,
    data_table_view,
    data_download_view,
    data_import_view,
    _scrape_ctx,
    _extract_ctx,
    data_scrape_view,
    scrape_run_view,
    data_extract_view,
    extract_run_view,
    _stop_and_redirect,
    scrape_stop_view,
    extract_stop_view,
    console_view,
    console_stop_view,
    scrape_status_view,
    api_keys_save_view,
)
from .surveys import (  # noqa: F401
    MAX_SUBJECTS_PER_SUBMISSION,
    MAX_SKILLS_PER_SUBJECT,
    MAX_JSON_BODY_BYTES,
    UE_EMAIL_DOMAIN,
    _is_ue_email,
    MAX_SECTION_LENGTH,
    _parse_curriculum_submission,
    _save_curriculum_survey,
    _is_dummy,
    _learner_survey_saved,
    _clean_target_role,
    _ue_email_error,
    student_survey_submit_view,
    alumni_survey_submit_view,
    professor_survey_submit_view,
    _survey_draft_key,
    student_survey_view,
    alumni_survey_view,
    professor_survey_view,
)
