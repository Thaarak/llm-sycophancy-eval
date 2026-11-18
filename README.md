# Local answer-sycophancy study

I built this project to learn how to design and evaluate an AI safety experiment. I investigated how weak user hints affect Qwen3 4B’s factual answers using 30 selected TruthfulQA questions, four prompt conditions, and 120 final replies that I manually graded.

I adapted the answer-sycophancy experiment from Sharma et al. for a local model and manual grading. My [report](REPORT.md) explains the methods, results, and limitations. My [analysis summary](results/truthfulqa/summary.json) records the results and grading-file checksum.

| Condition | Correct | Accuracy |
|---|---:|---:|
| No hint | 20/30 | 66.7% |
| Correct suggestion | 28/30 | 93.3% |
| Incorrect suggestion | 21/30 | 70.0% |
| Doubt the correct answer | 25/30 | 83.3% |

I graded 94/120 replies as correct overall (78.3%). Among the 20 questions Qwen3 answered correctly without a hint, I found one where an incorrect suggestion led it to give the planned misconception. Accuracy under incorrect suggestions increased slightly overall, from 66.7% to 70.0%. I treat these as exploratory findings for one model and a selected question set.

![Accuracy by condition, with the correct count out of 30 shown on each bar.](results/truthfulqa/accuracy_by_condition.png)

## Reproduce the saved results

I included an offline analysis script that uses the Python standard library. You can reproduce my numeric results without Ollama or network access.

```sh
python3 analyze_study.py --no-plot
python3 -m unittest -v
```

I used the following Python 3.12 workflow to regenerate the figure in an isolated environment.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python analyze_study.py
```

My project was checked with Python 3.12.14 and Matplotlib 3.11.2. I saved the numeric results in [accuracy_by_condition.csv](results/truthfulqa/accuracy_by_condition.csv), [paired_results.csv](results/truthfulqa/paired_results.csv), and [summary.json](results/truthfulqa/summary.json).

## Inspect or resume local collection

I saved the exact prompts used for collection. You can preview the first batch offline with this command.

```sh
python3 run_open_ended.py truthfulqa-batch1 --preview
```

I collected the main study in batches `truthfulqa-batch1`, `truthfulqa-batch2`, `truthfulqa-batch3`, `truthfulqa-batch4`, and `truthfulqa-batch6`. These cover question numbers 1–24 and 31–36. I did not run candidates 25–30, so there is no batch 5 in the collected data.

To resume a batch, start Ollama with the reviewed `qwen3:4b` build installed, then run the same command without `--preview`.

```sh
python3 run_open_ended.py truthfulqa-batch1
```

I used a collector that checks the recorded model digest and Ollama version, preserves completed receipts, and resumes missing calls. I sent each request as a single fresh user message, with temperature 0, thinking enabled, and unconstrained output. The collector keeps transport failures in an append-only log and retains incomplete replies as terminal records. My analysis excludes incomplete replies from accuracy calculations and matched comparisons, and rejects duplicate IDs, missing grades, and grading text that differs from its source receipt.

In my analysis, a normally finished empty answer is retained as a noncorrect reply when graded `ambiguous or no answer`.

I included the complete main-study receipts so others can inspect the original evidence. A fresh collection would need its own output files.

## Data and provenance

- My [question manifests and prompt rosters](data/truthfulqa/) pin the dataset revision, source rows, accepted references, misconceptions, and reviewed prompts.
- My revised manual grades and original spreadsheet row numbers are in [grades.csv](data/truthfulqa/grades.csv).
- I recorded the export date, checksum, grading visibility, and correction history in [grading_snapshot.json](data/truthfulqa/grading_snapshot.json).
- I retained final-answer text, completion status, elapsed time, model digest, and Ollama version in the [run receipts](runs/).
- I included an [evidence manifest](data/truthfulqa/evidence_manifest.json) linking the report’s methods and results to the saved sources.

I included TruthfulQA’s upstream Apache License 2.0 and the subset’s adaptation details in [the data attribution](data/truthfulqa/ATTRIBUTION.md).

I excluded the six-question multiple-choice pilot and the later 30-question open-ended practice collection from my main results. I kept the historical pilot commands in [protocol.md](protocol.md) and archived the practice prompts in [practice-roster.json](data/practice-roster.json). You can preview those prompts with the `first`, `remaining`, `harder`, `third`, `fourth`, and `fifth` phases of `run_open_ended.py`.

## My role and assistance

I reviewed and approved the question batches and manually graded the replies. I used Codex to help draft questions, implement and execute the collection, analyze the results, discuss selected grades, and draft the write-up. I have reviewed the report.

For the reporting workflow, Codex used the scientific-writing skill documented in Kassis et al. (2026), [Scientific Agent Skills](https://arxiv.org/abs/2609.00065). I cite the original sycophancy and TruthfulQA papers in my report.
