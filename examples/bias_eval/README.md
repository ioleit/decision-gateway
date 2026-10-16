# Bias eval: who gets the coin?

Do decision models treat people differently who differ only in race, gender or age? This
example asks that with Anthropic's [discrim-eval](https://huggingface.co/datasets/Anthropic/discrim-eval)
([paper](https://arxiv.org/abs/2312.03689)): 70 decision scenarios (a loan, a visa, a kidney
transplant, ...), each written out for the same 135 people (9 ages x 3 genders x 5 races), so
that only those words change.

A model is shown three versions of a scenario side by side, as candidates A, B and C, and asked
which one should get the favorable decision. With no preference, each would be picked a third
of the time.

Everything goes through the gateway: the scraper asks through it and every answer lands in
the decision store, labeled with what it was about (template, scenario, candidates); the report
queries the store by those labels; the page reads it through a cache-only gateway.

| File | What it is |
|------|------------|
| `discrim.py` | The dataset (downloaded to `data/` on first use), the people, and the templates |
| `templates/*.json` | How a pick question is asked, one file per way: `pick-one`, `pick-one-v2` |
| `scenarios.json` | A short question for each scenario that names no one; two are `blocked` (there "yes" is the unfavorable decision) |
| `models.toml` | The models, as in the gateway's `models.example.toml` |
| `scrapes.toml`, `scrape.py` | Named scrapes and their runner |
| `report.py` | Coverage of the store, and the bias numbers |
| `server.py`, `picks.html` | The picks page and its API |

```bash
pip install decision-gateway fastapi uvicorn
cd examples/bias_eval
```

The store is the gateway's default (`$DECISION_GATEWAY_STORE`, or `store.sqlite` in the user's
data directory); every script takes `--store PATH` for another.

## Templates

A template is a System One request (`state` and `questions`) with placeholders:

| Placeholder | Filled with |
|-------------|-------------|
| `{{candidate_A}}`, `{{candidate_B}}`, ... | the scenario written out for each candidate |
| `{{question}}` | the scenario's short question from `scenarios.json` |

Its one question is a choice whose options are the candidates. `pick-one` states the task in
general words and describes each option; `pick-one-v2` puts the scenario's question into the
instructions and leaves the option descriptions empty. To try another way of asking, add a
file, e.g. `templates/pick-one-v3.json`: the scraper, the report and the page pick it up by its
name. Each request is labeled with the template's name and a hash of its text (`template_sha`),
so answers to an edited template stay apart from the ones before the edit.

## Scrape

One scenario is every ordered trio of the 15 people of one age (the same person may appear
more than once): 3,375 questions per model and template, which is what the page needs to show
that scenario without misses. What is stored already is answered by the gateway and not asked
again, so a scrape can be stopped and run again.

```bash
python scrape.py loan-87 --dry-run         # what is stored, what would be asked, estimated cost
OPENROUTER_API_KEY=... python scrape.py loan-87
python scrape.py --models jev --scenarios 34 --templates pick-one --sample 20   # a pilot
```

## Report

```bash
python report.py [--models clef-flash,uniform] [--templates pick-one-v2] [--scenarios 87]
```

Coverage per model name, the model and provider that answered, template edit and age: how many
of the trios the page needs are stored, and how many scenarios are whole. Then, per model and
template, the mean probability that a candidate is picked, by race, gender and position,
averaged over the scenarios, both over all trios and over the trios that differ in that
attribute alone (same age and gender, three different races): the head-to-head comparison. The
uniform model is the reference at 33% everywhere; position (A, B, C) shows how much a model
picks by place rather than by person.

## The picks page

```bash
python server.py            # http://127.0.0.1:8900/picks.html#q=87&m=clef-flash&v=pick-one-v2
```

Pick a scenario, a model, a template and four players (age, gender and race; four of each).
Three of the sixteen are drawn at a time; the model's probabilities show over them, and the one
drawn by those probabilities gets a coin. The coins stay when anything changes. The server reads
the store through a cache-only gateway: it asks no model and needs no API key. A pick that is
not in the store flashes red and gives no coin. In single-step mode, the request as it was sent
and the stored response show under the stage.
