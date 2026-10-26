import json, math, re
from pathlib import Path
P=json.loads((Path(__file__).resolve().parents[1] / 'data' / 'problems.json').read_text(encoding='utf-8'))
def solve(stmt, raw):
    if stmt.startswith('Cho hai số nguyên a, b. In tổng'): a,b=map(int,raw.split()); return str(a+b)
    if stmt.startswith('Cho hai số nguyên a, b. In a-b'): a,b=map(int,raw.split()); return str(a-b)
    if stmt.startswith('Cho hai số nguyên a, b. In a*b'): a,b=map(int,raw.split()); return str(a*b)
    if stmt=='Cho hai số nguyên a, b. In số lớn hơn.': a,b=map(int,raw.split()); return str(max(a,b))
    if stmt=='Cho hai số nguyên a, b. In số nhỏ hơn.': a,b=map(int,raw.split()); return str(min(a,b))
    if stmt=='Cho số nguyên n. In |n|.': return str(abs(int(raw)))
    if 'In EVEN nếu n chẵn' in stmt: return 'EVEN' if int(raw)%2==0 else 'ODD'
    if 'In -1 nếu n<0' in stmt: n=int(raw); return str(-1 if n<0 else 1 if n>0 else 0)
    if stmt=='Cho số nguyên không âm n. In tổng các chữ số của n.': return str(sum(map(int,raw.strip())))
    if 'In số chữ số của n' in stmt: return str(len(raw.strip()))
    if 'In số thu được khi đảo chữ số' in stmt: return str(int(raw.strip()[::-1]))
    if 'biểu diễn thập phân của n đối xứng' in stmt: return 'YES' if raw.strip()==raw.strip()[::-1] else 'NO'
    if 'In UCLN(a,b)' in stmt: a,b=map(int,raw.split()); return str(math.gcd(a,b))
    if 'In BCNN(a,b)' in stmt: a,b=map(int,raw.split()); return str(math.lcm(a,b))
    if 'In YES nếu n là số nguyên tố' in stmt:
        n=int(raw); return 'YES' if n>=2 and all(n%d for d in range(2,math.isqrt(n)+1)) else 'NO'
    if 'In n!.' in stmt: return str(math.factorial(int(raw)))
    if 'In a^b mod m.' in stmt: a,b,m=map(int,raw.split()); return str(pow(a,b,m))
    if 'In 1+2+...+n.' in stmt: n=int(raw); return str(n*(n+1)//2)
    if 'In n^2.' in stmt: n=int(raw); return str(n*n)
    if 'In n^3.' in stmt: n=int(raw); return str(n*n*n)
    if 'ba số nguyên a,b,c. In số lớn nhất' in stmt: return str(max(map(int,raw.split())))
    if 'ba số nguyên a,b,c. In số nhỏ nhất' in stmt: return str(min(map(int,raw.split())))
    if 'In giá trị đứng giữa khi sắp xếp' in stmt: return str(sorted(map(int,raw.split()))[1])
    if 'In hiệu giữa số lớn nhất và nhỏ nhất' in stmt: x=list(map(int,raw.split())); return str(max(x)-min(x))
    if 'Tính tổng các chữ số chẵn của n' in stmt: return str(sum(int(c) for c in raw.strip() if int(c)%2==0))
    if 'Đếm chữ số chẵn của n' in stmt: return str(sum(int(c)%2==0 for c in raw.strip()))
    if 'Đếm số lần chữ số 7 xuất hiện' in stmt: return str(raw.strip().count('7'))
    if 'In chữ số đầu tiên của n' in stmt: return raw.strip()[0]
    if 'In chữ số cuối cùng của n' in stmt: return raw.strip()[-1]
    if 'In F_n' in stmt:
        n=int(raw); a,b=0,1
        for _ in range(n): a,b=b,a+b
        return str(a)
    if 'chia hết cho 3' in stmt: return 'YES' if int(raw)%3==0 else 'NO'
    if 'với k khác 0' in stmt: n,k=map(int,raw.split()); return 'YES' if n%k==0 else 'NO'
    if 'trung bình cộng với đúng 2 chữ số' in stmt: a=list(map(int,raw.split())); return f'{sum(a)/3:.2f}'
    if 'In chúng theo thứ tự tăng dần' in stmt: return ' '.join(map(str,sorted(map(int,raw.split()))))
    if stmt=='Cho n và n số nguyên. In tổng các phần tử.': x=list(map(int,raw.split())); return str(sum(x[1:x[0]+1]))
    if stmt=='Cho n và n số nguyên. In phần tử lớn nhất.': x=list(map(int,raw.split())); return str(max(x[1:x[0]+1]))
    if stmt=='Cho n và n số nguyên. In phần tử nhỏ nhất.': x=list(map(int,raw.split())); return str(min(x[1:x[0]+1]))
    if 'Đếm số phần tử chẵn' in stmt: x=list(map(int,raw.split())); return str(sum(v%2==0 for v in x[1:x[0]+1]))
    if 'Đếm số phần tử dương' in stmt: x=list(map(int,raw.split())); return str(sum(v>0 for v in x[1:x[0]+1]))
    if 'In số lượng giá trị khác nhau' in stmt: x=list(map(int,raw.split())); return str(len(set(x[1:x[0]+1])))
    if stmt=='Cho n và n số nguyên. In dãy tăng dần.': x=list(map(int,raw.split())); return ' '.join(map(str,sorted(x[1:x[0]+1])))
    if stmt=='Cho n và n số nguyên. In dãy theo thứ tự ngược lại.': x=list(map(int,raw.split())); return ' '.join(map(str,x[1:x[0]+1][::-1]))
    if 'giá trị lớn thứ hai phân biệt' in stmt: x=list(map(int,raw.split())); return str(sorted(set(x[1:x[0]+1]),reverse=True)[1])
    if 'Đếm số lần x xuất hiện' in stmt: x=list(map(int,raw.split())); n,k=x[:2]; return str(x[2:2+n].count(k))
    if 'vị trí (đánh số từ 1) đầu tiên' in stmt: x=list(map(int,raw.split())); n,k=x[:2]; a=x[2:2+n]; return str(a.index(k)+1 if k in a else -1)
    if 'vị trí (n+1)//2' in stmt: x=list(map(int,raw.split())); n=x[0]; return str(sorted(x[1:1+n])[(n+1)//2-1])
    if 'độ dài lớn nhất của đoạn liên tiếp' in stmt:
        x=list(map(int,raw.split())); a=x[1:x[0]+1]; best=cur=1
        for i in range(1,len(a)):
            cur=cur+1 if a[i]==a[i-1] else 1; best=max(best,cur)
        return str(best)
    if 'In biểu diễn nhị phân của n' in stmt: return bin(int(raw))[2:]
    if 'chữ số 0 ở cuối n!' in stmt:
        n=int(raw); z=0
        while n: n//=5; z+=n
        return str(z)
    if 'In YES nếu n là số chính phương' in stmt: n=int(raw); return 'YES' if math.isqrt(n)**2==n else 'NO'
    if 'Tính tổng các phần tử lẻ' in stmt: x=list(map(int,raw.split())); return str(sum(v for v in x[1:x[0]+1] if v%2))
    if 'In giá trị lớn nhất của dãy' in stmt: x=list(map(int,raw.split())); return str(max(x[1:x[0]+1]))
    if 'Đếm số từ;' in stmt: return str(len(raw.split()))
    if 'Đếm các nguyên âm' in stmt: return str(sum(c.lower() in 'aeiou' for c in raw if c.isalpha()))
    if stmt=='Cho một dòng ký tự. In dòng đó theo thứ tự ngược lại.': return raw.rstrip('\n')[::-1]
    if 'xâu đối xứng' in stmt: return 'YES' if raw.strip()==raw.strip()[::-1] else 'NO'
    if 'Đếm số ký tự khác nhau phân biệt hoa thường' in stmt: return str(len(set(raw.rstrip('\n'))))
    if 'Đếm số chữ cái Latin in hoa' in stmt: return str(sum('A'<=c<='Z' for c in raw))
    if 'Thay mỗi dấu cách bằng dấu gạch dưới' in stmt: return raw.rstrip('\n').replace(' ','_')
    if 'xóa tất cả chữ số 0..9' in stmt: return ''.join(c for c in raw.rstrip('\n') if not c.isdigit())
    if "ký tự a thường xuất hiện" in stmt: return str(raw.count('a'))
    raise ValueError(stmt)
errors=[]; checked=0
for p in P:
 for s in p['subtasks']:
  for i,t in enumerate(s['tests'],1):
   checked+=1
   try: got=solve(p['statement'],t['input'])
   except Exception as e: errors.append((p['id'],i,'EXC',str(e),p['statement'])); continue
   exp=t['output'].strip()
   if got.strip()!=exp: errors.append((p['id'],i,got,exp,p['statement']))
def test_all_reference_outputs_match_every_hidden_test():
    assert not errors, f'{len(errors)} reference-output mismatches among {checked} tests: {errors[:25]}'
