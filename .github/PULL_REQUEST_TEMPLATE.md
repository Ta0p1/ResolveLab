## What and why

<!-- One paragraph: the change, and the problem it solves. -->

## Evidence rules

- [ ] `pytest -q`, `ruff check .` and `ruff format --check .` pass.
- [ ] `python scripts/verify_http_study.py` and
      `python scripts/verify_casedesk_v2.py --dagger-every 20 --replay-every 10` pass.
- [ ] No locked source file changed. New behaviour lives in new modules; the audits list the
      locked files.
- [ ] No published result, lock, manifest or trace was edited. A correction is documented next
      to the unchanged evidence.
- [ ] Any new number names its pool (dev or test), denominator, seeds and models, and says
      whether it was registered in advance. Nothing was tuned on the test pool.

## How it was checked

<!-- Commands run, episodes or traces looked at, and anything not verified. -->
