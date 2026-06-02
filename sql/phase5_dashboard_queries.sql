-- Phase5 dashboard queries
-- Use with SQLite on jobs.db

-- 0. Current detail crawl status overview
select
  detail_status,
  count(*) as cnt
from jobs
group by detail_status
order by cnt desc, detail_status asc;


-- 0.1 Current pending detail jobs
select
  job_id,
  keyword,
  detail_url,
  detail_status,
  detail_error_message,
  detail_last_attempt_at,
  created_at,
  updated_at
from jobs
where detail_status = 'pending'
order by created_at asc
limit 200;


-- 0.2 Current failed detail jobs
select
  job_id,
  keyword,
  detail_url,
  detail_status,
  detail_error_message,
  detail_last_attempt_at,
  updated_at
from jobs
where detail_status in ('blocked', 'login_required', 'parse_failed')
order by detail_last_attempt_at desc, updated_at desc
limit 200;


-- 0.3 Recently succeeded detail jobs
select
  job_id,
  keyword,
  title,
  company_name,
  detail_status,
  detail_last_attempt_at,
  updated_at
from jobs
where detail_status = 'success'
order by detail_last_attempt_at desc, updated_at desc
limit 200;


-- 0.4 Jobs ordered by latest detail attempt
select
  job_id,
  keyword,
  title,
  detail_status,
  detail_error_message,
  detail_last_attempt_at,
  updated_at
from jobs
order by
  case when detail_last_attempt_at is null then 1 else 0 end asc,
  detail_last_attempt_at desc,
  updated_at desc
limit 200;


-- 0.5 Current jobs snapshot joined with latest crawl log
select
  j.job_id,
  j.keyword,
  j.title,
  j.detail_status,
  j.detail_error_message,
  j.detail_last_attempt_at,
  cl.success as last_crawl_success,
  cl.status_code as last_crawl_status_code,
  cl.error_message as last_crawl_error_message,
  cl.created_at as last_crawl_at
from jobs j
left join crawl_log cl
  on cl.id = (
    select cl2.id
    from crawl_log cl2
    where cl2.job_id = j.job_id
    order by cl2.created_at desc, cl2.id desc
    limit 1
  )
order by j.updated_at desc
limit 200;


-- 1. Recent crawl failures grouped by day and error
select
  date(created_at) as day,
  coalesce(error_message, 'UNKNOWN') as error_message,
  count(*) as cnt
from crawl_log
where success = 0
group by date(created_at), coalesce(error_message, 'UNKNOWN')
order by day desc, cnt desc;


-- 2. Recent crawl summary by day
select
  date(created_at) as day,
  count(*) as total_requests,
  sum(case when success = 1 then 1 else 0 end) as success_count,
  sum(case when success = 0 then 1 else 0 end) as failed_count
from crawl_log
group by date(created_at)
order by day desc;


-- 3. Current pending queue sizes
select
  (select count(*) from jobs where detail_status = 'pending') as pending_detail,
  (select count(*) from jobs where clean_status = 0) as pending_clean,
  (
    select count(*)
    from jobs_cleaned
    where need_company_check = 1
      and company_check_status = 'pending'
  ) as pending_enrich,
  (
    select count(*)
    from jobs_cleaned
    where clean_status = 1
      and (score_status is null or score_status <> 1)
  ) as pending_score;


-- 4. Current company enrichment status breakdown
select
  company_check_status,
  count(*) as cnt
from jobs_cleaned
group by company_check_status
order by cnt desc;


-- 5. Current scoring status breakdown
select
  score_status,
  count(*) as cnt
from jobs_cleaned
group by score_status
order by cnt desc;


-- 6. Jobs that still need company enrichment
select
  job_id,
  keyword,
  title,
  company_name,
  company_name_norm,
  company_check_status,
  company_check_reasons_json,
  cleaned_at
from jobs_cleaned
where need_company_check = 1
  and company_check_status = 'pending'
order by cleaned_at asc
limit 100;


-- 7. Jobs ready for scoring but not yet scored
select
  job_id,
  keyword,
  title,
  company_name,
  last_updated,
  days_since_update,
  score_status,
  cleaned_at
from jobs_cleaned
where clean_status = 1
  and (score_status is null or score_status <> 1)
order by cleaned_at asc
limit 100;


-- 7.1 Current detail crawl status counts for frontend cards
select
  sum(case when detail_status = 'pending' then 1 else 0 end) as pending_count,
  sum(case when detail_status = 'success' then 1 else 0 end) as success_count,
  sum(case when detail_status = 'expired' then 1 else 0 end) as expired_count,
  sum(case when detail_status = 'wrong_page' then 1 else 0 end) as wrong_page_count,
  sum(case when detail_status = 'login_required' then 1 else 0 end) as login_required_count,
  sum(case when detail_status = 'blocked' then 1 else 0 end) as blocked_count,
  sum(case when detail_status = 'parse_failed' then 1 else 0 end) as parse_failed_count
from jobs;


-- 8. Final joined result view
select
  c.job_id,
  c.keyword,
  c.title,
  c.company_name,
  c.salary_min,
  c.salary_max,
  c.salary_months,
  c.city,
  c.last_updated,
  c.days_since_update,
  ce.status as company_status,
  ce.risk_level,
  s.total,
  s.verdict,
  s.scored_at
from jobs_cleaned c
left join company_enriched ce on ce.company_name_norm = c.company_name_norm
left join scores s on s.job_id = c.job_id
order by c.cleaned_at desc
limit 200;


-- 9. High-score jobs with company risk attached
select
  c.job_id,
  c.title,
  c.company_name,
  s.total,
  s.verdict,
  ce.risk_level,
  c.salary_min,
  c.salary_max,
  c.last_updated
from jobs_cleaned c
join scores s on s.job_id = c.job_id
left join company_enriched ce on ce.company_name_norm = c.company_name_norm
order by s.total desc, c.cleaned_at desc
limit 100;
