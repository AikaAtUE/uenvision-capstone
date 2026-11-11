"""Recommendations Lab (/recs-lab/): developers only, blueprint-aware faculty advice, gap ranking
that keeps each skill's own share, and the skill tags. Gemini is always mocked."""
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from ..models import CurriculumSurveyResponse as R, CustomUser
from ..recs_lab import blueprints, engine, gemini, taxonomy
from .helpers import IsolatedDataMixin

LAB_PAGES = ["recs_lab", "recs_lab_faculty", "recs_lab_admin", "recs_lab_student", "recs_lab_alumni", "recs_lab_resources",
             "recs_lab_blueprints", "recs_lab_skills"]


def make_user(email, role, **kw):
    u = CustomUser.objects.create_user(email=email, password="secret123", first_name="T", last_name=email[:4],
                                       role=role, **kw)
    u.email_verified = True
    u.save()
    return u


class LabAccessTests(IsolatedDataMixin, TestCase):
    def test_developer_sees_every_page(self):
        self.client.force_login(make_user("dev@ue.edu.ph", CustomUser.Role.DEVELOPER))
        for name in LAB_PAGES:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)
        r = self.client.get(reverse("recs_lab_faculty") + "?subject=CCS%201101")
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse("recs_lab_blueprints") + "?subject=CCS%201101")
        self.assertEqual(r.status_code, 200)

    def test_other_roles_never_reach_it(self):
        roles = [CustomUser.Role.ADMINISTRATOR, CustomUser.Role.FACULTY, CustomUser.Role.STUDENT, CustomUser.Role.ALUMNI]
        for i, role in enumerate(roles):
            self.client.force_login(make_user(f"u{i}@ue.edu.ph", role))
            for name in LAB_PAGES:
                r = self.client.get(reverse(name))
                self.assertIn(r.status_code, (302, 404), f"{role} {name}")
                self.assertNotIn(b"Recommendations Lab", r.content)

    def test_anonymous_is_sent_to_login(self):
        r = self.client.get(reverse("recs_lab"))
        self.assertEqual(r.status_code, 302)

    def test_no_link_to_the_lab_in_the_normal_site(self):
        dev = make_user("dev2@ue.edu.ph", CustomUser.Role.DEVELOPER)
        self.client.force_login(dev)
        r = self.client.get("/", follow=True)
        self.assertNotIn(b"/recs-lab/", r.content)


class TaxonomyTests(IsolatedDataMixin, TestCase):
    def test_rule_tags(self):
        self.assertEqual(taxonomy.rule_tag("Python"), ("language", "lang-general"))
        self.assertEqual(taxonomy.rule_tag("React")[0], "framework")
        self.assertEqual(taxonomy.rule_tag("Agile")[0], "practice")
        self.assertEqual(taxonomy.rule_tag("JSON")[0], "concept")
        self.assertEqual(taxonomy.rule_tag("Cloud Computing")[0], "concept")

    def test_manual_tag_wins_and_reset_restores_rules(self):
        taxonomy.set_tag("Python", "tool", "", source="manual")
        self.assertEqual(taxonomy.tag("Python")["kind"], "tool")
        taxonomy.clear_tag("Python")
        self.assertEqual(taxonomy.tag("Python")["kind"], "language")

    def test_gemini_never_overwrites_manual_tags(self):
        taxonomy.set_tag("Python", "tool", "", source="manual")
        answer = {"skills": [{"skill": "Python", "kind": "language", "family": "lang-general"},
                             {"skill": "Jira", "kind": "tool", "family": "pm-tools"}]}
        with mock.patch.object(gemini, "_ask", return_value=answer) as ask:
            res = gemini.tag_skills(["Python", "Jira"])
        self.assertNotIn("Python", ask.call_args[0][1].split("Skills:\n", 1)[1])
        self.assertEqual(res["tagged"], 1)
        self.assertEqual(taxonomy.tag("Python")["kind"], "tool")
        self.assertEqual(taxonomy.tag("Jira")["source"], "gemini")


class BlueprintTests(IsolatedDataMixin, TestCase):
    def test_fundamentals_has_one_language_slot(self):
        bp = blueprints.get("CCS 1101")
        self.assertEqual(bp["status"], "auto")
        langs = [s for s in bp["slots"] if s["family"] == "lang-general"]
        self.assertEqual(len(langs), 1)
        self.assertEqual(langs[0]["count"], 1)
        self.assertFalse(langs[0]["optional"])

    def test_save_approve_reset(self):
        bp, problems = blueprints.from_text({"core": "Debugging | bug fixing | applied\nLoops", "slots":
                                             "Language | lang-general | 1 | required | Python, Java",
                                             "extensions": "Git", "out_of_scope": "A second language", "notes": "x"})
        self.assertEqual(problems, [])
        blueprints.save("CCS 1101", bp)
        got = blueprints.get("CCS 1101")
        self.assertEqual(got["status"], "draft")
        self.assertEqual([c["name"] for c in got["core"]], ["Debugging", "Loops"])
        self.assertEqual(got["core"][0]["target"], "applied")
        blueprints.approve("CCS 1101")
        self.assertEqual(blueprints.get("CCS 1101")["status"], "approved")
        blueprints.reset("CCS 1101")
        self.assertEqual(blueprints.get("CCS 1101")["status"], "auto")

    def test_gemini_draft_is_saved_as_draft(self):
        answer = {"core": [{"name": "Debugging", "also": [], "target": "practiced"}], "slots": [],
                  "extensions": [], "out_of_scope": [], "notes": "Logic first."}
        with mock.patch.object(gemini, "_ask", return_value=answer):
            gemini.draft_blueprint("CCS 1101")
        got = blueprints.get("CCS 1101")
        self.assertEqual((got["status"], got["source"]), ("draft", "gemini"))

    def test_gemini_failure_shows_a_message(self):
        self.client.force_login(make_user("dev@ue.edu.ph", CustomUser.Role.DEVELOPER))
        with mock.patch.object(gemini, "_ask", side_effect=gemini.LabGeminiError("Gemini is busy.")):
            r = self.client.post(reverse("recs_lab_blueprints"), {"subject": "CCS 1101", "action": "gemini"}, follow=True)
        self.assertContains(r, "Gemini is busy.")
        self.assertEqual(blueprints.get("CCS 1101")["status"], "auto")


class FacultyTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        prof = make_user("prof@ue.edu.ph", CustomUser.Role.FACULTY)
        R.objects.create(respondent_type=R.PROFESSOR, user=prof, data={"subjects": [
            {"code": "CCS 1101", "name": "Fundamentals of Programming",
             "skills": [{"name": "Python", "level": "Applied"}, {"name": "Debugging", "level": "Introduced"}]}]})
        for i in range(4):
            u = make_user(f"s{i}@ue.edu.ph", CustomUser.Role.STUDENT)
            R.objects.create(respondent_type=R.STUDENT, user=u, data={"personal_info": {"course": "BSCS"}, "subjects": [
                {"code": "CCS 1101", "name": "Fundamentals of Programming",
                 "skills": [{"name": "Python", "level": "Practiced"},
                            {"name": "Debugging", "level": "Practiced" if i == 0 else "Introduced"}]}]})
        self.prof = prof

    def test_language_slot_filled_and_no_second_language(self):
        v = engine.faculty_view("CCS 1101", self.prof.pk)
        lang = next(s for s in v["slots"] if s["family"] == "lang-general")
        self.assertEqual(lang["status"], "filled")
        self.assertIn("Python", lang["filled"])
        self.assertIn("No second", lang["why"])
        for r in v["rows"]:
            self.assertNotIn(r["item"], ("Java", "C++", "C"))

    def test_debugging_not_landing(self):
        v = engine.faculty_view("CCS 1101", self.prof.pk)
        dbg = next(r for r in v["core"] if r["item"] == "Debugging")
        self.assertEqual(dbg["status"], "not_landing")
        self.assertEqual((dbg["strong"], dbg["n"]), (1, 4))
        self.assertEqual(v["cards"][0]["status"], "not_landing")


class AdminGapTests(IsolatedDataMixin, TestCase):
    def test_members_keep_their_own_share(self):
        res = engine.admin_gaps(entry_only=False, floor=0.5)
        if not res["exists"]:
            self.skipTest("No extracted job data in this checkout.")
        d = engine.demand("", entry_only=False)
        for row in res["all_rows"]:
            for m in row["members"]:
                self.assertEqual(m["pct"], d["pct"][m["key"]])
            self.assertEqual(row["demand"], max(m["pct"] for m in row["members"]))
        gaps = [r["gap"] for r in res["rows"]]
        self.assertEqual(gaps, sorted(gaps, reverse=True))
        self.assertLessEqual(len(res["rows"]), 10)


class ResourceTests(IsolatedDataMixin, TestCase):
    ANSWER = {"resources": [
        {"type": "course", "name": "Intro to Git", "provider": "Coursera", "link": "https://example.org/git", "cost": "audit",
         "level": "beginner", "why": "Start here."},
        {"type": "practice", "name": "Branching game", "provider": "Example", "link": "https://game.example.org/",
         "cost": "free", "level": "beginner", "why": "Practice."},
        {"type": "certification", "name": "Fake Cert", "provider": "X", "link": "https://dead.example.org/cert", "cost": "paid"},
        {"type": "weird thing", "name": "No link"},
    ]}

    def setUp(self):
        from django.test import override_settings
        self._no_thread = override_settings(RECS_LAB_WORKER_AUTOSTART=False)   # before the data-dir override,
        self._no_thread.enable()                                               # so they unwind in order
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self._no_thread.disable()

    def _patches(self):
        from ..recs_lab import resources
        verdict = lambda link, name: "dead" if "dead" in link else "ok"  # noqa: E731
        return [mock.patch.object(resources.recommendations, "verify_resource", side_effect=verdict),
                mock.patch.object(resources, "_homepage_verdict", return_value="ok"),
                mock.patch.object(resources, "page_image", side_effect=lambda link: "https://img.example.org/a.png"
                                  if "git" in link else "")]

    def test_find_checks_links_and_takes_pictures_from_the_page(self):
        from ..recs_lab import resources
        sp = resources.spec("start", "Git", "Back-End Developer")
        p = self._patches()
        for x in p:
            x.start()
            self.addCleanup(x.stop)
        items = resources.find(sp, ask=lambda system, prompt: self.ANSWER)
        self.assertEqual([i["name"] for i in items], ["Intro to Git", "Branching game"])   # dead link + no link dropped
        self.assertEqual(items[0]["image"], "https://img.example.org/a.png")
        self.assertEqual(items[1]["image"], "")              # no picture -> the page shows the icon tile
        self.assertEqual(items[0]["cost"], "audit")

    def test_prompt_depends_on_purpose(self):
        from ..recs_lab import resources
        seen = {}

        def ask(system, prompt):
            seen["p"] = prompt
            return self.ANSWER
        for x in self._patches():
            x.start()
            self.addCleanup(x.stop)
        resources.find(resources.spec("class_landing", "Debugging", "CCS 1101"), ask=ask)
        self.assertIn("classroom activities", seen["p"])
        self.assertIn("Not courses for the professor", seen["p"])

    def test_queue_and_worker_save_results_once_per_need(self):
        from ..recs_lab import resources, worker
        for x in self._patches():
            x.start()
            self.addCleanup(x.stop)
        a = resources.spec("start", "Git")
        self.assertEqual(worker.enqueue([a, a, resources.spec("start", "git")]), 1)   # same skill key: one request
        calls = []
        out = worker.process(ask=lambda s, p: calls.append(p) or self.ANSWER, pace=0)
        self.assertEqual(out, "1 found, 0 failed.")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(resources.items_for(a["key"], limit=5)), 2)
        self.assertEqual(worker.enqueue([a]), 0)   # saved now, so not queued again

    def test_no_api_key_leaves_the_job_queued(self):
        from ..recs_lab import resources, worker
        worker.enqueue([resources.spec("start", "Docker")])

        def ask(system, prompt):
            raise gemini.LabGeminiError("No Gemini API key is set.")
        self.assertIn("Paused", worker.process(ask=ask, pace=0))
        self.assertEqual(worker.status()["pending"], 1)

    def test_free_first_and_free_only(self):
        from ..recs_lab import resources
        sp = resources.spec("start", "SQL")
        resources.save_entry(sp, [
            {"type": "course", "name": "Paid one", "link": "https://a/1", "cost": "paid", "verified": "ok"},
            {"type": "practice", "name": "Free one", "link": "https://a/2", "cost": "free", "verified": "ok"}])
        self.assertEqual([i["name"] for i in resources.items_for(sp["key"])], ["Free one", "Paid one"])
        self.assertEqual([i["name"] for i in resources.items_for(sp["key"], free_only=True)], ["Free one"])
        resources.hide_item(sp["key"], "https://a/2")
        self.assertEqual([i["name"] for i in resources.items_for(sp["key"])], ["Paid one"])

    def test_student_resources_follow_their_own_language(self):
        """A student with Java at Practiced gets "go further with Java", never a second language."""
        from ..recs_lab import resources
        result = {"role_label": "Back-End Developer", "units": [
            {"status": "met", "pick_skill": "Java", "label": "General-purpose language"},
            {"status": "build_now", "pick_skill": "Git", "label": "Version control"},
            {"status": "coming_up", "pick_skill": "MySQL", "label": "Relational database"}]}
        specs = resources.plan_student(result)
        self.assertEqual([(s["purpose"], s["skill"]) for s in specs],
                         [("deepen", "Java"), ("start", "Git"), ("preview", "MySQL")])

    def test_faculty_plan_follows_status(self):
        from ..recs_lab import resources
        result = {"info": {"code": "CCS 1101", "name": "Fundamentals of Programming"}, "cards": [], "core": [
            {"item": "Debugging", "kind": "Concept", "status": "not_landing"},
            {"item": "Loops", "kind": "Concept", "status": "on_track"},
            {"item": "Pseudocode", "kind": "Concept", "status": "not_reported"}],
            "slots": [{"item": "Language ×1", "kind": "Slot", "status": "open", "options": [{"skill": "Python"}]},
                      {"item": "IDE ×1", "kind": "Slot", "status": "filled", "options": [{"skill": "VS Code"}]}],
            "extensions": [{"item": "Git", "kind": "Extension", "status": "optional"}]}
        got = {(s["purpose"], s["skill"]) for s in resources.plan_faculty(result)}
        self.assertEqual(got, {("class_landing", "Debugging"), ("class_add", "Pseudocode"),
                               ("self_academy", "Python"), ("self_training", "Git")})

    def test_pages_show_saved_resources_and_find_button(self):
        from ..recs_lab import resources, worker
        dev = make_user("dev@ue.edu.ph", CustomUser.Role.DEVELOPER)
        self.client.force_login(dev)
        r = self.client.get(reverse("recs_lab_resources"))
        self.assertEqual(r.status_code, 200)
        sp = resources.spec("class_landing", "Debugging")
        resources.save_entry(sp, [{"type": "tool", "name": "Python Tutor", "link": "https://pythontutor.com/",
                                   "cost": "free", "verified": "ok", "image": ""}])
        r = self.client.get(reverse("recs_lab_resources") + "?who=professor")
        self.assertContains(r, "Python Tutor")
        r = self.client.post(reverse("recs_lab_resources"), {"action": "refresh", "key": sp["key"]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(worker.status()["pending"], 1)

    def test_resources_page_is_developer_only(self):
        self.client.force_login(make_user("fac@ue.edu.ph", CustomUser.Role.FACULTY))
        self.assertIn(self.client.get(reverse("recs_lab_resources")).status_code, (302, 404))


class TagAllTests(IsolatedDataMixin, TestCase):
    def test_runs_batches_until_nothing_is_left_and_never_resends(self):
        from ..recs_lab import tagjob
        names = [f"Skill {i}" for i in range(250)]
        sent = []

        def fake_tag(batch):
            sent.append(list(batch))
            for n in batch[:-1]:              # Gemini skips one name per batch
                taxonomy.set_tag(n, "tool", "", source="gemini")
            return {"tagged": len(batch) - 1, "new_families": [], "tried": batch}
        with mock.patch.object(tagjob, "todo_names", side_effect=lambda skipped=(): [
                n for n in names if taxonomy.tag(n)["source"] == "rules" and taxonomy.key_of(n) not in set(skipped)]):
            self.assertEqual(tagjob.run(tag=fake_tag, pace=0), "done")
        self.assertEqual([len(b) for b in sent], [120, 120, 10])
        flat = [n for b in sent for n in b]
        self.assertEqual(len(flat), len(set(flat)))       # nothing sent twice
        st = tagjob.state()
        self.assertEqual((st["status"], st["done"], st["batches"]), ("done", 247, 3))

    def test_quota_pauses_and_continue_resumes(self):
        from ..recs_lab import tagjob
        names = [f"Skill {i}" for i in range(130)]
        calls = {"n": 0}

        def fake_tag(batch):
            calls["n"] += 1
            if calls["n"] == 2:
                raise gemini.LabGeminiError("Gemini didn't answer: quota")
            for n in batch:
                taxonomy.set_tag(n, "tool", "", source="gemini")
            return {"tagged": len(batch), "new_families": [], "tried": batch}
        todo = lambda skipped=(): [n for n in names if taxonomy.tag(n)["source"] == "rules"]  # noqa: E731
        with mock.patch.object(tagjob, "todo_names", side_effect=todo):
            self.assertEqual(tagjob.run(tag=fake_tag, pace=0), "paused")
            self.assertIn("quota", tagjob.state()["error"])
            self.assertEqual(tagjob.run(tag=fake_tag, pace=0), "done")
        self.assertEqual(tagjob.state()["done"], 130)
