"""
Trains a custom Named Entity Recognition model on top of spaCy's
pretrained English pipeline (en_core_web_sm), teaching it two new
entity types the base model doesn't know about:

  SKILL   -> technical skills (Python, React, Docker, ...)
  DEGREE  -> academic qualifications (B.Tech, MBA, Ph.D., ...)

The base model already recognizes ORG, DATE, GPE, PERSON out of the box
(useful for pulling company names and durations out of the experience
section) — we're only adding the two labels resumes actually need that
general-purpose English NLP models aren't trained for.

Usage: python -m app.agents.train_ner
Output: trained pipeline saved to app/agents/ner_model/
"""
import random
from pathlib import Path

import spacy
from spacy.training import Example
from spacy.util import minibatch, compounding

from .training_data import generate_examples

MODEL_OUT = Path(__file__).parent / "ner_model"
N_EXAMPLES = 500
N_ITERATIONS = 25


def train():
    print("Loading base pipeline (en_core_web_sm)...")
    nlp = spacy.load("en_core_web_sm")

    ner = nlp.get_pipe("ner")
    ner.add_label("SKILL")
    ner.add_label("DEGREE")

    print(f"Generating {N_EXAMPLES} labeled training examples...")
    raw_examples = generate_examples(n=N_EXAMPLES)
    examples = []
    for text, annotations in raw_examples:
        doc = nlp.make_doc(text)
        examples.append(Example.from_dict(doc, annotations))

    # only train the NER component — leave tagger/parser/tok2vec as-is
    pipe_exceptions = ["ner"]
    other_pipes = [p for p in nlp.pipe_names if p not in pipe_exceptions]

    print(f"Training for {N_ITERATIONS} iterations...")
    with nlp.disable_pipes(*other_pipes):
        optimizer = nlp.resume_training()
        for i in range(N_ITERATIONS):
            random.shuffle(examples)
            losses = {}
            batches = minibatch(examples, size=compounding(4.0, 32.0, 1.001))
            for batch in batches:
                nlp.update(batch, drop=0.2, losses=losses, sgd=optimizer)
            if (i + 1) % 5 == 0 or i == 0:
                print(f"  iteration {i + 1}/{N_ITERATIONS} — loss: {losses.get('ner', 0):.2f}")

    MODEL_OUT.mkdir(exist_ok=True)
    nlp.to_disk(MODEL_OUT)
    print(f"Model saved to {MODEL_OUT}")

    # quick sanity check
    test_text = (
        "Proficient in Python, FastAPI, and PostgreSQL. "
        "Holds a B.E. Information Technology degree and has worked with Docker and React."
    )
    doc = nlp(test_text)
    print("\nSanity check on a test sentence:")
    print(f"  Text: {test_text}")
    print(f"  Entities: {[(ent.text, ent.label_) for ent in doc.ents]}")


if __name__ == "__main__":
    train()
