from pathlib import Path as _Path


def read_resume_text(resume_path: str) -> str:
    rp = _Path(resume_path)
    if rp.suffix.lower() == ".pdf":
        from pypdf import PdfReader as _PdfReader
        return "\n".join(p.extract_text() or "" for p in _PdfReader(resume_path).pages)
    return rp.read_text(encoding="utf-8")


async def run_test_apply_browser(page, job_url: str, resume_text: str, no_submit: bool) -> bool:
    from src.automation.tasks.job_application_manager import _detect_site
    site = _detect_site(job_url)
    print(f"Site detected: {site}")

    await page.goto(job_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    if site == "indeed":
        from src.automation.pages.indeed_jobs_page import IndeedJobsPage
        from src.core.use_cases.indeed_application_handler import IndeedApplicationHandler
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
    else:
        from src.automation.pages.jobs_search_page import JobsSearchPage
        from src.core.use_cases.job_application_handler import JobApplicationHandler
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
        return await handler.submit_easy_apply(job_title=title, job_description=description, no_submit=no_submit)
