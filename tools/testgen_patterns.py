"""Reusable deterministic adversarial input patterns for problem generators.

These helpers do not assume a problem's input format. A problem-specific generator
chooses how to serialize the returned values and which patterns satisfy its limits.
"""
import random


def integer_boundaries(lo, hi):
    if lo > hi:
        raise ValueError("lo must not exceed hi")
    values = [lo, hi]
    for x in (0, 1, -1, lo + 1, hi - 1, (lo + hi) // 2):
        if lo <= x <= hi:
            values.append(x)
    return list(dict.fromkeys(values))


def arrays(n, lo, hi, rng):
    """Yield common array shapes: min/max, equal, sorted, reverse, alternating, random."""
    if n < 0 or lo > hi:
        raise ValueError("invalid array constraints")
    if n == 0:
        yield []
        return
    yield [lo] * n
    yield [hi] * n
    yield [(lo + hi) // 2] * n
    yield sorted(rng.randint(lo, hi) for _ in range(n))
    yield sorted((rng.randint(lo, hi) for _ in range(n)), reverse=True)
    yield [lo if i % 2 == 0 else hi for i in range(n)]
    yield [rng.randint(lo, hi) for _ in range(n)]


def graphs(n, mode, rng):
    """Generate edge lists for path, star, cycle, complete (small n), or random graphs."""
    if n < 1:
        raise ValueError("graph must have at least one vertex")
    if mode == "path":
        return [(i, i + 1) for i in range(1, n)]
    if mode == "star":
        return [(1, i) for i in range(2, n + 1)]
    if mode == "cycle":
        return [(i, i + 1) for i in range(1, n)] + ([(n, 1)] if n > 2 else [])
    if mode == "complete":
        if n > 500:
            raise ValueError("complete graph helper is limited to n <= 500")
        return [(i, j) for i in range(1, n + 1) for j in range(i + 1, n + 1)]
    if mode == "random":
        if n == 1:
            return []
        edges = set()
        for v in range(2, n + 1):
            u = rng.randint(1, v - 1)
            edges.add((u, v))
        extra = rng.randint(0, min(n, n * (n - 1) // 2 - len(edges)))
        while extra:
            u, v = rng.sample(range(1, n + 1), 2)
            edge = (min(u, v), max(u, v))
            if edge not in edges:
                edges.add(edge)
                extra -= 1
        return sorted(edges)
    raise ValueError(f"unknown graph mode: {mode}")


def strings(n, alphabet, rng):
    if n < 0 or not alphabet:
        raise ValueError("invalid string constraints")
    return "".join(rng.choice(alphabet) for _ in range(n))


def permutations(n, rng):
    values = list(range(1, n + 1))
    rng.shuffle(values)
    return values


def operation_sequences(n, kinds, rng):
    if n < 0 or not kinds:
        raise ValueError("invalid operation sequence constraints")
    return [rng.choice(kinds) for _ in range(n)]
