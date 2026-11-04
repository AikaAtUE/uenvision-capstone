def login_administrator(client):
    """Students/alumni answer their survey logged in as themselves; tests that only look at
    the survey pages or post made-up "About you" answers do it as an administrator
    trying the survey out (who sees and fills in every field)."""
    from ..models import CustomUser
    user = CustomUser.objects.filter(email="tester-admin@ue.edu.ph").first() or CustomUser.objects.create_user(
        email="tester-admin@ue.edu.ph", password="secret123", first_name="Test", last_name="Admin",
        role=CustomUser.Role.ADMINISTRATOR)
    client.force_login(user)
    return user


class IsolatedDataMixin:
    """Points DATA_DIR at a temporary copy of data/ (ontology + extracted skills) so
    tests that add custom skills or seed curated ones never touch the real files."""
    def setUp(self):
        import shutil, tempfile
        from pathlib import Path
        from django.conf import settings
        from django.test import override_settings
        from .. import job_roles, ontology, skills_catalog
        super().setUp()
        self._tmp = tempfile.mkdtemp()
        real = Path(settings.DATA_DIR)
        (Path(self._tmp) / "ontology").mkdir()
        shutil.copy(real / "ontology" / "mind_tech_ontology.csv", Path(self._tmp) / "ontology")
        if (real / "extracted_skills.csv").is_file():
            shutil.copy(real / "extracted_skills.csv", self._tmp)
        self._override = override_settings(DATA_DIR=Path(self._tmp))
        self._override.enable()
        skills_catalog._ENTRIES = None
        skills_catalog._CURATED_DONE = False
        job_roles._CACHE.update(key=None, value=None)
        ontology.subject_skill_map.cache_clear()

    def tearDown(self):
        import shutil
        from .. import job_roles, ontology, skills_catalog
        self._override.disable()
        shutil.rmtree(self._tmp, ignore_errors=True)
        skills_catalog._ENTRIES = None
        skills_catalog._CURATED_DONE = False
        job_roles._CACHE.update(key=None, value=None)
        ontology.subject_skill_map.cache_clear()
        super().tearDown()
