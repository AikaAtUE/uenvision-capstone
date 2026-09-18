# UEnvision

**An Industry-Aligned Curriculum Mapping System Through Job Market Analysis**

> 🚧 **Status: Work in Progress**
> This is an active capstone project for the Bachelor of Science in Data Science program at the University of the East, Manila – College of Computer Studies and Systems (CCSS). The system, methodology, and documentation are still under active development and **will continue to change** as research, testing, and feedback progress. Expect frequent updates to this repository.

## About

UEnvision is a website-based system that helps identify, quantify, and help close the skill gap between what the **IT/CS job market demands** and what **academic curricula** currently teach.

It works by comparing two data sources:
- **Industry data** — technical skills extracted from IT/CS job postings scraped from [Kalibrr](https://www.kalibrr.com)
- **Academic data** — technical competencies expected by UE-CCSS faculty, gathered through structured surveys based on course syllabi

These datasets are cleaned, processed, and compared using skill extraction (NER, TF-IDF, keyword-based methods) and **cosine similarity–based gap score analysis**, with results presented through interactive dashboards to support data-driven curriculum decisions.

## Problem Statement

Graduates in IT and Computer Science programs often face a mismatch between the skills developed in school and the skills employers actually require. This study investigates that gap by answering:

1. What are the most in-demand technical skills for IT/CS professionals, based on Kalibrr job postings collected through web scraping?
2. How can UEnvision identify, quantify, and bridge the skill gap between industry-demanded skills and the technical competencies expected by UE-CCSS faculty?
3. What procedures, methodologies, and tools support the development and deployment of UEnvision — including web scraping, data cleaning, skill extraction/classification, database design, analytics, testing, and deployment?

## Scope and Limitations

- Limited to **UE Manila – College of Computer Studies and Systems (CCSS)**, IT and CS programs; survey respondents are UE-CCSS faculty only
- Job market data sourced exclusively from **Kalibrr**, scraped twice a month
- Filters out **ghost jobs** and duplicate postings to ensure data validity
- Focused strictly on **technical skill alignment** — not broader labor market policy, mobile apps, or non-web platforms

## Key Features (Planned / In Development)

- Automated, scheduled web scraping of Kalibrr job postings
- Ghost job detection and filtering
- PII removal and anonymization (compliant with RA 10173 – Data Privacy Act of 2012)
- Skill extraction using keyword-based methods, TF-IDF, and Named Entity Recognition (NER)
- Skill categorization and mapping to academic competencies
- Faculty survey collection and processing
- Cosine similarity–based gap score computation
- Interactive dashboards (bar graphs, heatmaps, word clouds, network diagrams, gauge graphs)
- Role-based access (Admin, Faculty, Guest)

## Tech Stack

| Layer | Tools |
|---|---|
| Scraping & NLP | Python, web scraping libraries, NLP/NER tools |
| Data Processing | Pandas, TF-IDF, skill classification models |
| Database | SQL (relational) |
| Visualization | Interactive dashboards |
| Survey Collection | Google Forms / Sheets |
| Skill Reference | National (CHED) and commercial skill taxonomies |

*(Full tooling and environment details are documented in Chapter 3 of the project paper and will be reflected here as implementation progresses.)*

## Research Team

**Adviser:** Sheila M. Geronimo

**Researchers:**
- Cirineo, Jann Justine C.
- Federizo, Ryan-Ver S.
- Pantoja, Miradel Jan A.
- Roxas, Raphael D.G.
- Rueco, Aika Lynn S.

*College of Computer Studies and Systems, University of the East, Manila*

## Compliance & Ethics

This project adheres to Kalibrr's Terms of Use and Privacy Policy, the Data Privacy Act of 2012 (RA 10173), and relevant provisions of the Intellectual Property Code (RA 8293). Only publicly available, non-personal job posting data is collected, and it is used strictly for academic research purposes.

---

*This README will be revised throughout development, testing, and defense — check back for the latest version.*
