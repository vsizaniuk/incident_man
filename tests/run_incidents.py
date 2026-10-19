import json
import sys
import time
from pathlib import Path

import httpx

INCIDENTS_FILE = Path(__file__).with_name("incidents.json")
DEFAULT_URL = "http://localhost:8000/incidents/classify"
# a request may go through several generation attempts
REQUEST_TIMEOUT = 900


def check(case: dict, response: httpx.Response) -> list[str]:
    if response.status_code != httpx.codes.OK:
        return [f"HTTP {response.status_code}: {response.text[:300]}"]
    body = response.json()
    problems = []
    if not body["category"].startswith(f"[{case['expected_prefix']}]"):
        problems.append(f"expected prefix [{case['expected_prefix']}]")
    if body["severity"] not in case["expected_severity"]:
        problems.append(f"expected severity in {case['expected_severity']}")
    return problems


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    cases = json.loads(INCIDENTS_FILE.read_text(encoding="utf-8"))
    failed = 0

    with httpx.Client(timeout=REQUEST_TIMEOUT, headers={"Content-Type": "text/plain; charset=utf-8"}) as client:
        for case in cases:
            started = time.monotonic()
            try:
                response = client.post(url, content=case["text"].encode())
            except httpx.TransportError as exc:
                response, problems = None, [f"request failed: {exc!r}"]
            else:
                problems = check(case, response)
            failed += bool(problems)

            verdict = "FAIL" if problems else "ok"
            print(f"{case['id']} {verdict:4} {time.monotonic() - started:5.1f}s  {case['purpose']}")
            if response is not None and response.status_code == httpx.codes.OK:
                body = response.json()
                print(f"     {body['severity']:6}  {body['category']}")
            for problem in problems:
                print(f"     ! {problem}")

    print(f"\n{len(cases) - failed}/{len(cases)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
