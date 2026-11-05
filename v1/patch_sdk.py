"""teavm-javac の compile-classlib（javac 用の型情報）の不具合を直す。
@org.teavm.interop.Rename("getMessage") が付いた getMessage0 などのメソッドを、本来の名前に付け替える。
（実行用の runtime-classlib はそのまま。TeaVM は元々この名前で実装を結び付けている）
使い方: python3 patch_sdk.py 入力.bin 出力.bin
"""
import gzip, struct, sys

RENAME = 'Lorg/teavm/interop/Rename;'


class R:
    def __init__(self, b, p=0): self.b, self.p = b, p
    def u1(self): v = self.b[self.p]; self.p += 1; return v
    def u2(self): v = struct.unpack_from('>H', self.b, self.p)[0]; self.p += 2; return v
    def u4(self): v = struct.unpack_from('>I', self.b, self.p)[0]; self.p += 4; return v


def skip_element(r):
    t = chr(r.u1())
    if t in 'BCDFIJSZsc': r.u2()
    elif t == 'e': r.u2(); r.u2()
    elif t == '@': skip_annotation(r)
    elif t == '[':
        for _ in range(r.u2()): skip_element(r)
    else: raise ValueError('bad element tag ' + t)


def skip_annotation(r):
    r.u2()
    for _ in range(r.u2()): r.u2(); skip_element(r)


def patch_class(data):
    r = R(data, 8)
    count = r.u2()
    utf8 = {}
    i = 1
    while i < count:
        tag = r.u1()
        if tag == 1:
            n = r.u2(); utf8[i] = data[r.p:r.p + n].decode('utf-8', 'surrogatepass'); r.p += n
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18): r.p += 4
        elif tag in (5, 6): r.p += 8; i += 1
        elif tag in (7, 8, 16, 19, 20): r.p += 2
        elif tag == 15: r.p += 3
        else: raise ValueError('bad cp tag %d' % tag)
        i += 1
    cp_end = r.p
    r.p += 6
    n_if = r.u2(); r.p += 2 * n_if         # interfaces
    for _ in range(r.u2()):                # fields
        r.p += 6
        for _ in range(r.u2()):
            r.u2(); ln = r.u4(); r.p += ln
    methods = []                           # (name_index の位置, 名前, 記述子, 付け替え後の名前)
    for _ in range(r.u2()):
        r.p += 2
        name_pos = r.p
        name, desc = utf8[r.u2()], utf8[r.u2()]
        target = None
        for _ in range(r.u2()):
            an, ln = utf8[r.u2()], r.u4()
            end = r.p + ln
            if an == 'RuntimeVisibleAnnotations':
                for _ in range(r.u2()):
                    typ = utf8[r.u2()]
                    for _ in range(r.u2()):
                        key = utf8[r.u2()]
                        if typ == RENAME and key == 'value' and data[r.p] == ord('s'):
                            r.p += 1; target = utf8[r.u2()]
                        else:
                            skip_element(r)
            r.p = end
        methods.append((name_pos, name, desc, target))
    existing = {(n, d) for _, n, d, _ in methods}
    # コンストラクタ（<init>）や fakeInit への付け替えは TeaVM 内部用なので触らない
    renames = [(pos, t) for pos, n, d, t in methods
               if t and t != n and not n.startswith('<') and t.isidentifier() and t != 'fakeInit' and (t, d) not in existing]
    if not renames:
        return data, []
    out = bytearray(data)
    extra = bytearray()
    by_name = {v: k for k, v in utf8.items()}
    nxt = count
    for pos, t in renames:
        if t not in by_name:
            enc = t.encode('utf-8')
            extra += bytes([1]) + struct.pack('>H', len(enc)) + enc
            by_name[t] = nxt; nxt += 1
        struct.pack_into('>H', out, pos, by_name[t])
    struct.pack_into('>H', out, 8, nxt)
    out = out[:cp_end] + extra + out[cp_end:]
    return bytes(out), [t for _, t in renames]


def main(src, dst):
    d = gzip.open(src).read()
    p, entries, total = 0, [], 0
    while p < len(d):
        l = struct.unpack_from('>H', d, p)[0]; p += 2
        name = d[p:p + l]; p += l
        sz = struct.unpack_from('>I', d, p)[0]; p += 4
        body = d[p:p + sz]; p += sz
        if name.endswith(b'.class'):
            body, rn = patch_class(body)
            if rn:
                total += len(rn)
                if name.startswith(b'java/lang/'): print(name.decode(), rn)
        entries.append(struct.pack('>H', len(name)) + name + struct.pack('>I', len(body)) + body)
    with open(dst, 'wb') as f:
        f.write(gzip.compress(b''.join(entries), mtime=0))
    print('renamed methods:', total)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
