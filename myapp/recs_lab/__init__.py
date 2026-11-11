"""
UEnvision — Recommendations Lab: a second, experimental recommendation system that sits
next to the current one (rec_context.py / gap_analysis.py / recommendations.py), which it
never changes. Only developers can open it, by typing its link; nothing in the site links
to it.

  taxonomy.py    what a skill IS: kind (concept / language / framework / tool / practice)
                 and family (skills that can stand in for each other, e.g. Python / Java / C)
  blueprints.py  what a subject is FOR: core concepts, slots ("one language"), optional
                 extensions, out of scope. Auto-drafted from the curated subject list,
                 optionally re-drafted by Gemini, approved by a developer.
  engine.py      plain code over the blueprints, the survey answers and the job postings:
                 faculty statuses per subject, top curriculum gaps for administrators,
                 slot-aware advice for students and alumni.
  gemini.py      the two Gemini jobs (tag skills, draft a blueprint). Never used for scoring.
  views.py, urls.py   the developer-only pages under /recs-lab/.

Skill counts follow data/extracted_skills.csv and data/hard_skills.csv as they are
(job_roles.it_postings + gap_analysis._tally). A family is only a label on top: every
member keeps its own count and a family is ranked by its highest member, never by a
merged number.

Everything the lab saves lives in data/.state/recs_lab_*.json, so it needs no migration
and removing the lab is deleting this folder, its templates, its CSS and one line in
myapp/urls.py.
"""
