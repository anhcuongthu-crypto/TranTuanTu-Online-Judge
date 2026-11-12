"""Batch test-suite builder for every problem in data/problems.json.

Only generators with an explicit reference implementation are enabled. This tool
writes a NEW JSON file and report; it never overwrites the source problem bank.
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def prime(n):
    if n < 2:
        return False
    d = 2
    while d * d <= n:
        if n % d == 0:
            return False
        d += 1
    return True


def divisor_prime_prefix(limit):
    tau = [0] * (limit + 1)
    for d in range(1, limit + 1):
        for x in range(d, limit + 1, d):
            tau[x] += 1
    pref = [0] * (limit + 1)
    for x in range(1, limit + 1):
        pref[x] = pref[x - 1] + int(prime(tau[x]))
    return pref


def is_special(x):
    product = 1
    for ch in str(x):
        digit = int(ch)
        if digit == 0:
            return False
        product *= digit
    return x % product == 0


def is_near_square(x):
    s = str(x)
    if len(s) < 3 or int(s[0]) not in (1, 4, 9):
        return False
    z = int(s[-1]) + int(s[-2])
    return int(z ** 0.5) ** 2 == z or (int(z ** 0.5) + 1) ** 2 == z


def count_near_square(limit):
    # Digit DP: first digit must be 1, 4, or 9; last-two digit sum is square.
    total = 0
    for length in range(3, len(str(limit)) + 1):
        bound = str(limit) if length == len(str(limit)) else "9" * length
        digits = list(map(int, bound))
        memo = {}

        def dp(pos, tight, first, tens, ones):
            key = (pos, tight, first, tens, ones)
            if key in memo:
                return memo[key]
            if pos == length:
                sm = tens + ones
                return int(first in (1, 4, 9) and sm in (0, 1, 4, 9, 16))
            high = digits[pos] if tight else 9
            low = 1 if pos == 0 else 0
            ans = 0
            for dig in range(low, high + 1):
                nt = int(bool(tight and dig == high))
                nf = dig if pos == 0 else first
                ntens = tens
                nones = ones
                if pos == length - 2:
                    ntens = dig
                if pos == length - 1:
                    nones = dig
                ans += dp(pos + 1, nt, nf, ntens, nones)
            memo[key] = ans
            return ans

        total += dp(0, 1, 0, 0, 0)
    return total


def split_power_two(a):
    n = len(a)
    inf = n + 1
    dp = [inf] * (n + 1)
    dp[0] = 0
    for i in range(n):
        if dp[i] == inf:
            continue
        s = 0
        for j in range(i, n):
            s += a[j]
            if s > 0 and (s & (s - 1)) == 0:
                dp[j + 1] = min(dp[j + 1], dp[i] + 1)
    return -1 if dp[n] == inf else dp[n]


def prime_tokens(s):
    count = 0
    i = 0
    while i < len(s):
        if s[i].isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            value = int(s[i:j])
            count += int(prime(value))
            i = j
        else:
            i += 1
    return count


def solve(problem_id, inp):
    t = inp.split()
    if problem_id == "tuyen-sinh-lam-son-2024":
        q = int(t[0])
        pairs = [tuple(map(int, t[1 + 2*i:3 + 2*i])) for i in range(q)]
        pref = divisor_prime_prefix(max((b for _, b in pairs), default=1))
        return "\n".join(str(pref[b] - pref[a - 1]) for a, b in pairs)
    if problem_id == "chu-vi-dien-tich-hcn":
        d, r = map(int, t[:2])
        return f"{2*(d+r)}\n{d*r}"
    if problem_id == "chia-banh-32bit":
        n, k = map(int, t[:2])
        return f"{n//k}\n{n%k}"
    if problem_id == "mua-vo-32bit":
        n, price = map(int, t[:2])
        return str(n * price)
    if problem_id == "kiem-tra-chan-le-32bit":
        return "CHAN" if int(t[0]) % 2 == 0 else "LE"
    if problem_id == "tong-thi-sinh-18-10-32bit":
        return str(sum(map(int, t[:3])))
    if problem_id == "so-sanh-hai-so-64bit":
        return str(max(map(int, t[:2])))
    if problem_id == "tổng-tích":
        a, b = map(int, t[:2])
        return f"{a+b}\n{a*b}"
    if problem_id == "ve-phim-64":
        return "50000" if int(t[0]) < 12 else "80000"
    if problem_id == "xe-32":
        return "5000" if int(t[0]) <= 2 else "10000"
    if problem_id == "for cơ bản":
        n = int(t[0])
        return str(n * (n + 1) // 2)
    if problem_id == "hsg9-ninh-binh-2026-hinh-chu-nhat":
        a, b, c, d = map(int, t[:4])
        return str(max(a*b, c*d))
    if problem_id == "Ninh Binh-Câu 2":
        n, l, r = map(int, t[:3])
        a = list(map(int, t[3:3+n]))
        values = [str(x) for x in a[l-1:r] if is_special(x)]
        return " ".join(values) if values else "-1"
    if problem_id == "Ninh Binh-Câu 3":
        return str(prime_tokens(t[0]))
    if problem_id == "Ninh Binh-Câu 5":
        return str(count_near_square(int(t[0])))
    if problem_id == "Ninh Binh-Câu 4":
        n = int(t[0])
        return str(split_power_two(list(map(int, t[1:1+n]))))
    raise KeyError(problem_id)


def cases_for(problem, rng, count):
    pid = problem["id"]
    subtasks = problem["subtasks"]
    result = []
    for si, sub in enumerate(subtasks):
        sid = str(sub["id"])
        for k in range(count):
            if pid == "tuyen-sinh-lam-son-2024":
                hi = 199 if si == 0 else 1_000_000
                q = 12
                pairs = []
                for z in range(q):
                    a = rng.randint(1, hi)
                    b = rng.randint(a, hi)
                    pairs.append((a, b))
                inp = str(q) + "\n" + "\n".join(f"{a} {b}" for a,b in pairs)
            elif pid == "chu-vi-dien-tich-hcn":
                d, r = rng.choice([(1,1),(1,1000),(1000,1000),(rng.randint(1,1000),rng.randint(1,1000))])
                inp = f"{d} {r}"
            elif pid == "chia-banh-32bit":
                n, k = rng.randint(1,1000), rng.randint(1,100)
                inp = f"{n} {k}"
            elif pid == "mua-vo-32bit":
                inp = f"{rng.randint(1,1000)} {rng.randint(1,1000)}"
            elif pid == "kiem-tra-chan-le-32bit":
                inp = str(rng.choice([-10**18,10**18,0,-1,1,rng.randint(-10**18,10**18)]))
            elif pid == "tong-thi-sinh-18-10-32bit":
                inp = "\n".join(str(rng.randint(1,100)) for _ in range(3))
            elif pid == "so-sanh-hai-so-64bit":
                a = rng.choice([-10**18,10**18,0,rng.randint(-10**18,10**18)])
                b = rng.choice([-10**18,10**18,0,rng.randint(-10**18,10**18)])
                inp = f"{a} {b}"
            elif pid == "tổng-tích":
                inp = f"{rng.randint(-1000,1000)} {rng.randint(-1000,1000)}"
            elif pid == "ve-phim-64":
                inp = str(rng.choice([1,11,12,13,100,rng.randint(1,100)]))
            elif pid == "xe-32":
                inp = str(rng.choice([1,2,3,24,rng.randint(1,24)]))
            elif pid == "for cơ bản":
                inp = str(rng.choice([1,2,10,10**6,rng.randint(1,10**6)]))
            elif pid == "hsg9-ninh-binh-2026-hinh-chu-nhat":
                hi = 1000 if si == 0 else 10**9
                vals = [rng.randint(1,hi) for _ in range(4)]
                inp = " ".join(map(str, vals))
            elif pid == "Ninh Binh-Câu 2":
                hi = 10**5 if si == 0 else 10**9
                n = 40 if si == 0 else 1000
                a = [rng.randint(1,hi) for _ in range(n)]
                if k % 2 == 0:
                    choices = [1, 2, 5, 12, 15, 24, 36, 128]
                    if si == 1:
                        choices.append(999999937)
                    a[rng.randrange(n)] = rng.choice(choices)
                if si == 1 and k == count - 1:
                    n = 100000
                    a = [rng.randint(1, hi) for _ in range(n)]
                l = rng.randint(1,n)
                r = rng.randint(l,n)
                inp = f"{n} {l} {r}\n" + " ".join(map(str,a))
            elif pid == "Ninh Binh-Câu 3":
                maxlen = 1000 if si == 0 else 3000000
                if si == 0:
                    tokens = [str(rng.randint(0,1000)) for _ in range(80)]
                    inp = "x".join(tokens)
                else:
                    # Long string with many small and near-limit numeric tokens.
                    chunks = []
                    remaining = maxlen
                    while remaining > 0:
                        token = rng.choice(["a2b","c999983d","e1000000f","g999979h","xyz","m17n"])
                        if len(token) > remaining:
                            token = "a" * remaining
                        chunks.append(token)
                        remaining -= len(token)
                    inp = "".join(chunks)
            elif pid == "Ninh Binh-Câu 5":
                maxv = 999 if si == 0 else (10**6 if si == 1 else 10**17)
                if si == 2:
                    inp = "1" + "0" * rng.randint(7,17)
                else:
                    inp = str(rng.randint(100,maxv))
            elif pid == "Ninh Binh-Câu 4":
                nmax = [100,500,1000,2000][si]
                n = nmax if k == count - 1 else rng.randint(1,nmax)
                a = [rng.choice([0,0,1,2,3,4,5,7,8,15,16,20000]) for _ in range(n)]
                if k % 3 == 0:
                    a = [1] * n
                inp = str(n) + "\n" + " ".join(map(str,a))
            else:
                continue
            result.append({"subtask_id": sid, "input": inp})
    return result


def main():
    parser = argparse.ArgumentParser(description="Build generated tests for all problem-bank entries")
    parser.add_argument("--input", default=str(ROOT / "data" / "problems.json"))
    parser.add_argument("--output", default="data/problems.generated.json")
    parser.add_argument("--seed", type=int, default=20261113)
    parser.add_argument("--per-subtask", type=int, default=5)
    parser.add_argument("--report", default="data/testgen_catalog_report.json")
    args = parser.parse_args()
    if args.per_subtask < 1:
        parser.error("--per-subtask must be >= 1")

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    rng = random.Random(args.seed)
    report = {"seed": args.seed, "per_subtask": args.per_subtask, "problems": [], "errors": []}
    total_added = total_old = 0

    for problem in data:
        pid = problem["id"]
        old_count = sum(len(s.get("tests", [])) for s in problem.get("subtasks", []))
        total_old += old_count
        try:
            # Audit stored expected answers against an independent reference.
            old_mismatches = []
            for sub in problem.get("subtasks", []):
                for ti, old_test in enumerate(sub.get("tests", []), 1):
                    actual = solve(pid, old_test["input"])
                    if " ".join(actual.split()) != " ".join(str(old_test["output"]).split()):
                        old_mismatches.append({
                            "subtask": str(sub["id"]), "test": ti,
                            "expected": str(old_test["output"])[:160],
                            "reference": actual[:160]
                        })
            generated = cases_for(problem, rng, args.per_subtask)
            submap = {str(s["id"]): s for s in problem["subtasks"]}
            added = 0
            seen = {sid: {x["input"] for x in sub.get("tests", [])}
                    for sid, sub in submap.items()}
            for case in generated:
                sid = case["subtask_id"]
                if case["input"] in seen[sid]:
                    continue
                output = solve(pid, case["input"])
                # Validate reference result is deterministic before accepting.
                if " ".join(output.split()) != " ".join(solve(pid, case["input"]).split()):
                    raise ValueError("reference solver is non-deterministic")
                submap[sid].setdefault("tests", []).append({"input": case["input"], "output": output})
                seen[sid].add(case["input"])
                added += 1
            total_added += added
            report["problems"].append({
                "id": pid, "title": problem.get("title"),
                "old_tests": old_count, "generated_candidates": len(generated),
                "added_tests": added,
                "total_tests": old_count + added,
                "subtasks": len(problem.get("subtasks", [])),
                "existing_answer_mismatches": old_mismatches,
                "status": "generated" if not old_mismatches else "generated_needs_audit"
            })
        except Exception as exc:
            report["errors"].append({"id": pid, "error": str(exc)})
            report["problems"].append({
                "id": pid, "title": problem.get("title"),
                "old_tests": old_count, "added_tests": 0,
                "status": "needs_review", "reason": str(exc)
            })

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["summary"] = {
        "problems": len(data), "old_tests": total_old,
        "added_tests": total_added,
        "final_tests": total_old + total_added,
        "needs_review": len(report["errors"])
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    for item in report["errors"]:
        print("NEEDS REVIEW:", item["id"], "-", item["error"])
    print("Generated:", out)
    print("Report:", report_path)


if __name__ == "__main__":
    main()
