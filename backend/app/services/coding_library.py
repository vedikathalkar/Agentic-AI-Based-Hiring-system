"""Built-in coding problem library (stdin/stdout problems with real test cases).

Seeded once into ``coding_problems`` (idempotent by slug). HR can add their own
problems through the API; hidden tests are never sent to candidates.
Reference solutions live in tests/test_coding_library.py, which verifies every
test case below.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .. import models

LIBRARY = [
    {
        "slug": "array-sum", "title": "Sum of Numbers", "difficulty": "easy",
        "tags": "python,java,c++,programming,algorithms,data structures",
        "statement": "Given N integers, print their sum.",
        "input_format": "The first line contains N. The second line contains N space-separated integers.",
        "output_format": "Print a single integer: the sum.",
        "constraints": "1 <= N <= 10^5\n-10^9 <= each integer <= 10^9",
        "examples": [{"input": "3\n1 2 3", "output": "6", "explanation": "1 + 2 + 3 = 6"}],
        "visible": [{"input": "3\n1 2 3\n", "output": "6"}, {"input": "1\n-5\n", "output": "-5"}],
        "hidden": [{"input": "5\n1000000000 1000000000 1000000000 1000000000 1000000000\n", "output": "5000000000"},
                   {"input": "4\n-1 1 -1 1\n", "output": "0"},
                   {"input": "6\n7 0 0 0 0 3\n", "output": "10"}],
    },
    {
        "slug": "palindrome-check", "title": "Palindrome Check", "difficulty": "easy",
        "tags": "python,java,c++,strings,programming",
        "statement": "A string is a palindrome if it reads the same forwards and backwards after removing every "
                     "character that is not a letter or digit and ignoring case. Print YES if the given line is a "
                     "palindrome, otherwise NO.",
        "input_format": "A single line of text (may contain spaces and punctuation).",
        "output_format": "YES or NO.",
        "constraints": "1 <= length <= 10^5",
        "examples": [{"input": "A man, a plan, a canal: Panama", "output": "YES", "explanation": "amanaplanacanalpanama"}],
        "visible": [{"input": "A man, a plan, a canal: Panama\n", "output": "YES"}, {"input": "hello\n", "output": "NO"}],
        "hidden": [{"input": "No 'x' in Nixon\n", "output": "YES"}, {"input": "ab\n", "output": "NO"},
                   {"input": "Was it a car or a cat I saw?\n", "output": "YES"}, {"input": "0P\n", "output": "NO"}],
    },
    {
        "slug": "max-subarray", "title": "Maximum Subarray Sum", "difficulty": "medium",
        "tags": "python,java,c++,algorithms,dynamic programming,machine learning,data structures",
        "statement": "Given an array of N integers, find the largest possible sum of a non-empty contiguous subarray.",
        "input_format": "The first line contains N. The second line contains N space-separated integers.",
        "output_format": "Print the maximum subarray sum.",
        "constraints": "1 <= N <= 2*10^5\n-10^9 <= a[i] <= 10^9",
        "examples": [{"input": "9\n-2 1 -3 4 -1 2 1 -5 4", "output": "6", "explanation": "[4, -1, 2, 1] has sum 6"}],
        "visible": [{"input": "9\n-2 1 -3 4 -1 2 1 -5 4\n", "output": "6"}, {"input": "1\n5\n", "output": "5"}],
        "hidden": [{"input": "3\n-3 -1 -2\n", "output": "-1"}, {"input": "5\n5 4 -1 7 8\n", "output": "23"},
                   {"input": "4\n1000000000 1000000000 -1 1000000000\n", "output": "2999999999"}],
    },
    {
        "slug": "balanced-brackets", "title": "Balanced Brackets", "difficulty": "medium",
        "tags": "python,java,c++,javascript,stacks,data structures,programming",
        "statement": "Given a string made of the characters ()[]{}, print YES if every bracket is closed by the same "
                     "type of bracket in the correct order, otherwise NO.",
        "input_format": "A single line containing the bracket string.",
        "output_format": "YES or NO.",
        "constraints": "1 <= length <= 10^5",
        "examples": [{"input": "{[()]}", "output": "YES", "explanation": "Every bracket closes in order"}],
        "visible": [{"input": "{[()]}\n", "output": "YES"}, {"input": "([)]\n", "output": "NO"}],
        "hidden": [{"input": "((((\n", "output": "NO"}, {"input": "()[]{}\n", "output": "YES"},
                   {"input": "]\n", "output": "NO"}, {"input": "{{[[(())]]}}\n", "output": "YES"}],
    },
    {
        "slug": "category-totals", "title": "Category Totals", "difficulty": "medium",
        "tags": "sql,python,data analysis,pandas,tableau,excel,analytics",
        "statement": "You are given sales rows of the form `category amount`. Print the total amount per category, "
                     "one per line as `category total`, sorted by total descending and then by category name "
                     "ascending (like SELECT category, SUM(amount) ... GROUP BY category ORDER BY 2 DESC, 1).",
        "input_format": "The first line contains N. Each of the next N lines contains a category (no spaces) and an integer amount.",
        "output_format": "One line per category: `category total`.",
        "constraints": "1 <= N <= 10^5\n0 <= amount <= 10^6",
        "examples": [{"input": "4\nbooks 10\ntoys 5\nbooks 7\ngames 17", "output": "books 17\ngames 17\ntoys 5",
                      "explanation": "books and games tie at 17, so they are ordered by name"}],
        "visible": [{"input": "4\nbooks 10\ntoys 5\nbooks 7\ngames 17\n", "output": "books 17\ngames 17\ntoys 5"},
                    {"input": "1\na 0\n", "output": "a 0"}],
        "hidden": [{"input": "5\nx 1\ny 2\nz 3\nx 4\ny 1\n", "output": "x 5\ny 3\nz 3"},
                   {"input": "3\nb 100\na 100\nc 100\n", "output": "a 100\nb 100\nc 100"},
                   {"input": "2\nsolo 1000000\nsolo 1000000\n", "output": "solo 2000000"}],
    },
    {
        "slug": "word-frequency", "title": "Top Word Frequencies", "difficulty": "medium",
        "tags": "python,nlp,natural language processing,strings,data analysis,machine learning",
        "statement": "Given a line of text and an integer K, print the K most frequent words (lowercased, words are "
                     "maximal runs of letters a-z). Break ties alphabetically. Print `word count` per line. "
                     "If there are fewer than K distinct words, print all of them.",
        "input_format": "The first line contains K. The second line contains the text.",
        "output_format": "Up to K lines of `word count`.",
        "constraints": "1 <= K <= 100\n1 <= text length <= 10^5",
        "examples": [{"input": "2\nThe cat and the hat and the bat", "output": "the 3\nand 2",
                      "explanation": "'the' appears 3 times, 'and' twice"}],
        "visible": [{"input": "2\nThe cat and the hat and the bat\n", "output": "the 3\nand 2"},
                    {"input": "3\nhello\n", "output": "hello 1"}],
        "hidden": [{"input": "2\nb a b a c\n", "output": "a 2\nb 2"},
                   {"input": "1\nIt's it, IT! it?\n", "output": "it 4"},
                   {"input": "3\nzeta alpha zeta beta alpha zeta\n", "output": "zeta 3\nalpha 2\nbeta 1"}],
    },
]


def seed_library(db: Session) -> int:
    added = 0
    for p in LIBRARY:
        if db.query(models.CodingProblem).filter(models.CodingProblem.slug == p["slug"]).first():
            continue
        db.add(models.CodingProblem(
            slug=p["slug"], title=p["title"], difficulty=p["difficulty"], tags=p["tags"],
            statement=p["statement"], input_format=p["input_format"], output_format=p["output_format"],
            constraints=p["constraints"], examples=json.dumps(p["examples"]),
            visible_tests=json.dumps(p["visible"]), hidden_tests=json.dumps(p["hidden"]),
            time_limit_ms=2000, memory_limit_mb=256, active=True,
        ))
        added += 1
    if added:
        db.commit()
    return added
