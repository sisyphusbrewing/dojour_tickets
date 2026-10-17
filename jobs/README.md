# Jobs

The job post and application form, served by GitHub Pages and embedded on
the site:

    https://www.sisyphusbrewing.com/pages/jobs

The Shopify page "Jobs" (handle `jobs`) iframes `jobs/index.html`; its body
is in `jobs/shopify-page.html`.

1. Someone fills in the form. Answers save on their device as they type.
2. **Apply** uploads the résumé (optional) to the private Supabase bucket
   `jobs` and saves the answers with `job_apply()` into
   `public.job_applications`.
3. The form calls the `job-applied` edge function, which starts the
   "Job application" action (`job_notify.yml` → `job_notify.py`). That emails
   booking@sisyphusbrewing.com with the answers and the résumé attached,
   Reply-To the applicant. Set the repo variable `JOBS_EMAIL_TO` to send them
   somewhere else.

Questions live in `jobs/fields.js`; the form and the email both read it.
The post itself (the job, who we want) is plain HTML at the top of
`jobs/index.html`. `?role=` is saved with each application, for when it is
not bartenders.
