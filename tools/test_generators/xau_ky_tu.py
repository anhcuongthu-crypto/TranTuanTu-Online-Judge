"""Strong test generator for XAU_KY_TU, plugged into the shared testgen runner."""
VALID = "BCDEFGIJKLMOPQRSTUVWXYZ"
FORBIDDEN = set("ANH")


def solve(input_text):
    lines = input_text.splitlines()
    count = int(lines[0])
    answers = []
    for s in lines[1:1 + count]:
        best = current = 0
        for ch in s.strip():
            if ch in FORBIDDEN:
                current = 0
            else:
                current += 1
                best = max(best, current)
        answers.append(str(best if best else -1))
    return "\n".join(answers)


def _case(subtask_id, strings):
    input_text = str(len(strings)) + "\n" + "\n".join(strings)
    return {"subtask_id": subtask_id, "input": input_text, "output": solve(input_text)}


def generate(rng):
    # SUB1: exactly one A; no N/H.
    for _ in range(2):
        strings = []
        for _ in range(10):
            n = 100000
            pos = rng.randrange(n)
            strings.append(
                "".join(rng.choices(VALID, k=pos))
                + "A"
                + "".join(rng.choices(VALID, k=n - pos - 1))
            )
        yield _case("SUB1", strings)

    # SUB3: long random strings, with different forbidden-character densities.
    for probability in (0.0002, 0.05):
        strings = []
        pool = list(VALID) + ["A", "N", "H"]
        weights = [1.0] * len(VALID) + [probability * len(VALID) / 3.0] * 3
        for _ in range(10):
            strings.append("".join(rng.choices(pool, weights=weights, k=100000)))
        yield _case("SUB3", strings)

    # SUB3: deterministic adversarial boundaries and patterns.
    strings = [
        "B" * 100000,
        "ANH" * 33333 + "A",
        "BA" * 50000,
        "A" + "B" * 99998 + "N",
        ("BBBBAN" * 16666) + "BB",
        "B" * 49999 + "A" + "C" * 50000,
        "N" + "Z" * 99998 + "H",
        "B" * 49998 + "ANH" + "C" * 49999,
        "A" + "B" * 99999,
        "B" * 99999 + "H",
    ]
    yield _case("SUB3", strings)
