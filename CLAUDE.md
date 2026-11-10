# UEnvision project map

Navigation notes for Claude (and anyone new). Written 2026-11-10 from a full read of the code.
Keep it short and correct: when a module moves or changes its job, fix the line here.

UEnvision is a Django 5.2 site (one app, `myapp`) for UE-CCSS. It scrapes IT/CS job postings,
extracts skills with Gemini, collects curriculum surveys from faculty, students and alumni,
and shows the gap between the two, with learning recommendations.

## Standing rules (from Paeng)

- Never run `git commit`, `git push` or a deploy. Give Paeng the commands (PowerShell on the PC;
  on the server `ssh root@201.18.219.201`, then `sudo bash /home/uenvision/uenvision-capstone/deploy/update.sh`).
  `git add` names the specific changed files.
- Skill results shown anywhere (homepage, dashboards, rankings, gap analysis, recommendations) must
  follow `data/extracted_skills.csv` and `data/hard_skills.csv` as they are. No re-merging, no
  re-normalizing, no fuzzy matching of skill names at display time.
- All postings/skill numbers must come from `job_roles.it_postings()` so every page shows the same count.

## Run, test, deploy

| Task | Command |
| --- | --- |
| Run locally | `python manage.py runserver` (no `.env` needed: DEBUG on, SQLite, console emails) |
| All tests | `python manage.py test myapp` |
| One test file | `python manage.py test myapp.tests.test_surveys` |
| Automation tick | `python manage.py run_automation [--now] [--no-wait]` |
| Recommendation queue | `python manage.py process_recommendations` |
| Rebuild subject profiles | `python manage.py rebuild_subject_profiles` |
| Ghost job check | `python manage.py ghost_job_check` |

Tests turn off the "answer the survey first" redirects and the recommendation thread in
`myapp/tests/__init__.py`. `tests/helpers.py` has `login_administrator` and `IsolatedDataMixin`
(points `DATA_DIR` at a temp copy so tests never touch real data files).

Production: Hostinger Ubuntu VPS, `nginx -> gunicorn (3 sync workers, 300 s timeout, unix socket) -> SQLite`.
Code at `/home/uenvision/uenvision-capstone`, runs as user `uenvision`, env in `.env` there.
`deploy/update.sh` copies `db.sqlite3` to a `.bak`, `git pull`, pip install, migrate, collectstatic,
installs the automation timer, restarts gunicorn. A systemd timer runs `run_automation` every 5 minutes.
Details: `deploy/DEPLOY.md`, `deploy/SECURITY-STEPS.md`, `deploy/.env.example`.

`data/`, `db.sqlite3`, `api_keys.txt` and `.env` are NOT in git (see `.gitignore`); only
`data/ontology/mind_tech_ontology.csv` is. The live datasets exist only on the server.

## Layout

```
manage.py
UEnvision/            settings.py (env-driven), urls.py (admin, allauth under /auth/, then myapp.urls)
myapp/
  urls.py             every route, grouped: public, students/alumni, auth, dashboard, data, feedback, accounts, surveys
  models.py           all models (below)
  middleware.py       access rules by role + idle timeout + ghost-job switch
  context_processors.py, feedback_nudge.py   template context (notification bell, data-updated line, tour, feedback banner)
  views/              the views package (see below)
  student_views.py    public homepage + student/alumni side (views that are NOT in views/)
  survey_admin.py, survey_tracker.py, survey_export.py   Data > Survey Responses / Survey Tracker / CSV export
  pipeline/           scrapers and Gemini scripts, run as subprocesses
  management/commands/   run_automation, process_recommendations, rebuild_subject_profiles, ghost_job_check
  templates/          flat folder; `_name.html` are partials; `emails/` are mail bodies
  static/myapp/       plain JS and CSS, no build step
  tests/              test package (27 files)
  migrations/         0001-0021
data/                 datasets and run state (server-owned, not in git)
deploy/               server config and docs
(old_files_dump)/, _tmp_screens/, foundit_dates.py   leftovers, not used by the app
```

Traps:
- `myapp/views.py` and `myapp/tests.py` are DEAD. The `views/` and `tests/` packages shadow them.
  Never edit them; edit the package files.
- `views/__init__.py` re-exports every view by name. A new view must be added there too or
  `urls.py` (`views.some_view`) will not find it.
- Three middleware allow-lists hold URL names (`LEARNER_URL_NAMES`, `PROFESSOR_SURVEY_URL_NAMES`,
  `LEARNER_SURVEY_URL_NAMES`, plus `PASSWORD_CHANGE_URL_NAMES`). A new URL that students or
  not-yet-surveyed users must reach has to be added to them, or it silently redirects.
- Per-process caches (3 gunicorn workers): `job_roles._CACHE`, `pipeline.manager._table_cache`,
  `ghost_jobs._CACHE`, `job_market._CACHE`, `skills_catalog._ENTRIES`, `skill_suggestions`.
  Most key on file mtime; `skills_catalog._ENTRIES` does not.

## Roles and access

`CustomUser.role`: `administrator`, `developer`, `faculty`, `student`, `alumni`. Login is by email.

| Role | Can open |
| --- | --- |
| Student / alumni (`is_learner`) | Only `LEARNER_URL_NAMES`: homepage, their survey, My skill gap (`/me/`), My subjects & skills, Feedback (SUS, UAT), Settings, Help. Everything else redirects to `/me/`. |
| Faculty | Dashboard, Job Market, Recommendations, Data > View Data (read and download), Professor Survey, Feedback, Settings. Must answer the Professor Survey first. Self sign-ups are `is_approved=False` but are not blocked from anything. |
| Administrator | Everything faculty can, plus Accounts, Notifications, Data Import / Data Extraction / Console, Survey Responses, Data > Recommendations settings. |
| Developer | An administrator whose own answers are saved as dummy data. Also: Real/Dummy and Faculty/Student/Alumni view switches, Survey Tracker, editing the Feedback forms. |

`is_dummy` accounts (Dummy Student / Alumni / Faculty) behave like the role, but their answers are
flagged `is_dummy` and never mix with real results. Guards: `@login_required`,
`views.common.administrator_required`, `survey_tracker.developer_required`, and the middleware.

Middleware order (settings.py): GhostJobs, IdleTimeout (30 min), LearnerAccess, ForcePasswordChange,
ProfessorSurveyFirst, LearnerSurveyFirst.

## Models (`myapp/models.py`)

- `CustomUser`: role, names, `target_role` (job_roles key), `learner_info` JSON (student_number, course,
  year_level, section / year_graduated), flags `email_verified`, `is_dummy`, `is_approved`,
  `must_change_password`, plus `theme`, `tours_seen`, `app_uses`, `photo_updated`.
- `CurriculumSurveyResponse`: `respondent_type` student / alumni / professor, `user`, `is_dummy`, `data` JSON:
  `{personal_info, subjects: [{code, name, term, custom?, programs?, skills: [{name, level}]}], overall_skills?, employment?, target_role, consent_at, edited_at}`.
  Only each account's LATEST response per side (learner / professor) counts.
- `SurveyResponse`: Feedback page answers. `survey_type` sus / uat / functional, `data` JSON.
- `FeedbackForm`: a developer's edited wording of a Feedback form (defaults in `feedback_forms.py`).
- `SubjectSkillStat`: derived "subject profile" rows, rebuilt on every survey save by a signal in `subject_profiles.py`.
- `SubjectAlias`, `AssumedSkillChoice`, `RecommendationJob` (queue), `Notification`, `ProfilePhoto` (image bytes in the DB).

Settings that are NOT in the database live as JSON in `data/.state/`: `scrape_settings.json`,
`extract_settings.json`, `automation.json`, `automation_state.json`, `recommendation_settings.json`,
ghost job settings, `run.json`, `run.log`, `run_config.json`.

## Data flow

```
job boards --scrape--> data/jsons/<source>/*.json --compile--> data/compiled_<source>.csv
   --Gemini extract--> data/extracted_skills.csv (+ data/.state/extracted_skills.json resume file)
   --standardize--> same files, hard skills mapped to ontology names (raw kept in hard_skills_raw)
   --write_skill_csvs--> data/hard_skills.csv, data/soft_skills.csv (tech postings only)
   --job_roles.postings()/it_postings()--> homepage, Dashboard, Job Market, gap analysis, recommendations

surveys --> CurriculumSurveyResponse --> gap_analysis.compute() (vs job postings)
                                    --> subject_profiles (SubjectSkillStat) --> rec_context
rec_context picks skills --> rec_queue (RecommendationJob) --> recommendations.py asks Gemini,
   checks every link --> data/professor_training_recommendations.csv / student_learning_recommendations.csv
```

Sources: `kalibrr`, `trabajo`, `foundit` (registry in `pipeline/sources.py`).

### Pipeline (`myapp/pipeline/`)

| File | Job |
| --- | --- |
| `manager.py` | The only module the web side calls. Paths, View Data table reader, settings forms, `build_steps`, `start_run` / `stop_run` / run state, Import Data, API key file, `skills_dashboard()` (dashboard chart numbers), `ensure_skill_csvs()`. |
| `orchestrator.py` | Standalone detached process that runs the steps of one run, writes `run.json` heartbeat and `run.log`. Sources run as parallel lanes. |
| `sources.py` | Registry of job sources. Adding a source: scraper + layout in `compile_jobs_to_csv.py` + one line here. |
| `search_terms.py` | The CHED expected-roles search list (locked) plus admin extras. |
| `kalibrr_scraper.py`, `trabajo_scraper.py`, `foundit_scraper.py` | One JSON per posting. `kalibrr_backfill.py` walks old job IDs. |
| `compile_jobs_to_csv.py` | JSON folder to compiled CSV per source. `dedupe_trabajo.py` merges Trabajo reposts. |
| `extract_skills_gemini.py` | Gemini extraction in batches, key rotation, resume file. Also sets `isTechJob`, `COMPUTER SCIENCE`, `INFORMATION TECHNOLOGY`. |
| `standardize_skills_gemini.py`, `skill_standardizer.py` | Map hard skills to ontology / `custom_skills.csv` names. |
| `skills_schema.py` | The one column layout of `extracted_skills.csv`; `write_skill_csvs`, `split_skills`. |
| `failed_saves.py` | Per-run log of postings that could not be saved. |

Runs are started from Data > Data Extraction (admin) or by `automation.py` on the timer.
Only one run at a time (`run.json` + heartbeat). Gemini keys: `api_keys.txt` and `GEMINI_API_KEYS`.

### Analysis modules (`myapp/`)

| File | Job |
| --- | --- |
| `job_roles.py` | `postings()` / `it_postings()`: THE reader of extracted postings (tech only, program / source / level filters, ghost exclusion). `ROLES` title patterns, `skill_stats()` for the homepage. |
| `gap_analysis.py` | `_standardize` / `count_key` (how skill names are grouped: case, spacing, punctuation ignored only), `compute()` (alignment score, under-taught, by subject, three-source comparison), `subject_targets()`. |
| `ghost_jobs.py` | Marks possible ghost jobs; never deletes. Viewer switch in the session, read through a contextvar. |
| `job_market.py` | Job Market page numbers. |
| `subject_profiles.py` | Builds `SubjectSkillStat`, subject name aliases, `min_respondents` setting. |
| `rec_context.py` | Which skills to recommend to a student (`student_plan`) or for a professor's subject (`faculty_subject`). No Gemini. |
| `rec_queue.py` | Background queue for finding resources (thread after a survey save, and the timer). |
| `recommendations.py` | Gemini call for resources, link verification, the two recommendation CSVs. |
| `curriculum_data.py` | BSIT/BSCS subject catalog, `ACADEMIC_TERMS` calendar (hand-maintained), eligibility helpers. |
| `ontology.py`, `skills_catalog.py`, `subject_skills.py`, `skill_suggestions.py`, `skill_categories.py` | Skill search, suggestions per subject, display categories. Suggestion and category code never changes counts. |
| `automation.py` | Schedule settings and `tick()`. |

## Views

`myapp/views/`:

| File | Pages |
| --- | --- |
| `common.py` | `home_url_for`, `administrator_required`, `_sees_dummy_results`, `_safe_json` |
| `auth.py` | login, faculty signup, logout, session ping, email verification, forgot / reset password |
| `dashboard.py` | `/dashboard/`, `/dashboard/skills/` (JSON for all dashboard charts and the gap report), Recommendations page, generate and download, developer switches |
| `market.py` | Job Market page and its JSON |
| `data.py` | View Data (table JSON, download, delete), Import, Data Extraction (autosave form, run), Console, ghost jobs, API keys |
| `surveys.py` | student / alumni / professor survey pages and submits |
| `feedback.py` | Feedback page: SUS, UAT, functional sheet; developer form editing |
| `accounts.py` | Accounts page (create, edit, approve, move to student, reset password, delete), notifications |
| `pages.py` | Settings, Help, About, theme, tours, change password, profile photo |
| `rec_admin.py` | Data > Recommendations (min respondents, aliases, queue) |

`myapp/student_views.py`: homepage (`/`), role skills JSON, check-gap, skill search / add, register,
student dashboard (`/me/`), My subjects & skills (view and save), target role, assumed skills, student generate.

`myapp/google_auth.py`: Google sign-in through django-allauth (existing email logs in; a new Google
account is held in the session until the sign-up form is finished).

## Templates and static files

Base templates: `base.html` (public and auth pages), `app_base.html` (logged-in shell with sidebar).
Page templates match their view names (`dashboard.html`, `student_dashboard.html`, `recommendations.html`,
`job_market.html`, `data_view.html`, `data_import.html`, `data_extraction.html`, `console.html`,
`data_survey_responses.html`, `data_survey_tracker.html`, `rec_settings.html`, `accounts.html`,
`feedback.html`, `student_survey.html`, `alumni_survey.html`, `professor_survey.html`, `my_skills.html`,
`settings.html`, `help.html`, `home.html`, `check_gap.html`, `register.html`, `signup.html`, `login.html`).
`data_scrape.html` and `data_extract.html` are old pages whose URLs now redirect to Data Extraction.

Page data is passed as JSON in a `<script type="application/json">` tag (`_safe_json`) or fetched.
JS builds HTML with `escapeHtml` / `textContent`; keep it that way.

| JS | Used by |
| --- | --- |
| `script.js` | app shell (navigation, sidebar) |
| `dashboard-skills.js` | Dashboard charts and gap report from `/dashboard/skills/` |
| `job-market.js` | Job Market charts |
| `curriculum-survey.js` | shared survey engine: skill picker, levels, drafts in localStorage |
| `cs-student.js`, `cs-alumni.js`, `cs-professor.js`, `cs-my-skills.js` | the three survey pages and My subjects & skills |
| `survey.js` | Feedback page (SUS, UAT, functional sheet, form editing) |
| `data-view.js`, `data-import.js`, `data-extraction.js`, `data-scrape.js` | Data pages; `data-scrape.js` polls run status for the Console |
| `recommendations.js` | "Generate selected" on Recommendations and the student dashboard |
| `accounts.js`, `notif-bell.js`, `survey-responses.js` | admin pages |
| `idle-timeout.js`, `survey-first.js`, `onboarding-tour.js`, `welcome-tips.js`, `theme.js`, `ue-modal.js`, `profile-photo.js`, `password-toggle.js`, `resend-countdown.js` | cross-page helpers |

CSS: `styles.css` (main), `public.css`, `dashboard-skills.css`, `student-dashboard.css`, `data-pages.css`,
`curriculum-survey.css`, `job-market.css`, `recommendations.css`, `rec-context.css`, `onboarding-tour.css`,
`uenvision-additions.css`.

## Where to look for common changes

- A number on a chart looks wrong: `job_roles.it_postings()` first, then `pipeline/manager.skills_dashboard()` or `gap_analysis.compute()`.
- A page redirects unexpectedly: the allow-lists in `middleware.py`.
- Survey wording or steps: the survey template plus `curriculum-survey.js` and the page's `cs-*.js`.
- What a survey saves: `views/surveys.py` (`_parse_curriculum_submission`) and `student_views.my_skills_save_view`.
- Subjects or the school calendar: `curriculum_data.py`.
- Run / scrape behaviour: `pipeline/manager.py` (`build_steps`, `start_run`) and `pipeline/orchestrator.py`.
- Emails: `email_verification.py`, `notifications.py`, `templates/emails/`.
