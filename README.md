# Local answer-sycophancy experiment

Does Qwen3 4B choose an incorrect answer more often when the user suggests it? This project will test the question on a laptop using Ollama and Python.

The pilot covers six questions. Each question is tested with three user hints (none, correct, or incorrect) and both answer orders, for 36 independent requests.

[Experiment plan](PLAN.md) has the review checkpoints, prompt design, scoring rules, and planned outputs.

[Pilot protocol](protocol.md) describes the verified question bank, pinned model, scoring rules, and commands. To see the exact prompts without running the model:

```sh
python3 run_pilot.py preview
```
