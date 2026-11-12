import json
import random
from pathlib import Path

# Co dinh seed de moi lan chay tao ra cung mot bo test.
random.seed(20261113)

VALID_CHARS = "BCDEFGIJKLMOPQRSTUVWXYZ"
FORBIDDEN = set("ANH")


def solve(s):
    best = current = 0
    for ch in s:
        if ch in FORBIDDEN:
            current = 0
        else:
            current += 1
            best = max(best, current)
    return str(best if best else -1)


def make_sub1_large(n=100000):
    # Dung chinh xac mot ky tu A, khong co N/H.
    pos_a = random.randrange(n)
    return (
        "".join(random.choices(VALID_CHARS, k=pos_a))
        + "A"
        + "".join(random.choices(VALID_CHARS, k=n - pos_a - 1))
    )


def make_sub3_large(n=100000, forbidden_prob=0.0005):
    # Xau dai co ca ky tu hop le va ky tu cam.
    pool = list(VALID_CHARS) + ["A", "N", "H"]
    weights = [1.0] * len(VALID_CHARS) + [
        forbidden_prob * len(VALID_CHARS) / 3.0
    ] * 3
    return "".join(random.choices(pool, weights=weights, k=n))


def make_adversarial_tests():
    # Cac truong hop bien va cau truc de bat loi cap nhat max/phan tach doan.
    return [
        "B" * 100000,                              # Khong co ky tu cam
        "ANH" * 33333 + "A",                      # Toan ky tu cam
        "BA" * 50000,                              # Ky tu cam xen ke
        "A" + "B" * 99998 + "N",                  # Doan hop le dai o giua
        ("BBBBAN" * 16666) + "BB",                # Nhieu doan dai bang nhau
        "B" * 49999 + "A" + "C" * 50000,          # Ky tu cam duy nhat o giua
        "N" + "Z" * 99998 + "H",                 # Ky tu cam o hai dau
        "B" * 49998 + "ANH" + "C" * 49999,        # Cum ky tu cam o giua
        "A" + "B" * 99999,                         # Ky tu cam dau xau
        "B" * 99999 + "H",                         # Ky tu cam cuoi xau
    ]


data = [
    {
        "id": "XAU_KY_TU",
        "title": "Xâu kí tự",
        "category": "Xâu ký tự",
        "difficulty": "Trung bình",
        "statement": "Cho xâu kí tự S chỉ chứa các kí tự IN HOA trong bảng chữ cái tiếng Anh.\n\nYêu cầu: Tìm độ dài lớn nhất của xâu con liên tiếp không chứa một trong các kí tự 'A', 'N', 'H'.\n\nNếu không có xâu con liên tiếp thỏa mãn thì ghi ra -1.",
        "input": "Vào từ tệp CAU2.INP gồm:\n- Dòng đầu tiên ghi số nguyên dương T là số lượng xâu (T <= 10).\n- T dòng tiếp theo, mỗi dòng ghi một xâu kí tự có độ dài không quá 10^5 kí tự.",
        "output": "Ghi ra tệp CAU2.OUT gồm T dòng, mỗi dòng một số nguyên là độ dài xâu con liên tiếp tìm được theo yêu cầu. Nếu không có xâu con liên tiếp thỏa mãn thì ghi ra -1.",
        "input_format": "Dòng đầu tiên chứa số nguyên T. T dòng tiếp theo, mỗi dòng chứa một xâu S chỉ gồm chữ cái IN HOA tiếng Anh.",
        "output_format": "Gồm T dòng, mỗi dòng là độ dài lớn nhất của xâu con liên tiếp không chứa A, N, H; nếu không tồn tại thì in -1.",
        "sample_input": "3\nABRBCDAB\nLCKHABWCHTHUR\nANHA",
        "sample_output": "5\n3\n-1",
        "explanation": "Xâu 1: Xâu con liên tiếp dài nhất thỏa mãn là BRBCD, có độ dài 5.\nXâu 2: Có hai xâu con liên tiếp dài nhất là LCK và BWC, đều có độ dài 3.\nXâu 3: Không có xâu con nào thỏa mãn.",
        "time_limit": 1.0,
        "memory_limit": 256000,
        "total_score": 100,
        "use_freopen": True,
        "input_file": "CAU2.INP",
        "output_file": "CAU2.OUT",
        "subtasks": [
            {
                "id": "SUB1",
                "name": "Subtask 1",
                "score": 30,
                "constraints": "Có 30% số điểm có xâu đầu vào chỉ có một kí tự A và không có N, H.",
                "tests": [
                    {"input": "1\nABCDE", "output": "4"},
                    {"input": "1\nBCDAEFG", "output": "3"},
                    {"input": "1\nXYZABCD", "output": "4"},
                    {"input": "1\nA", "output": "-1"},
                ],
            },
            {
                "id": "SUB2",
                "name": "Subtask 2",
                "score": 30,
                "constraints": "Có 30% số điểm có xâu đầu vào có một kí tự A, một kí tự H, không có kí tự N và độ dài xâu không quá 10^2.",
                "tests": [
                    {"input": "1\nABCHDE", "output": "2"},
                    {"input": "1\nABCDEHFG", "output": "3"},
                    {"input": "1\nHABCXYZ", "output": "3"},
                    {"input": "1\nAH", "output": "-1"},
                ],
            },
            {
                "id": "SUB3",
                "name": "Subtask 3",
                "score": 40,
                "constraints": "40% số điểm còn lại không có ràng buộc gì thêm.",
                "tests": [
                    {"input": "3\nABRBCDAB\nLCKHABWCHTHUR\nANHA", "output": "5\n3\n-1"},
                    {"input": "2\nBCDFG\nANH", "output": "5\n-1"},
                    {"input": "2\nBCANHDEFG\nXYZ", "output": "4\n3"},
                    {"input": "2\nAAAA\nBCNHDE", "output": "-1\n2"},
                    {"input": "1\nBANANA", "output": "-1"},
                    {"input": "1\nQWERTY", "output": "6"},
                ],
            },
        ],
    }
]

# Hai test lon cho SUB1: moi test gom 10 xau, moi xau dai 100.000.
for _ in range(2):
    strings = [make_sub1_large(100000) for _ in range(10)]
    data[0]["subtasks"][0]["tests"].append({
        "input": "10\n" + "\n".join(strings),
        "output": "\n".join(solve(s) for s in strings),
    })

# Test lon cho SUB3: nua dau khong co ky tu cam, nua sau co ky tu cam thua.
strings_max = (
    ["".join(random.choices(VALID_CHARS, k=100000)) for _ in range(5)]
    + [make_sub3_large(100000, 0.0002) for _ in range(5)]
)
data[0]["subtasks"][2]["tests"].append({
    "input": "10\n" + "\n".join(strings_max),
    "output": "\n".join(solve(s) for s in strings_max),
})

strings_mix = [make_sub3_large(100000, 0.05) for _ in range(10)]
data[0]["subtasks"][2]["tests"].append({
    "input": "10\n" + "\n".join(strings_mix),
    "output": "\n".join(solve(s) for s in strings_mix),
})

# Them cac test doi khang co kich thuoc lon vao SUB3.
extra = make_adversarial_tests()
data[0]["subtasks"][2]["tests"].append({
    "input": str(len(extra)) + "\n" + "\n".join(extra),
    "output": "\n".join(solve(s) for s in extra),
})

output_path = Path("XAU_KY_TU.json")
output_path.write_text(
    json.dumps(data, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(f"Da xuat {output_path} voi {sum(len(s['tests']) for s in data[0]['subtasks'])} test groups.")
