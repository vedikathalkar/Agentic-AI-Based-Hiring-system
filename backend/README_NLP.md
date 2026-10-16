# Resume Parsing Agent — NLP notes

## What it is

`app/agents/resume_parser.py` uses a **custom-trained spaCy NER model**
(`app/agents/ner_model/`, already trained and included in this zip) to pull
`SKILL` and `DEGREE` entities out of resume text, instead of pure keyword
matching. It's built by extending spaCy's pretrained English pipeline
(`en_core_web_sm`) with two new entity labels and training just the NER
component on ~500 auto-generated labeled examples (see `training_data.py`).

The base pipeline's own pretrained entities (`ORG`, `GPE`, `PERSON`) are
reused — for free, no training needed — to pull company names out of the
experience section, and to suppress skill false positives (see below).

## Setup

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm   # base model, ~13MB
```

The trained model is already in `app/agents/ner_model/` — you don't need to
retrain to use it. If you want to retrain (e.g. after editing
`training_data.py` to improve it):

```
python -m app.agents.train_ner
```

This regenerates training data, trains for 25 iterations, and overwrites
`app/agents/ner_model/`.

## Known limitations (worth putting in your report)

The training data is **synthetically generated** — skills and degrees
dropped into template sentences ("Proficient in X and Y.") — not
hand-annotated real resumes. This means:

- **Strength:** the model generalizes to skill terms it never saw during
  training (tested: correctly tagged "Rust", "Ansible", "Terraform",
  "Jenkins" as SKILL despite none of those appearing in the training
  vocabulary). That's the actual point of using a trained model instead of
  a keyword list — it's learned the *shape* of how skills appear in text,
  not just memorized a list.
- **Weakness:** on real resumes with unusual formatting (headings, bullet
  points, project names), it sometimes mislabels proper nouns as SKILL —
  e.g. a project name like "PR Janitor" got tagged as a skill in testing.
  Two mitigations are already in place:
  1. Model predictions are cross-checked against a curated keyword list
     and length/format heuristics (`_is_plausible_skill`).
  2. A second, untouched copy of the base model is run purely to detect
     organization/place names, and any SKILL prediction overlapping a
     known ORG/GPE span is suppressed (`_org_gpe_spans`, `_overlaps`).
  Neither mitigation is perfect — genuinely novel project names can still
  slip through, since nothing distinguishes "a project name I've never
  seen" from "a skill I've never seen" without more training data.

**Natural next step** if you want to strengthen this further: hand-correct
50-100 real resumes' worth of predictions and add them to the training set
alongside the synthetic examples — real annotated examples fix this kind
of error far more efficiently than more synthetic data would.
