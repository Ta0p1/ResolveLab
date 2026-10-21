"""Real-browser UI smoke checks. Run against an isolated preview server."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    parser.add_argument("--channel", default=None)
    args = parser.parse_args()
    output = Path("artifacts/browser")
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=args.channel)
        context = browser.new_context(viewport={"width": 1536, "height": 1040}, device_scale_factor=1)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url)
        expect(page.locator(".scenario")).to_have_count(10)
        page.locator('[data-id="compound"]').click()
        page.locator("#run-button").click()
        expect(page.locator("#run-status")).to_have_text("Resolved", timeout=15000)
        expect(page.locator("#verdict")).to_contain_text("Recovery verified.")
        page.locator(".trace-item").first.click()
        expect(page.locator(".trace-item").first.locator("pre")).to_be_visible()
        with page.expect_download() as downloaded:
            page.locator("#export-button").click()
        trace = Path(downloaded.value.path()).read_text()
        assert json.loads(trace.splitlines()[0])["verdict"]["passed"]
        page.screenshot(path=str(output / "workbench-desktop.png"), full_page=True)
        page.locator('[data-id="lost_response"]').click()
        page.locator("#policy").select_option("naive")
        page.locator("#run-button").click()
        expect(page.locator("#run-status")).to_have_text("Failed check", timeout=15000)
        expect(page.locator("#verdict")).to_contain_text("did not pass verification")
        page.locator('[data-id="read_only"]').click()
        page.locator("#policy").select_option("reference")
        page.locator("#run-button").click()
        expect(page.locator("#run-status")).to_have_text("Escalated", timeout=15000)
        page.locator('[data-page="evaluations"]').click()
        page.locator("#eval-suite").select_option("smoke")
        with page.expect_response(
            lambda response: (
                response.url.endswith("/api/evaluations") and response.request.method == "POST"
            )
        ) as started:
            page.locator("#eval-button").click()
        evaluation_id = started.value.json()["id"]
        expect(page.locator("#report-select")).to_have_value(evaluation_id)
        expect(page.locator(".results-header .pill")).to_have_text("completed", timeout=20000)
        with page.expect_download() as downloaded:
            page.locator("#download-report").click()
        report = json.loads(Path(downloaded.value.path()).read_text())
        assert report["completed"] == 6
        assert next(s for s in report["summary"] if s["policy"] == "reference")["passed"] == 3
        page.screenshot(path=str(output / "evaluations-desktop.png"), full_page=True)
        page.locator(".episode-table tbody tr").last.click()
        expect(page.locator("#page-label")).to_have_text("Workbench")
        page.locator('[data-page="guide"]').click()
        expect(page.get_by_role("heading", name="From a claim to a check.")).to_be_visible()
        page.locator('[data-page="experiments"]').click()
        expect(page.get_by_role("heading", name="Held-out composition test")).to_be_visible()
        expect(page.locator("#experiment-results tbody tr")).to_have_count(12)
        with page.expect_download() as downloaded:
            page.get_by_role("link", name="Download evidence").click()
        evidence = json.loads(Path(downloaded.value.path()).read_text())
        assert evidence["comparison"]["paired_episodes"] == 24
        page.screenshot(path=str(output / "post-training-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / "post-training-mobile.png"), full_page=True)
        page.locator('[data-page="http-study"]').click()
        page.set_viewport_size({"width": 1536, "height": 1040})
        expect(page.get_by_role("heading", name="Same grammar. Different decisions.")).to_be_visible()
        expect(page.locator("#http-study-results table").first.locator("tbody tr")).to_have_count(5)
        expect(page.locator("#http-case option")).to_have_count(30)
        page.locator("#http-model").select_option("sft-3407-test")
        expect(page.locator("#http-case option")).to_have_count(30)
        page.locator("#http-trace .http-action summary").first.click()
        expect(page.locator("#http-trace .http-action").first.locator("pre").first).to_be_visible()
        with page.expect_download() as downloaded:
            page.get_by_role("link", name="Download HTTP evidence").click()
        http_evidence = json.loads(Path(downloaded.value.path()).read_text())
        assert len(http_evidence["reports"]) == 5
        assert sum(len(r["rows"]) for r in http_evidence["reports"].values()) == 150
        assert len(http_evidence["supplementary"]["rows"]) == 30
        for index, report in enumerate(http_evidence["reports"].values()):
            row = page.locator("#http-study-results table").first.locator("tbody tr").nth(index)
            summary = report["summary"]
            expect(row.locator("td").nth(1)).to_contain_text(f"{summary['passed']}/30")
            expect(row.locator("td").nth(2)).to_have_text(f"{100 * summary['schema_valid_rate']:.1f}%")
            expect(row.locator("td").nth(3)).to_have_text(str(summary["unsafe_mutations"]))
            expect(row.locator("td").nth(4)).to_have_text(str(summary["false_successes"]))
        page.locator("#http-model").select_option("ollama-4b-test")
        expect(page.locator("#http-case option")).to_have_count(30)
        page.locator("#http-model").select_option("sft-3407-test")
        page.screenshot(path=str(output / "http-study-desktop.png"), full_page=True)
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(output / "http-study-overview.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / "http-study-mobile.png"), full_page=True)
        page.locator('[data-page="workbench"]').click()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / "workbench-mobile.png"), full_page=True)
        assert not errors, errors
        (output / "checks.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "browser": browser.version,
                    "checks": [
                        "verified recovery",
                        "trace details",
                        "JSONL download",
                        "false claim rejected",
                        "read-only escalation",
                        "evaluation from UI",
                        "report download",
                        "episode navigation",
                        "guide navigation",
                        "post-training results and evidence download",
                        "post-training mobile overflow",
                        "HTTP study five model arms and 150 episodes",
                        "supplementary 4B control and 30 episodes",
                        "HTTP model/case selection and request details",
                        "HTTP evidence download",
                        "HTTP displayed scores match downloaded evidence",
                        "HTTP study mobile overflow",
                        "mobile overflow",
                        "no JS exceptions",
                    ],
                },
                indent=2,
            )
        )
        browser.close()
    print("Browser smoke checks passed; screenshots and report saved to artifacts/browser.")


if __name__ == "__main__":
    main()
