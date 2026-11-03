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
