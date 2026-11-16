# UEnvision

**An Industry-Aligned Curriculum Mapping System Through Job Market Analysis**

**Live site:** [https://uenvision.tech/](https://uenvision.tech/)

> **Status: Thesis defended (November 14, 2026)**
> UEnvision is a capstone project of BS Data Science students at the University of the East, Manila, College of Computer Studies and Systems (CCSS). The thesis was defended on **November 14, 2026**. The system is deployed and running at [uenvision.tech](https://uenvision.tech/).
> The capstone paper is still being updated after the defense, so parts of this README may change as the final paper is completed.

## About

UEnvision is a web-based system that identifies, measures, and helps close the gap between the technical skills the **IT/CS job market asks for** and the skills the **UE-CCSS BSIT and BSCS curricula** actually teach.

It compares two kinds of data:

- **Industry data:** hard (technical) skills extracted with Google Gemini from IT/CS job postings scraped from [Kalibrr](https://www.kalibrr.com), [Trabajo.org](https://ph.trabajo.org), and [Foundit](https://www.foundit.com.ph). The job searches follow the expected job roles of graduates in CHED Memorandum Order No. 25, s. 2015.
- **Academic data:** curriculum-mapping surveys answered by UE-CCSS faculty (what they teach in each subject, and how deeply), and by students and fresh-graduate alumni (what they learned, and how well), built on the real BSIT/BSCS subject list.

The two are compared with a **depth-weighted, cosine-similarity alignment score**, and the results are shown in interactive dashboards, a skill gap report, and learning and training recommendations to support data-driven curriculum decisions.

## Research Questions

1. What are the most in-demand technical skills for IT/CS professionals, based on job postings collected through web scraping?
2. How can UEnvision identify, quantify, and help bridge the gap between industry-demanded skills and the technical competencies taught at UE-CCSS?
3. What procedures, methodologies, and tools support the development and deployment of UEnvision, including web scraping, data cleaning, skill extraction, database design, analytics, testing, and deployment?

## Scope and Limitations

- Limited to **UE Manila, CCSS**, BSIT and BSCS programs. Survey respondents are UE-CCSS faculty, students, and fresh-graduate alumni.
- Job market data comes from **Kalibrr, Trabajo.org, and Foundit**. Public job datasets (for example, Djinni) can be imported for reference, but they are kept out of the Dashboard and all results unless a user ticks them in.
- Only **tech postings** (postings Gemini marks as tech jobs) and only **hard skills** are counted in the results. Soft skills are extracted but are not part of the gap score.
- Skill names are counted **as written** in the extracted data. Only capitalization, spacing, and punctuation are ignored; skills are not fuzzy-matched when results are shown.
- **Possible ghost jobs** are flagged, never deleted. Users can switch on "Exclude possible ghost jobs" to leave them out of every result.
- Focused on **technical skill alignment**. Broader labor market policy, mobile apps, and non-web platforms are out of scope.

## How It Works

```
Job boards ──scrape──> one JSON per posting ──compile──> compiled_<source>.csv
   ──Gemini extract──> extracted_skills.csv ──standardize──> hard skills mapped to ontology names
   ──> hard_skills.csv / soft_skills.csv (tech postings only)
   ──> Homepage, Dashboard, Job Market, Gap Analysis, Recommendations

Curriculum surveys ──> Gap Analysis (vs. job postings) ──> Subject skill profiles
   ──> Context-aware recommendations ──> Gemini finds resources, every link is checked
```

1. **Scrape:** Kalibrr, Trabajo.org, and Foundit scrapers save one JSON file per posting, searching the locked CHED role list plus any extra searches an administrator adds.
2. **Compile:** each source's JSON files become one CSV. Trabajo.org reposts (the same ad under several cities or feeds) are merged into a single posting.
3. **Extract:** Google Gemini reads each posting and lists its hard skills, soft skills, certifications, experience level, education, and whether it is a tech job (and whether it fits Computer Science, Information Technology, or both).
4. **Standardize:** hard skills are mapped to standard names from the [MIND Tech Skills Ontology](https://github.com/MIND-TechAI/MIND-tech-ontology) and a custom skill list. The original wording is kept alongside.
5. **Ghost job check:** postings are flagged when the same job appears twice under different IDs, or when enough weak signs apply together (hidden salary, very short description, unverified company).
6. **Automation:** the whole pipeline can run on a schedule (every N days or on chosen weekdays, Philippine time), checked every 5 minutes by a systemd timer on the server.

### Gap analysis method

For the top 10, 20, or 30 most in-demand hard skills:

- **Industry side:** how many tech postings mention each skill.
- **Academic side:** a depth-weighted coverage per skill. Faculty rate how a skill is taught (Introduced = 1/3, Practiced = 2/3, Applied = 1). Students and alumni rate how proficient they became (Beginner = 0.25 up to Expert = 1).
- **Alignment score:** the cosine similarity of the two vectors, shown as a percentage. The report also lists under-taught and well-covered skills, a per-subject breakdown, and a side-by-side view of what faculty say they teach versus what students and alumni say they learned.

Results can be filtered by program (BSIT, BSCS, or both), job source, and experience level.

## Features

**For everyone (public)**
- Homepage with the top in-demand skills and a quick "check my skill gap" tool for a chosen job role

**Students and alumni**
- Curriculum survey (student or alumni version), saved per account, with drafts and editing
- **My skill gap:** personal gap against a target job role, with learning recommendations
- **My subjects and skills:** view and update the subjects and skills they reported

**Faculty**
- Professor curriculum survey (required before using the rest of the site)
- **Dashboard:** top in-demand skills, skill trends, and the skill gap report
- **Job Market:** postings over time, rising and falling skills, salary by experience level, work mode, and city
- **Recommendations:** training resources for under-taught skills in their subjects
- **View Data:** read and download the datasets

**Administrators**
- Everything faculty can do, plus **Accounts** (create, approve, edit, reset passwords, move to student), **Notifications**, **Import Data**, **Data Extraction** (sources, searches, steps, ghost job settings, automation), **Console** (live run log), **Survey Responses** (with CSV download), and recommendation settings

**Developers**
- Administrator access, with their own answers saved as dummy data, plus view switches (Real/Dummy data; Faculty/Student/Alumni view), the Survey Tracker, and editing of the Feedback forms

**Across the site**
- Email/password accounts and **Continue with Google** sign-in, email verification, and password reset
- **Feedback page:** System Usability Scale (SUS), User Acceptance Testing (UAT, Likert scale), and the Functional test case sheet, all built into the site
- Onboarding tour for first-time users, light and dark mode, profile photos, a 30-minute idle timeout, and email logging on the server

## Tech Stack

| Layer | Tools |
|---|---|
| Web application | Django 5.2 (Python), plain JavaScript and CSS (no build step) |
| Authentication | Django auth, django-allauth (Google sign-in) |
| Scraping | requests, BeautifulSoup, lxml |
| Skill extraction and standardization | Google Gemini (`google-genai`), rapidfuzz, MIND Tech Skills Ontology |
| Data processing | pandas, pydantic |
| Database | SQLite through the Django ORM |
| Server | Hostinger Ubuntu VPS: nginx, gunicorn, systemd (service and automation timer) |
| Testing | Django test framework, about 550 automated tests in `myapp/tests/` |

## Running Locally

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

No `.env` file is needed locally: DEBUG is on, the database is SQLite, and emails print to the console.

| Task | Command |
|---|---|
| Run all tests | `python manage.py test myapp` |
| Run the automation check now | `python manage.py run_automation --now` |
| Process the recommendation queue | `python manage.py process_recommendations` |
| Rebuild subject skill profiles | `python manage.py rebuild_subject_profiles` |
| Run the ghost job check | `python manage.py ghost_job_check` |

The job datasets (`data/`), the database (`db.sqlite3`), Gemini API keys, and `.env` are **not** in this repository. The live data exists only on the server. The one data file kept in git is `data/ontology/mind_tech_ontology.csv`.

## Project Structure

```
UEnvision/        Django settings and root URLs
myapp/
  views/          page views (dashboard, data, surveys, feedback, accounts, ...)
  pipeline/       scrapers, compiler, Gemini extraction and standardization, run manager
  management/     scheduled commands (automation, recommendations, ghost jobs)
  templates/      HTML templates
  static/myapp/   JavaScript and CSS
  tests/          automated tests
deploy/           server setup files and guides
data/ontology/    MIND Tech Skills Ontology (CSV)
```

## Deployment

The production setup (Hostinger Ubuntu VPS with nginx, gunicorn, and systemd) is described step by step in [deploy/DEPLOY.md](deploy/DEPLOY.md), with security steps in [deploy/SECURITY-STEPS.md](deploy/SECURITY-STEPS.md). Updates are applied with `deploy/update.sh`, which backs up the database, pulls the latest code, installs requirements, runs migrations, collects static files, and restarts the site.

## Research Team

**Adviser:** Dr. Sheila M. Geronimo

**Researchers:**
- Cirineo, Jann Justine C.
- Federizo, Ryan-Ver S.
- Pantoja, Miradel Jan A.
- Roxas, Raphael D.G.
- Rueco, Aika Lynn S.

*College of Computer Studies and Systems, University of the East, Manila*

## Compliance and Ethics

This project follows the Terms of Use and Privacy Policies of the job boards it collects from, the Data Privacy Act of 2012 (RA 10173), and relevant provisions of the Intellectual Property Code (RA 8293). Only publicly available, non-personal job posting data is collected, and it is used strictly for academic research. Test (dummy) survey answers are always kept separate from real results.

## Acknowledgments

- [MIND Tech Skills Ontology](https://github.com/MIND-TechAI/MIND-tech-ontology) (MIT License), used to standardize skill names and suggest skills per subject.
- CHED Memorandum Order No. 25, s. 2015, for the expected job roles of BSIT and BSCS graduates.
