from src.automation.tasks.job_application_manager import detect_site
from src.automation.pages.indeed_jobs_page import IndeedJobsPage
from src.automation.pages.jobs_search_page import JobsSearchPage
from src.core.use_cases.indeed_application_handler import IndeedApplicationHandler
from src.core.use_cases.job_application_handler import JobApplicationHandler


async def run_test_apply(page, job_url: str, resume_text: str, no_submit: bool) -> bool:
    """Apply to a single job URL — no pipeline, no LLM eval.

    Used by the `test-apply` CLI command. Site detected automatically.
    """
    site = detect_site(job_url)
    print(f"Site detected: {site}")

    await page.goto(job_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    if site == "indeed":
        page_obj = IndeedJobsPage(page, job_url)
        btn = await page_obj.get_apply_btn()
        if not btn:
            print("No Apply button found on this Indeed job page.")
            return False
        title = await page_obj.get_job_title() or "Test Job"
        print(f"Applying to: {title}")
        await btn.click()
        await page.wait_for_timeout(1500)
        handler = IndeedApplicationHandler(page, resume=resume_text)
        return await handler.submit(salary_expectation=None, no_submit=no_submit)

    page_obj = JobsSearchPage(page, job_url)
    btn = await page_obj.get_easy_apply_btn()
    if not btn:
        print("No Easy Apply button found on this job page.")
        return False
    title = await page_obj.get_job_title() or "Test Job"
    description = await page_obj.get_job_description() or ""
    print(f"Applying to: {title}")
    await btn.click()
    await page.wait_for_timeout(1500)
    handler = JobApplicationHandler(page, resume=resume_text)
    return await handler.submit_easy_apply(
        job_title=title, job_description=description, no_submit=no_submit
    )
