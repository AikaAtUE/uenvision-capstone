-- ==========================================================================
-- UEnvision — Feedback & Survey tables
-- --------------------------------------------------------------------------
-- Run this once in your Supabase project's SQL Editor (Dashboard -> SQL
-- Editor -> New query -> paste this whole file -> Run). It creates the three
-- tables the Feedback page writes to, and locks them down with Row Level
-- Security so that anyone using your public "anon" key can SUBMIT a survey
-- but cannot read, edit, or delete anyone else's responses. You (the project
-- owner) can still see every row in the Supabase Table Editor, since that
-- view uses your own login, not the anon key.
-- ==========================================================================

-- ---------- System Usability Scale (SUS) ----------
create table if not exists sus_responses (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  respondent_role text,
  program text,
  q1 smallint check (q1 between 1 and 5),
  q2 smallint check (q2 between 1 and 5),
  q3 smallint check (q3 between 1 and 5),
  q4 smallint check (q4 between 1 and 5),
  q5 smallint check (q5 between 1 and 5),
  q6 smallint check (q6 between 1 and 5),
  q7 smallint check (q7 between 1 and 5),
  q8 smallint check (q8 between 1 and 5),
  q9 smallint check (q9 between 1 and 5),
  q10 smallint check (q10 between 1 and 5),
  sus_score numeric(5,2),
  comments text
);

alter table sus_responses enable row level security;

create policy "Anyone can submit a SUS response"
  on sus_responses for insert
  to anon
  with check (true);

-- ---------- User Acceptance Testing (UAT) ----------
create table if not exists uat_responses (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  tester_name text,
  tester_role text,
  program text,
  test_date date,
  login_worked text,
  dashboard_worked text,
  filter_worked text,
  export_worked text,
  settings_worked text,
  satisfaction smallint check (satisfaction between 1 and 5),
  comments text
);

alter table uat_responses enable row level security;

create policy "Anyone can submit a UAT response"
  on uat_responses for insert
  to anon
  with check (true);

-- ---------- Functional test case sheet ----------
create table if not exists functional_test_results (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  submission_id uuid not null,
  tester_name text,
  test_case_id text,
  feature text,
  steps text,
  expected_result text,
  actual_result text,
  status text check (status in ('Pass', 'Fail', 'Blocked')),
  notes text
);

alter table functional_test_results enable row level security;

create policy "Anyone can submit functional test results"
  on functional_test_results for insert
  to anon
  with check (true);

-- --------------------------------------------------------------------------
-- Optional: if you (as faculty/admin) want to read the results from inside
-- the app later instead of only via the Supabase dashboard, add a SELECT
-- policy restricted to logged-in users, e.g.:
--
--   create policy "Authenticated users can read SUS responses"
--     on sus_responses for select
--     to authenticated
--     using (true);
--
-- Repeat for the other two tables as needed.
-- --------------------------------------------------------------------------
