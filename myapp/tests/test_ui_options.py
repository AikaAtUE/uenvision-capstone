"""Dark mode, show-password buttons, phone Log out, the developer's Faculty / Student view,
the students' UAT and the Accounts filters."""
import json

from django.test import TestCase
from django.urls import reverse

from ..models import CurriculumSurveyResponse, CustomUser, SurveyResponse


def make_user(email, role, **extra):
    return CustomUser.objects.create_user(email=email, password="secret123", first_name=email[:3].title(),
                                          last_name="Tester", role=role, **extra)


class ThemeTests(TestCase):
    def setUp(self):
        self.user = make_user("fac@ue.edu.ph", CustomUser.Role.FACULTY)
        CurriculumSurveyResponse.objects.create(respondent_type="professor", user=self.user, data={"subjects": []})

    def test_new_accounts_start_in_light_mode(self):
        self.assertEqual(self.user.theme, "light")
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("about")), 'data-theme-pref="light"')

    def test_migration_moves_untouched_accounts_to_light(self):
        from importlib import import_module
        from django.apps import apps
        CustomUser.objects.filter(pk=self.user.pk).update(theme="system")
        dark = make_user("dark@ue.edu.ph", CustomUser.Role.FACULTY, theme="dark")
        import_module("myapp.migrations.0016_theme_default_light").system_to_light(apps, None)
        self.user.refresh_from_db(); dark.refresh_from_db()
        self.assertEqual((self.user.theme, dark.theme), ("light", "dark"))

    def test_theme_is_set_in_the_head_before_the_page_draws(self):
        page = self.client.get(reverse("login")).content.decode()
        # anonymous pages fall back to the browser's last choice (localStorage)
        self.assertIn('data-theme-pref=""', page)
        self.assertLess(page.index("data-theme"), page.index("styles.css"))
        self.assertIn("prefers-color-scheme: dark", page)   # only used when "System" is picked
        self.assertIn("if(p!=='dark'&&p!=='system')p='light';", page)   # no choice yet: light
        self.client.force_login(self.user)
        CustomUser.objects.filter(pk=self.user.pk).update(theme="dark")
        self.assertContains(self.client.get(reverse("about")), 'data-theme-pref="dark"')

    def test_settings_offers_light_dark_and_system(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("settings"))
        self.assertContains(page, 'id="appearance"')
        for value in ("light", "dark", "system"):
            self.assertContains(page, f'name="theme" value="{value}"')
        self.assertContains(page, 'value="light" data-theme-choice checked')

    def test_saving_the_theme(self):
        self.client.force_login(self.user)
        url = reverse("theme_save")
        r = self.client.post(url, {"theme": "dark"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.json(), {"ok": True, "theme": "dark"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "dark")
        # the no-JavaScript form comes back to Settings
        r = self.client.post(url, {"theme": "light"})
        self.assertRedirects(r, reverse("settings") + "#appearance", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "light")
        r = self.client.post(url, {"theme": "purple"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "light")
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_saving_needs_login(self):
        r = self.client.post(reverse("theme_save"), {"theme": "dark"})
        self.assertEqual(r.status_code, 302)

    def test_every_role_can_save_it_even_before_finishing_their_first_steps(self):
        # learner without a survey, faculty without a Professor Survey, temporary password
        for user in (make_user("stu@ue.edu.ph", CustomUser.Role.STUDENT),
                     make_user("new@ue.edu.ph", CustomUser.Role.FACULTY),
                     make_user("tmp@ue.edu.ph", CustomUser.Role.ADMINISTRATOR, must_change_password=True)):
            self.client.force_login(user)
            r = self.client.post(reverse("theme_save"), {"theme": "dark"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(r.status_code, 200, user.email)
            user.refresh_from_db()
            self.assertEqual(user.theme, "dark")

    def test_top_bar_has_the_quick_toggle_and_the_scripts_load(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("about"))
        self.assertContains(page, "data-theme-toggle")
        self.assertContains(page, "myapp/theme.js")
        self.assertContains(page, f'data-save-url="{reverse("theme_save")}"')


class MobileLogoutAndPasswordTests(TestCase):
    def test_log_out_is_in_the_menu_and_in_settings_not_the_top_bar(self):
        for role in (CustomUser.Role.STUDENT, CustomUser.Role.ADMINISTRATOR):
            user = make_user(f"{role}@ue.edu.ph", role)
            if role == CustomUser.Role.STUDENT:
                CurriculumSurveyResponse.objects.create(respondent_type="student", user=user, data={"subjects": []})
            self.client.force_login(user)
            page = self.client.get(reverse("about"))
            self.assertNotContains(page, 'id="logout-btn-mobile"')
            self.assertContains(page, 'id="logout-btn"')   # still at the bottom of the menu
            self.assertContains(page, 'M9 21H5a2 2 0 0 1-2-2V5')   # door-and-arrow log out icon
            self.assertNotContains(page, 'M9 5l-7 7 7 7M2 12h20')  # not the old plain arrow
            settings_page = self.client.get(reverse("settings"))
            self.assertContains(settings_page, 'id="settings-logout"')
            self.assertContains(settings_page, f'action="{reverse("logout")}"')
        r = self.client.post(reverse("logout"))
        self.assertRedirects(r, reverse("home"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("settings")).status_code, 302)   # logged out

    def test_sidebar_header_is_logo_link_plus_close_button(self):
        user = make_user("adm@ue.edu.ph", CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(user)
        page = self.client.get(reverse("about")).content.decode()
        self.assertIn(f'class="sidebar-home" href="{reverse("dashboard")}"', page)
        self.assertIn('id="collapse-btn" aria-controls="sidebar" aria-expanded="true" aria-label="Close menu"', page)
        self.assertNotIn("uenvision-logo.png", page.split('class="sidebar-top"')[1].split("</div>")[0])  # icon only, no wordmark
        self.assertIn('class="mobile-bar-home"', page)
        self.assertNotIn("Header like GitHub", page)   # the template comment stays a comment
        self.assertIn("M19.4 15a1.65", page)   # Settings is a gear now
        self.assertNotIn('r="3.2"', page)

    def test_password_boxes_get_a_show_password_button(self):
        from pathlib import Path
        page = self.client.get(reverse("login"))
        self.assertContains(page, "myapp/password-toggle.js")
        self.assertContains(page, 'type="password"')
        js = (Path(__file__).resolve().parent.parent / "static" / "myapp" / "password-toggle.js").read_text(encoding="utf-8")
        self.assertIn("input[type=\"password\"]", js)
        self.assertIn("btn.type = 'button'", js)          # never submits the form
        self.assertIn("'Show password'", js)
        self.assertIn("'Hide password'", js)
        self.assertIn("aria-pressed", js)


class DeveloperViewTests(TestCase):
    def setUp(self):
        self.dev = make_user("dev@ue.edu.ph", CustomUser.Role.DEVELOPER)
        self.admin = make_user("adm@ue.edu.ph", CustomUser.Role.ADMINISTRATOR)

    def test_developers_get_the_student_survey_tab_instead_of_my_subjects_and_skills(self):
        CurriculumSurveyResponse.objects.create(respondent_type="professor", user=self.dev, is_dummy=True,
                                                data={"subjects": [{"code": "CCP 1101", "skills": []}]})
        self.client.force_login(self.dev)
        data = self.client.get(reverse("data"))
        self.assertNotContains(data, f'href="{reverse("my_skills")}"')   # the tab became Student Survey
        self.assertContains(data, f'href="{reverse("student_survey")}">Student Survey</a>')
        # the page itself still opens (by its address) as their faculty record
        page = self.client.get(reverse("my_skills"))
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context["professor"])           # their faculty record, professor levels
        self.assertEqual(page.context["active_page"], "data")
        self.assertContains(page, "Professor Survey")        # still next to the Professor Survey tab
        # administrators keep editing theirs on the Professor Survey page
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse("data")), f'href="{reverse("my_skills")}"')
        self.assertRedirects(self.client.get(reverse("my_skills")), reverse("professor_survey"),
                             fetch_redirect_response=False)

    def test_faculty_and_student_view_switch(self):
        self.client.force_login(self.dev)
        page = self.client.get(reverse("dashboard"))
        self.assertTemplateUsed(page, "dashboard.html")
        self.assertContains(page, 'value="faculty" class="results-switch-btn is-active"')
        self.assertContains(page, 'value="real" class="results-switch-btn is-active"')

        r = self.client.post(reverse("developer_results"), {"view": "student", "next": "/recommendations/"})
        self.assertRedirects(r, "/recommendations/", fetch_redirect_response=False)
        for name in ("dashboard", "recommendations"):
            page = self.client.get(reverse(name))
            self.assertTemplateUsed(page, "student_dashboard.html")
            self.assertEqual(page.context["active_page"], name)      # the menu item stays highlighted
            self.assertContains(page, 'value="student" class="results-switch-btn is-active"')
            self.assertContains(page, "Student view.")
            self.assertNotContains(page, 'name="results"')          # Real / Dummy only matters to the faculty view

        # each switch keeps the other's setting
        self.client.post(reverse("developer_results"), {"results": "dummy"})
        self.assertTemplateUsed(self.client.get(reverse("dashboard")), "student_dashboard.html")
        self.client.post(reverse("developer_results"), {"view": "faculty"})
        page = self.client.get(reverse("dashboard"))
        self.assertTemplateUsed(page, "dashboard.html")
        self.assertContains(page, 'value="dummy" class="results-switch-btn is-active"')

    def test_picking_a_job_role_in_student_view_comes_back_to_the_dashboard(self):
        self.client.force_login(self.dev)
        self.client.post(reverse("developer_results"), {"view": "student"})
        r = self.client.post(reverse("student_role"), {"role": ""})
        self.assertRedirects(r, reverse("dashboard"), fetch_redirect_response=False)

    def test_only_developers_have_the_view_switch(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse("developer_results"), {"view": "student"}).status_code, 403)
        self.client.session["dev_student_view"] = True
        self.assertTemplateUsed(self.client.get(reverse("dashboard")), "dashboard.html")
        self.assertNotContains(self.client.get(reverse("dashboard")), "Student view")


class StudentUatTests(TestCase):
    def post(self, rows):
        return self.client.post(reverse("survey_submit"), data=json.dumps({"type": "uat", "rows": rows}),
                                content_type="application/json")

    def test_students_answer_their_own_uat_saved_like_the_faculty_one(self):
        student = make_user("stu@ue.edu.ph", CustomUser.Role.STUDENT)
        CurriculumSurveyResponse.objects.create(respondent_type="student", user=student, data={"subjects": []})
        self.client.force_login(student)
        page = self.client.get(reverse("feedback"))
        self.assertContains(page, 'id="uat-questions" data-audience="learner"')
        r = self.post([{f"q{n}": 5 for n in range(1, 11)}])
        self.assertEqual(r.status_code, 200)
        saved = SurveyResponse.objects.get(survey_type="uat")
        self.assertEqual(saved.user, student)
        self.assertEqual((saved.data["uat_score"], saved.data["uat_version"], saved.data["uat_audience"]),
                         (5.0, 2, "learner"))
        self.assertEqual((saved.data["tester_name"], saved.data["tester_role"]), ("Stu Tester", "Student"))
        bad = {f"q{n}": 3 for n in range(1, 11)}
        bad["q4"] = 0
        self.assertEqual(self.post([bad]).status_code, 400)

    def test_faculty_uat_is_marked_as_the_faculty_set(self):
        fac = make_user("fac@ue.edu.ph", CustomUser.Role.FACULTY)
        CurriculumSurveyResponse.objects.create(respondent_type="professor", user=fac, data={"subjects": []})
        self.client.force_login(fac)
        self.assertContains(self.client.get(reverse("feedback")), 'data-audience="faculty"')
        self.post([{f"q{n}": 4 for n in range(1, 11)}])
        self.assertEqual(SurveyResponse.objects.get().data["uat_audience"], "faculty")

    def test_dummy_students_uat_stays_dummy(self):
        student = make_user("dum@ue.edu.ph", CustomUser.Role.STUDENT, is_dummy=True)
        self.client.force_login(student)
        self.post([{f"q{n}": 4 for n in range(1, 11)}])
        self.assertTrue(SurveyResponse.objects.get().is_dummy)


class AccountsFilterTests(TestCase):
    def setUp(self):
        self.admin = make_user("adm@ue.edu.ph", CustomUser.Role.ADMINISTRATOR)
        make_user("juan@ue.edu.ph", CustomUser.Role.STUDENT)
        make_user("dumstu@ue.edu.ph", CustomUser.Role.STUDENT, is_dummy=True)
        make_user("prof@ue.edu.ph", CustomUser.Role.FACULTY, is_approved=False)
        make_user("unconf@ue.edu.ph", CustomUser.Role.ALUMNI, email_verified=False)
        make_user("gone@ue.edu.ph", CustomUser.Role.FACULTY, is_active=False)
        self.client.force_login(self.admin)

    def emails(self, **params):
        page = self.client.get(reverse("accounts"), params)
        return {a.email for a in page.context["accounts"]}

    def test_role_status_and_real_or_dummy_filters_combine(self):
        self.assertEqual(self.emails(role="student"), {"juan@ue.edu.ph", "dumstu@ue.edu.ph"})
        self.assertEqual(self.emails(role="student", kind="real"), {"juan@ue.edu.ph"})
        self.assertEqual(self.emails(kind="dummy"), {"dumstu@ue.edu.ph"})
        self.assertEqual(self.emails(state="pending"), {"prof@ue.edu.ph"})
        self.assertEqual(self.emails(state="unverified"), {"unconf@ue.edu.ph"})
        self.assertEqual(self.emails(state="inactive"), {"gone@ue.edu.ph"})
        self.assertNotIn("prof@ue.edu.ph", self.emails(state="approved"))
        self.assertNotIn("gone@ue.edu.ph", self.emails(state="approved"))
        self.assertEqual(self.emails(role="faculty", q="prof"), {"prof@ue.edu.ph"})
        # unknown values are ignored
        self.assertEqual(len(self.emails(role="wizard", state="?", kind="x")), CustomUser.objects.count())

    def test_old_show_menu_links_still_work(self):
        self.assertEqual(self.emails(status="pending"), {"prof@ue.edu.ph"})
        self.assertEqual(self.emails(status="student"), {"juan@ue.edu.ph"})
        self.assertEqual(self.emails(status="dummy"), {"dumstu@ue.edu.ph"})

    def test_filter_drawer_count_and_removable_chips(self):
        page = self.client.get(reverse("accounts"))
        self.assertContains(page, 'id="acct-filter-drawer"')
        self.assertContains(page, 'id="acct-filter-count" hidden')
        page = self.client.get(reverse("accounts"), {"role": "student", "kind": "real", "q": "juan"})
        self.assertEqual(page.context["filter_count"], 2)
        chips = dict(page.context["filter_chips"])
        self.assertEqual(chips["Students"], reverse("accounts") + "?q=juan&kind=real")
        self.assertEqual(chips["Real accounts only"], reverse("accounts") + "?q=juan&role=student")
        self.assertContains(page, '<option value="student" selected>Students</option>', html=False)
        self.assertContains(page, '<input type="hidden" name="q" value="juan">')


class SkillGapYouColumnTests(TestCase):
    """My skill gap: what the "You" column's levels mean (legend + a tip on every pill)."""

    def page(self):
        from unittest import mock
        from .. import gap_analysis
        key = lambda name: gap_analysis._standardize(name)[0]
        skills = [{"key": key(n), "skill": n, "pct": p} for n, p in (("SQL", 30.0), ("Python", 25.0), ("Docker", 9.0))]
        stats = {"exists": True, "roles": [], "role": None, "source_label": "Kalibrr",
                 "overall": {"postings": 100, "skills": skills}}
        student = make_user("stu@ue.edu.ph", CustomUser.Role.STUDENT)
        CurriculumSurveyResponse.objects.create(respondent_type="student", user=student, data={"subjects": [
            {"code": "X", "skills": [{"name": "SQL", "level": "applied"}, {"name": "Python", "level": "introduced"}]}]})
        self.client.force_login(student)
        with mock.patch("myapp.student_views.job_roles.skill_stats", side_effect=lambda *a, **k: json.loads(json.dumps(stats))):
            return self.client.get(reverse("student_dashboard"))

    def test_legend_reuses_the_survey_wording(self):
        page = self.page()
        self.assertContains(page, 'id="you-legend"', count=1)          # once, above both tables
        for label in ("Applied", "Practiced", "Introduced", "Not yet"):
            self.assertContains(page, f'">{label}</span><span>')
        # same descriptions as the student survey's level guide (curriculum-survey.js)
        from pathlib import Path
        js = (Path(__file__).resolve().parent.parent / "static" / "myapp" / "curriculum-survey.js").read_text(encoding="utf-8").replace(chr(92) + "u2019", chr(0x2019))
        from ..student_views import YOU_LEVELS
        for key, _, _, text in YOU_LEVELS:
            if key != "missing":
                survey_text = text.split(". Counts")[0].split(". Does not")[0] + "."
                self.assertIn(survey_text, js, key)
        self.assertContains(page, "reported this skill in any of your subjects.")

    def test_every_pill_explains_itself_on_hover_focus_and_tap(self):
        page = self.page()
        html = page.content.decode()
        # SQL: Applied, Python: Introduced, Docker: Not yet -- in both tables
        for prefix in ("you-top", "you-all"):
            for n in (1, 2, 3):
                self.assertIn(f'aria-describedby="{prefix}-{n}"', html)
                self.assertIn(f'role="tooltip" id="{prefix}-{n}"', html)
        self.assertIn('<button type="button" class="sd-pill sd-pill--strong sd-tip-btn" aria-expanded="false" '
                      'aria-describedby="you-top-1">Applied</button>', html)
        self.assertIn('class="sd-pill sd-pill--building sd-tip-btn"', html)
        self.assertIn('class="sd-pill sd-pill--missing sd-tip-btn"', html)
        self.assertIn("Does not count toward job readiness yet.", html)
        # the info button on the heading
        self.assertIn('aria-label="What the Your Skill Level column means"', html)
        self.assertIn('<th>Job Skills</th><th>In job postings</th>', html)
        self.assertIn('Your Skill Level <span', html)
        self.assertIn('What &ldquo;Your Skill Level&rdquo; means', html)
        self.assertIn("Your highest level for this skill, from your survey.", html)

    def test_readiness_wording_uses_the_new_levels(self):
        page = self.page()
        self.assertContains(page, "at Practiced or Applied")
        self.assertNotContains(page, "Intermediate or better")
