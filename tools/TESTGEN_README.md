# Shared test generation for TranTu OJ

## Design

The shared runner is problem-independent. Each problem has its own generator module because only that problem's statement and constraints define valid inputs and correct answers.

- `tools/testgen.py`: imports a generator, validates its output, computes missing expected outputs through the generator's reference `solve(input_text)`, and appends test groups to a problem JSON.
- `tools/test_generators/<problem_id>.py`: problem-specific random, boundary, adversarial and stress test logic.
- Generators use a seeded `random.Random` instance so test generation is reproducible.

## Run the XAU_KY_TU generator

From the repository root:

```bash
python tools/testgen.py XAU_KY_TU.json tools.test_generators.xau_ky_tu --seed 20261113 --output XAU_KY_TU.generated.json
```

The JSON must be a top-level array containing exactly one problem, and its subtask IDs must match those emitted by the generator (SUB1 and SUB3).

## Add another problem

1. Create `tools/test_generators/<module_name>.py`.
2. Implement `generate(rng)`, yielding dictionaries with `subtask_id` and `input`.
3. Implement `solve(input_text)` as an independent reference solution, unless every yielded case supplies its own `output`.
4. Use only inputs that satisfy the selected subtask's constraints.
5. Run the shared runner with that module's import path.

The framework deliberately does not guess a problem's input format or answer. A dedicated generator and trusted reference solution are required per problem; this prevents invalid random tests from being added to unrelated problems.

## Safety

Generated output is written to a separate file when `--output` is supplied. Review the generated JSON and run it through a local validator before importing it into a live contest.


## Test Generator Pro (differential + mutation testing)

Use the enhanced runner when you want to test candidate solutions against generated cases:

```bash
python tools/testgen_pro.py XAU_KY_TU.json tools.test_generators.xau_ky_tu \
  --seed 20261113 --output XAU_KY_TU.generated.json
```

To test one or more intentionally wrong/student implementations, pass their commands.
Each program receives one test input on stdin; stdout is compared with the generator's
trusted expected output (whitespace-insensitive):

```bash
python tools/testgen_pro.py XAU_KY_TU.json tools.test_generators.xau_ky_tu \
  --seed 20261113 --output XAU_KY_TU.generated.json \
  --candidate correct="python solution.py" \
  --candidate mutant="python wrong_solution.py" \
  --timeout 2 --dedupe
```

The runner:
- validates problem/subtask structure and verifies that subtask scores sum to total_score;
- checks generated case formats and subtask IDs;
- computes expected outputs with the generator's `solve(input_text)` when output is omitted;
- reproducibly regenerates and checks reference outputs when `solve` is available;
- optionally skips duplicate inputs, executes candidate programs, detects WA/RE/TLE,
  and reports a mutation kill rate;
- writes a separate JSON report beside the generated JSON by default.

Important: a candidate kill rate is meaningful only when candidate programs are
deliberately selected mutants or known incorrect solutions. It is not a formal
proof of test completeness. The generator and its reference solution must still
be reviewed against the statement and constraints before importing tests into a contest.
