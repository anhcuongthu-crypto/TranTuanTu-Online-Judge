"""Copy this file to tools/test_generators/<problem>.py and customize it."""
def solve(input_text):
    # Implement a simple, trusted reference algorithm independently
    # from the intended optimized solution.
    raise NotImplementedError


def generate(rng):
    # Yield dictionaries: {"subtask_id": "SUB1", "input": "..."}.
    # The Pro runner computes output with solve(input_text).
    # Include boundary, corner, structured, random, adversarial and stress cases.
    raise NotImplementedError
