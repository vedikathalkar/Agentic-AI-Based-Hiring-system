"""Every built-in coding problem's visible and hidden tests are checked against a
reference solution executed through the real sandbox runner."""

import pytest

from app.services import code_runner
from app.services.coding_library import LIBRARY

REFERENCE = {
    "array-sum": "n=int(input());print(sum(map(int,input().split())))",
    "palindrome-check": "s=input();t=[c.lower() for c in s if c.isalnum()];print('YES' if t==t[::-1] else 'NO')",
    "max-subarray": (
        "input();a=list(map(int,input().split()));best=cur=a[0]\n"
        "for x in a[1:]:\n    cur=max(x,cur+x);best=max(best,cur)\nprint(best)"),
    "balanced-brackets": (
        "s=input().strip();st=[];m={')':'(',']':'[','}':'{'};ok=True\n"
        "for c in s:\n    if c in '([{': st.append(c)\n    elif not st or st.pop()!=m[c]: ok=False;break\n"
        "print('YES' if ok and not st else 'NO')"),
    "category-totals": (
        "import sys\nfrom collections import defaultdict\nd=sys.stdin.read().split();n=int(d[0]);t=defaultdict(int)\n"
        "for i in range(n): t[d[1+2*i]]+=int(d[2+2*i])\n"
        "for k,v in sorted(t.items(),key=lambda x:(-x[1],x[0])): print(k,v)"),
    "word-frequency": (
        "import re,sys\nfrom collections import Counter\nk=int(input());c=Counter(re.findall('[a-z]+',sys.stdin.read().lower()))\n"
        "for w,n in sorted(c.items(),key=lambda x:(-x[1],x[0]))[:k]: print(w,n)"),
}

pytestmark = pytest.mark.skipif(not code_runner.is_available("python"), reason="python sandbox unavailable")


@pytest.mark.parametrize("problem", LIBRARY, ids=[p["slug"] for p in LIBRARY])
def test_reference_solution_passes_all_tests(problem):
    tests = problem["visible"] + problem["hidden"]
    report = code_runner.execute("python", REFERENCE[problem["slug"]], tests)
    assert report.status == "accepted", [t.__dict__ for t in report.tests if not t.passed]
    assert report.passed == report.total == len(tests)
    assert len(problem["hidden"]) >= 3


def test_wrong_solution_is_partially_scored():
    report = code_runner.execute("python", "print(6)", LIBRARY[0]["visible"] + LIBRARY[0]["hidden"])
    assert report.status == "wrong_answer"
    assert 0 < report.passed < report.total
    assert report.score == round(report.passed / report.total * 100, 1)


def test_infinite_loop_times_out():
    report = code_runner.execute("python", "while True: pass", [{"input": "", "output": ""}], time_limit_ms=500)
    assert report.status == "time_limit"


def test_compile_error_reported():
    if not code_runner.is_available("cpp"):
        pytest.skip("g++ unavailable")
    report = code_runner.execute("cpp", "int main(){ return x; }", [{"input": "", "output": ""}])
    assert report.status == "compile_error" and report.error


def test_sandbox_has_no_network():
    if not code_runner.sandbox_info()["network_isolated"]:
        pytest.skip("network namespaces unavailable here")
    src = "import socket\ntry:\n    socket.create_connection(('1.1.1.1',80),timeout=2);print('online')\nexcept OSError:\n    print('offline')"
    report = code_runner.execute("python", src, [{"input": "", "output": "offline"}])
    assert report.status == "accepted"
