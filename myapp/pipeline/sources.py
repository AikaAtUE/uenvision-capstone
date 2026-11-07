"""
The job sources the Data Extraction page can scrape, in one place.

Adding another source takes three things (Foundit was added this way):
  1. its scraper script in this folder, saving one JSON file per job posting into an
     output folder and taking the search words from a command-line option
     (the options below are the ones Kalibrr's and Trabajo's scrapers already take),
     and recording each job posting it saves or fails to save with failed_saves.Recorder
     (--report-dir), so its failures show up in the failed saves log;
  2. its JSON layout in compile_jobs_to_csv.py (that script's SOURCES table), so the
     JSONs can be compiled into data/compiled_<key>.csv;
  3. one JobSource line in REGISTRY below.
Everything else (the source checkboxes, the scrape / compile / extract steps, View Data,
Import Data, the data/ summary and ghost job detection) reads its list from here.
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobSource:
    key: str            # used in file names: data/jsons/<key>/, data/compiled_<key>.csv
    label: str          # shown on the pages
    site: str           # shown under the label
    scraper: str        # script in this folder
    search_option: str  # the scraper's option for the search words
    parallel: int = 1   # how many of its searches run at the same time (see manager.build_steps)

    def scrape_argv(self, python: str, pipeline_dir: Path, search: str, output_dir: Path,
                    delay_min: float, delay_max: float, max_jobs=None, report_dir=None) -> list[str]:
        argv = [python, "-u", str(pipeline_dir / self.scraper),
                f"{self.search_option}={search}", f"--output-dir={output_dir}",
                f"--delay-min={delay_min}", f"--delay-max={delay_max}"]
        if max_jobs:
            argv.append(f"--max-jobs={max_jobs}")
        if report_dir:
            argv.append(f"--report-dir={report_dir}")
        return argv


REGISTRY = (
    JobSource("kalibrr", "Kalibrr", "kalibrr.com", "kalibrr_scraper.py", "--text"),
    JobSource("trabajo", "Trabajo", "ph.trabajo.org", "trabajo_scraper.py", "--keyword"),
    # Foundit's searches are slow (one detail request per job, at most 100 jobs per search),
    # so 3 run at the same time: about 1 request a second in all, still gentle on the site.
    JobSource("foundit", "Foundit", "foundit.com.ph", "foundit_scraper.py", "--query", parallel=3),
)
BY_KEY = {s.key: s for s in REGISTRY}
