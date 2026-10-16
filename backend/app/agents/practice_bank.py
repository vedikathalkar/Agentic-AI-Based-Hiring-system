"""Skill-tagged multiple-choice questions.

Used by the demo seed and as the offline fallback for practice (mock)
assessments when the Groq LLM is not configured. Each question carries the
skill it tests, so a practice test can be assembled for any role."""

from __future__ import annotations

import random
import re


def _mcq(skill, question, options, correct, difficulty="medium"):
    return {"type": "mcq", "skill": skill, "difficulty": difficulty, "question": question,
            "options": [{"label": l, "text": t} for l, t in zip("ABCD", options)],
            "correct_option_label": correct, "reference_answer": None, "problem_id": None}


ML_MCQ = [
    _mcq("Machine Learning", "Which technique most directly reduces overfitting in a high-variance model?",
         ["Adding more features", "L2 regularisation", "Training for more epochs", "Removing the validation set"], "B"),
    _mcq("scikit-learn", "In scikit-learn, which method fits a transformer and returns the transformed data in one call?",
         ["fit()", "predict()", "fit_transform()", "score()"], "C", "easy"),
    _mcq("PyTorch", "What does optimizer.zero_grad() do in a PyTorch training loop?",
         ["Resets model weights", "Clears accumulated gradients", "Sets the learning rate to zero", "Freezes the model"], "B"),
    _mcq("Deep Learning", "Which activation is most commonly used in hidden layers of deep CNNs?",
         ["Sigmoid", "ReLU", "Softmax", "Linear"], "B", "easy"),
    _mcq("NLP", "What is the main purpose of tokenisation in an NLP pipeline?",
         ["Encrypt the text", "Split text into units a model can process", "Translate text", "Remove all stop words"], "B", "easy"),
    _mcq("SQL", "Which SQL clause filters rows AFTER aggregation?", ["WHERE", "GROUP BY", "HAVING", "ORDER BY"], "C"),
]
FS_MCQ = [
    _mcq("React", "Which hook runs a side effect after render in React?", ["useMemo", "useEffect", "useRef", "useId"], "B", "easy"),
    _mcq("JavaScript", "What does `===` check in JavaScript?", ["Value only", "Type only", "Value and type", "Reference only"], "C", "easy"),
    _mcq("Node.js", "Which Node.js mechanism lets a single thread handle many concurrent I/O operations?",
         ["Worker pools only", "The event loop", "Multiple processes per request", "Blocking sockets"], "B"),
    _mcq("REST APIs", "Which HTTP status code should a successful POST that creates a resource return?", ["200", "201", "204", "302"], "B"),
    _mcq("PostgreSQL", "Which index type does PostgreSQL use by default?", ["Hash", "GIN", "B-tree", "BRIN"], "C"),
    _mcq("TypeScript", "What does `unknown` require before you can use a value's properties?",
         ["Nothing", "A type check or assertion", "A class declaration", "A runtime import"], "B"),
    _mcq("Git", "Which command creates a new branch and switches to it?", ["git branch -d x", "git switch -c x", "git merge x", "git fetch x"], "B", "easy"),
]
DA_MCQ = [
    _mcq("SQL", "Which join returns all rows from the left table and matching rows from the right?",
         ["INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "CROSS JOIN"], "B", "easy"),
    _mcq("Statistics", "The median is preferred over the mean when the data…",
         ["is normally distributed", "has strong outliers", "is categorical", "has no missing values"], "B"),
    _mcq("Excel", "Which Excel function looks up a value in the first column of a range and returns a value in the same row?",
         ["HLOOKUP", "VLOOKUP", "INDEX", "COUNTIF"], "B", "easy"),
    _mcq("Tableau", "In Tableau, a measure placed on Rows by default is…", ["Counted", "Aggregated (SUM)", "Filtered", "Hidden"], "B"),
    _mcq("Python", "In pandas, which method returns summary statistics for numeric columns?",
         ["df.info()", "df.describe()", "df.head()", "df.shape"], "B", "easy"),
]

EXTRA_MCQ = {
    "android": [
        _mcq("Kotlin", "Which keyword declares a read-only variable in Kotlin?", ["var", "val", "let", "const var"], "B", "easy"),
        _mcq("Android", "Which component should run a long download that must survive the app going to the background?",
             ["Activity", "Fragment", "WorkManager job", "BroadcastReceiver"], "C"),
        _mcq("REST APIs", "Which HTTP method is idempotent and used to replace a resource?", ["POST", "PUT", "PATCH", "CONNECT"], "B"),
        _mcq("Git", "What does `git rebase` do?", ["Deletes a branch", "Replays commits onto another base",
                                                   "Creates a tag", "Reverts the last commit"], "B")],
    "backend": [
        _mcq("Python", "What does a Python generator return when called?", ["A list", "A generator object", "None", "A tuple"], "B", "easy"),
        _mcq("FastAPI", "How does FastAPI validate a JSON request body?", ["With Pydantic models", "With regex", "It doesn't", "With XML schemas"], "A", "easy"),
        _mcq("PostgreSQL", "Which isolation level prevents non-repeatable reads in PostgreSQL?",
             ["Read uncommitted", "Read committed", "Repeatable read", "None"], "C"),
        _mcq("Docker", "What is the main purpose of a multi-stage Docker build?", ["Run several containers", "Produce smaller final images",
                                                                                  "Enable GPU access", "Mount volumes"], "B"),
        _mcq("SQL", "Which index type best supports equality and range queries on a column?", ["Hash", "B-tree", "Bitmap", "Full-text"], "B")],
    "devops": [
        _mcq("Kubernetes", "Which object keeps a set number of identical pods running?", ["Service", "ConfigMap", "Deployment", "Ingress"], "C", "easy"),
        _mcq("Terraform", "What does `terraform plan` do?", ["Applies changes", "Shows the changes it would make", "Deletes state", "Formats code"], "B", "easy"),
        _mcq("AWS", "Which AWS service is object storage?", ["EC2", "S3", "RDS", "Lambda"], "B", "easy"),
        _mcq("CI/CD", "What is a blue-green deployment?", ["Two identical environments; traffic switches between them",
                                                           "A deployment on Fridays", "Deploying only CSS", "A Git branching model"], "A")],
    "ds": [
        _mcq("Statistics", "A p-value of 0.03 at α = 0.05 means…", ["Accept the null hypothesis", "Reject the null hypothesis",
                                                                    "The effect is large", "The test is invalid"], "B"),
        _mcq("Machine Learning", "Which metric is most useful for a heavily imbalanced classification problem?",
             ["Accuracy", "Precision-recall AUC", "Mean squared error", "R²"], "B"),
        _mcq("pandas", "Which pandas method combines two DataFrames on a key column?", ["concat", "merge", "append", "stack"], "B", "easy"),
        _mcq("scikit-learn", "Why use cross-validation?", ["To speed up training", "To estimate performance on unseen data",
                                                            "To remove outliers", "To scale features"], "B", "easy")],
    "qa": [
        _mcq("Selenium", "Which locator is usually the most stable in Selenium?", ["Absolute XPath", "Unique id", "CSS nth-child", "Link text"], "B", "easy"),
        _mcq("Test Automation", "What is a flaky test?", ["A slow test", "A test that passes and fails without code changes",
                                                          "A skipped test", "A unit test"], "B", "easy"),
        _mcq("Java", "Which JUnit annotation runs before each test method?", ["@BeforeAll", "@BeforeEach", "@Test", "@AfterEach"], "B"),
        _mcq("SQL", "Which query returns the number of rows in a table named orders?",
             ["SELECT SUM(*) FROM orders", "SELECT COUNT(*) FROM orders", "SELECT ROWS FROM orders", "COUNT orders"], "B", "easy")],
    "frontend": [
        _mcq("React", "Why do list items in React need a `key`?", ["For CSS", "So React can track items between renders",
                                                                    "For accessibility", "To sort them"], "B", "easy"),
        _mcq("CSS", "Which CSS layout is best for a two-dimensional grid?", ["Flexbox", "Grid", "Float", "Table"], "B", "easy"),
        _mcq("TypeScript", "What does the `?` in `name?: string` mean?", ["Nullable type", "Optional property", "Private property", "Any type"], "B", "easy"),
        _mcq("JavaScript", "What does `Promise.all` do if one promise rejects?", ["Ignores it", "Rejects immediately",
                                                                                 "Retries it", "Resolves with undefined"], "B")],
    "pa": [
        _mcq("Statistics", "What does a conversion rate measure?", ["Visitors per day", "Share of users who complete a goal",
                                                                    "Revenue per user", "Page load time"], "B", "easy"),
        _mcq("SQL", "Which clause keeps only groups with more than 10 orders?", ["WHERE", "HAVING", "LIMIT", "ORDER BY"], "B", "easy"),
        _mcq("Data Analysis", "In an A/B test, what is the control group?", ["Users who see the new version",
                                                                             "Users who see the current version", "All users", "Bots"], "B", "easy"),
        _mcq("Excel", "Which Excel feature summarises data by categories interactively?", ["VLOOKUP", "PivotTable", "Conditional formatting", "Freeze panes"], "B", "easy")],
}



# Extra general questions so common skills always have enough material.
MORE_MCQ = [
    _mcq("Python", "What does `if __name__ == \"__main__\":` do?", ["Imports a module", "Runs code only when the file is executed directly",
                                                                   "Declares the main class", "Starts a thread"], "B", "easy"),
    _mcq("Python", "Which data structure gives average O(1) membership checks?", ["list", "tuple", "set", "string"], "C", "easy"),
    _mcq("Python", "What is a decorator in Python?", ["A comment style", "A function that wraps another function to extend it",
                                                      "A class attribute", "A type hint"], "B"),
    _mcq("SQL", "Which statement removes all rows but keeps the table structure fastest?", ["DROP TABLE", "DELETE without WHERE", "TRUNCATE", "ALTER"], "C"),
    _mcq("SQL", "What does a LEFT JOIN return for rows with no match on the right?", ["They are dropped", "NULLs for right-side columns",
                                                                                  "Zeros", "An error"], "B", "easy"),
    _mcq("JavaScript", "What is a closure?", ["A finished promise", "A function that remembers variables from its outer scope",
                                              "A closed browser tab", "A private class"], "B"),
    _mcq("Git", "How do you undo the last commit but keep its changes in your working tree?", ["git reset --soft HEAD~1", "git revert --all",
                                                                                             "git clean -fd", "git stash drop"], "A"),
    _mcq("Data Structures", "What is the time complexity of binary search on a sorted array?", ["O(n)", "O(log n)", "O(n log n)", "O(1)"], "B", "easy"),
    _mcq("Data Structures", "Which structure is best for a first-in-first-out queue?", ["Stack", "Queue / deque", "Heap", "Tree"], "B", "easy"),
    _mcq("Machine Learning", "What is the purpose of a validation set?", ["Train the model", "Tune hyperparameters and check generalisation",
                                                                          "Store raw data", "Replace the test set"], "B", "easy"),
    _mcq("REST APIs", "Which status code means the client is not authenticated?", ["200", "401", "404", "500"], "B", "easy"),
    _mcq("Docker", "What does `docker compose up` do?", ["Builds a single image only", "Starts the services defined in the compose file",
                                                         "Deletes containers", "Pushes to a registry"], "B", "easy"),
]

ALL_MCQ = [q for group in (ML_MCQ, FS_MCQ, DA_MCQ, MORE_MCQ, *EXTRA_MCQ.values()) for q in group]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+#]", "", (s or "").lower())


def pick_mcqs(skills: list[str], count: int, difficulty: str = "medium", seed: int | None = None) -> list[dict]:
    """Questions whose skill matches one of `skills`, spread across skills; tops up with
    general fundamentals so a practice test is never empty."""
    rng = random.Random(seed)
    wanted = [_norm(s) for s in skills if s]
    matches = [q for q in ALL_MCQ if any(w and (w in _norm(q["skill"]) or _norm(q["skill"]) in w) for w in wanted)]
    rng.shuffle(matches)
    order = {"easy": 0, "medium": 1, "hard": 2}
    target = order.get(difficulty, 1)
    matches.sort(key=lambda q: abs(order.get(q["difficulty"], 1) - target))
    by_skill: dict[str, list[dict]] = {}
    for q in matches:
        by_skill.setdefault(q["skill"], []).append(q)
    picked: list[dict] = []
    while len(picked) < count and any(by_skill.values()):          # round-robin across skills
        for k in list(by_skill):
            if by_skill[k] and len(picked) < count:
                picked.append(by_skill[k].pop(0))
    if len(picked) < count:
        rest = [q for q in ALL_MCQ if q not in picked and q["skill"] in ("Data Structures", "Git", "REST APIs", "SQL", "Python")]
        rng.shuffle(rest)
        picked += rest[: count - len(picked)]
    return [dict(q) for q in picked[:count]]
