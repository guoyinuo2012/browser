"""Self-contained QR Code encoder for browser (offline, no dependencies).

Byte-mode (UTF-8) QR codes, versions 1-10, all four ECC levels, all eight
mask patterns with automatic penalty-based selection.

Layout construction order (per ISO/IEC 18004):
  finders → timing → alignment → data (with mask applied inline) →
  format info → version info. One matrix per mask; lowest penalty wins.

Self-checks used by the test suite:
  * Reed-Solomon syndromes of every generated codeword sequence are zero.
  * Format information matches the spec's published constants
    (L/M0/H7 = 111011111000100 / 101010000010010 / 110011000101111).
  * Version information for v7 matches 0x07C94.
  * Alignment pattern tables match ISO/IEC 18004.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# GF(256) arithmetic, primitive polynomial 0x11D
# --------------------------------------------------------------------------- #
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> list[int]:
    g = [1]
    for i in range(degree):
        ng = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            ng[j] ^= _gf_mul(c, _EXP[i])
            ng[j + 1] ^= c
        g = ng
    return g[::-1]  # highest degree first


def rs_encode(data: list[int], degree: int) -> list[int]:
    """Reed-Solomon ECC generator encoding of data polynomial."""
    gen = _rs_generator(degree)
    rem = [0] * degree
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        if factor:
            for i, g in enumerate(gen[1:]):
                rem[i] ^= _gf_mul(g, factor)
    return rem


def rs_syndromes(codeword: list[int], nsym: int) -> list[int]:
    """Syndrome polynomial; all zeros means the block decodes cleanly."""
    syn = []
    for i in range(nsym):
        s = 0
        for c in codeword:
            s = _gf_mul(s, _EXP[i]) ^ c
        syn.append(s)
    return syn


# --------------------------------------------------------------------------- #
# Version / ECC tables (ISO/IEC 18004)
# --------------------------------------------------------------------------- #
# (ec per block, short blocks, long blocks, short data cw, long data cw)
_ECC_TABLE: dict[int, dict[str, tuple[int, int, int, int, int]]] = {
    1: {"L": (7, 1, 0, 19, 0), "M": (10, 1, 0, 16, 0), "Q": (13, 1, 0, 13, 0), "H": (17, 1, 0, 9, 0)},
    2: {"L": (10, 1, 0, 34, 0), "M": (16, 1, 0, 28, 0), "Q": (22, 1, 0, 22, 0), "H": (28, 1, 0, 16, 0)},
    3: {"L": (15, 1, 0, 55, 0), "M": (26, 1, 0, 44, 0), "Q": (18, 2, 0, 17, 0), "H": (22, 2, 0, 13, 0)},
    4: {"L": (20, 1, 0, 80, 0), "M": (18, 2, 0, 32, 0), "Q": (26, 2, 0, 24, 0), "H": (16, 4, 0, 9, 0)},
    5: {"L": (26, 1, 0, 108, 0), "M": (24, 2, 0, 43, 0), "Q": (18, 2, 2, 15, 16), "H": (22, 2, 2, 11, 12)},
    6: {"L": (18, 2, 0, 68, 0), "M": (16, 4, 0, 27, 0), "Q": (24, 4, 0, 19, 0), "H": (28, 4, 0, 15, 0)},
    7: {"L": (20, 2, 0, 78, 0), "M": (18, 4, 0, 31, 0), "Q": (18, 2, 4, 14, 15), "H": (26, 4, 1, 13, 14)},
    8: {"L": (24, 2, 0, 97, 0), "M": (22, 2, 2, 38, 39), "Q": (22, 4, 2, 18, 19), "H": (26, 4, 2, 14, 15)},
    9: {"L": (30, 2, 0, 116, 0), "M": (22, 3, 2, 36, 37), "Q": (20, 4, 4, 16, 17), "H": (24, 4, 4, 12, 13)},
    10: {"L": (18, 2, 2, 68, 69), "M": (26, 4, 1, 43, 44), "Q": (24, 6, 2, 19, 20), "H": (28, 6, 2, 15, 16)},
}

_ALIGNMENT = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

_TOTAL_CW = {1: 26, 2: 44, 3: 70, 4: 100, 5: 134, 6: 172, 7: 196, 8: 242, 9: 292, 10: 346}


def _capacity_bytes(version: int, level: str) -> int:
    _ec, short_b, long_b, short_cw, long_cw = _ECC_TABLE[version][level]
    data_cw = short_b * short_cw + long_b * long_cw
    return data_cw - 2  # 4-bit mode + 8-bit count overhead


def pick_version(length: int, level: str) -> int:
    """Choose QR version and ECC block layout for the data length."""
    for v in range(1, 11):
        if length <= _capacity_bytes(v, level):
            return v
    raise ValueError(f"data too long for QR v1-10 ({length} bytes); "
                     f"max {_capacity_bytes(10, level)}")


# --------------------------------------------------------------------------- #
# Bit stream
# --------------------------------------------------------------------------- #
class BitBuffer:
    """Bit-accumulating buffer used during QR encoding."""
    def __init__(self) -> None:
        self.bits: list[int] = []

    def push(self, value: int, n: int) -> None:
        for i in range(n - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def to_bytes(self, target_len: int) -> list[int]:
        data = []
        for i in range(0, len(self.bits), 8):
            chunk = list(self.bits[i:i + 8])
            while len(chunk) < 8:
                chunk.append(0)
            b = 0
            for bit in chunk:
                b = (b << 1) | bit
            data.append(b)
        pads = [0xEC, 0x11]
        i = 0
        while len(data) < target_len:
            data.append(pads[i % 2])
            i += 1
        return data


# --------------------------------------------------------------------------- #
# Format / version BCH codes
# --------------------------------------------------------------------------- #
_LEVEL_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}


def format_bits(level: str, mask: int) -> int:
    """The 15-bit format information (ECC level + mask) with BCH."""
    data = (_LEVEL_BITS[level] << 3) | mask
    v = data << 10
    g = 0x537
    for bit in range(9, -1, -1):
        if v & (1 << (bit + 10)):
            v ^= g << bit
    return ((data << 10) | (v & 0x3FF)) ^ 0x5412


def version_bits(version: int) -> int:
    """The 18-bit version information block for versions >= 7."""
    v = version << 12
    g = 0x1F25
    for bit in range(11, -1, -1):
        if v & (1 << (bit + 12)):
            v ^= g << bit
    return (version << 12) | (v & 0xFFF)


# --------------------------------------------------------------------------- #
# Matrix construction
# --------------------------------------------------------------------------- #
def _build_function_patterns(version: int) -> list[list[int | None]]:
    size = 17 + version * 4
    m: list[list[int | None]] = [[None] * size for _ in range(size)]

    def finder(row: int, col: int) -> None:
        for dr in range(7):
            for dc in range(7):
                v = (dr in (0, 6) or dc in (0, 6) or
                     (2 <= dr <= 4 and 2 <= dc <= 4))
                m[row + dr][col + dc] = 1 if v else 0
        for i in range(8):  # separators
            for r, c in ((row - 1, col + i), (row + 7, col + i)):
                if 0 <= r < size and 0 <= c < size:
                    m[r][c] = 0
            for r, c in ((row + i, col - 1), (row + i, col + 7)):
                if 0 <= r < size and 0 <= c < size:
                    m[r][c] = 0

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)

    # timing patterns
    for i in range(8, size - 8):
        m[6][i] = 1 if i % 2 == 0 else 0
        m[i][6] = 1 if i % 2 == 0 else 0

    # alignment patterns (skip anything already drawn)
    centers = _ALIGNMENT[version]
    for r in centers:
        for c in centers:
            if m[r][c] is not None:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    dist = max(abs(dr), abs(dc))
                    dark = dist in (0, 2)
                    m[r + dr][c + dc] = 1 if dark else 0
    return m


def _place_data(m, codewords: list[int], mask: int) -> None:
    size = len(m)
    total_bits = len(codewords) * 8
    bit_i = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        for step in range(size):
            row = (size - 1 - step) if upward else step
            for c in (col, col - 1):
                if m[row][c] is not None:
                    continue
                bit = 0
                if bit_i < total_bits:
                    bit = (codewords[bit_i // 8] >> (7 - (bit_i % 8))) & 1
                bit_i += 1
                if _mask_fn(mask, row, c):
                    bit ^= 1
                m[row][c] = bit
        upward = not upward
        col -= 2


def _mask_fn(mask: int, r: int, c: int) -> bool:
    if mask == 0:
        return (r + c) % 2 == 0
    if mask == 1:
        return r % 2 == 0
    if mask == 2:
        return c % 3 == 0
    if mask == 3:
        return (r + c) % 3 == 0
    if mask == 4:
        return (r // 2 + c // 3) % 2 == 0
    if mask == 5:
        return (r * c) % 2 + (r * c) % 3 == 0
    if mask == 6:
        return ((r * c) % 2 + (r * c) % 3) % 2 == 0
    return ((r * c) % 3 + (r + c) % 2) % 2 == 0


def _place_format(m, level: str, mask: int) -> None:
    size = len(m)
    fb = format_bits(level, mask)
    bits = [(fb >> (14 - i)) & 1 for i in range(15)]
    coords1 = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7),
               (8, 8), (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
    for i, (r, c) in enumerate(coords1):
        m[r][c] = bits[i]
    coords2 = [(size - 1, 8), (size - 2, 8), (size - 3, 8), (size - 4, 8),
               (size - 5, 8), (size - 6, 8), (size - 7, 8),
               (8, size - 8), (8, size - 7), (8, size - 6), (8, size - 5),
               (8, size - 4), (8, size - 3), (8, size - 2), (8, size - 1)]
    for i, (r, c) in enumerate(coords2):
        m[r][c] = bits[i]
    m[size - 8][8] = 1  # dark module


def _place_version(m, version: int) -> None:
    if version < 7:
        return
    size = len(m)
    vb = version_bits(version)
    bits = [(vb >> (17 - i)) & 1 for i in range(18)]
    for i in range(18):
        r = size - 11 + i % 3
        c = i // 3
        m[r][c] = bits[i]
        m[c][r] = bits[i]


def _penalty(m) -> int:
    size = len(m)
    p = 0
    # N1: runs of 5+ identical modules
    for r in range(size):
        run = 1
        for c in range(1, size):
            if m[r][c] == m[r][c - 1]:
                run += 1
            else:
                if run >= 5: p += 3 + run - 5
                run = 1
        if run >= 5: p += 3 + run - 5
    for c in range(size):
        run = 1
        for r in range(1, size):
            if m[r][c] == m[r - 1][c]:
                run += 1
            else:
                if run >= 5: p += 3 + run - 5
                run = 1
        if run >= 5: p += 3 + run - 5
    # N2: 2x2 blocks
    for r in range(size - 1):
        for c in range(size - 1):
            v = m[r][c]
            if m[r][c + 1] == v and m[r + 1][c] == v and m[r + 1][c + 1] == v:
                p += 3
    # N3: 1011101 with 0000 on either side
    pats = (0b10111010000, 0b00001011101)
    for r in range(size):
        for c in range(size - 10):
            v = 0
            for i in range(11):
                v = (v << 1) | m[r][c + i]
            if v in pats: p += 40
    for c in range(size):
        for r in range(size - 10):
            v = 0
            for i in range(11):
                v = (v << 1) | m[r + i][c]
            if v in pats: p += 40
    # N4: dark module ratio
    dark = sum(row.count(1) for row in m)
    deviation = abs(dark * 100 // (size * size) - 50)
    p += (deviation // 5) * 10
    return p


def encode(text: str, level: str = "M") -> list[list[int]]:
    """Encode text into a QR matrix of 0/1 (1 = dark)."""
    if not text:
        raise ValueError("cannot encode empty text")
    data = text.encode("utf-8")
    version = pick_version(len(data), level)
    ec, short_b, long_b, short_cw, long_cw = _ECC_TABLE[version][level]
    blocks = short_b + long_b
    data_cw_total = short_b * short_cw + long_b * long_cw

    buf = BitBuffer()
    buf.push(4, 4)             # byte mode indicator
    buf.push(len(data), 8)     # char count, versions 1-10
    for b in data:
        buf.push(b, 8)
    raw = buf.to_bytes(data_cw_total)

    block_cws = [short_cw if b < short_b else long_cw for b in range(blocks)]
    data_blocks, idx = [], 0
    for n in block_cws:
        data_blocks.append(raw[idx:idx + n])
        idx += n
    ecc_blocks = [rs_encode(db, ec) for db in data_blocks]

    # RS integrity self-check
    for db, eb, n in zip(data_blocks, ecc_blocks, block_cws):
        syn = rs_syndromes(db + eb, ec)
        assert all(s == 0 for s in syn), "Reed-Solomon self-check failed"

    # interleave
    final: list[int] = []
    for i in range(max(block_cws)):
        for db, n in zip(data_blocks, block_cws):
            if i < n:
                final.append(db[i])
    for i in range(ec):
        for eb in ecc_blocks:
            final.append(eb[i])
    assert len(final) == _TOTAL_CW[version]

    best, best_score = None, None
    for mask in range(8):
        m = _build_function_patterns(version)
        _place_data(m, final, mask)
        _place_format(m, level, mask)
        _place_version(m, version)
        score = _penalty(m)
        if best_score is None or score < best_score:
            best_score, best = score, m
    return best


def to_svg(matrix: list[list[int]], quiet_zone: int = 4, dark: str = "#1a1a1a",
           light: str = "#ffffff") -> str:
    """Render a QR matrix as a self-contained SVG string."""
    size = len(matrix)
    total = size + quiet_zone * 2
    rects = []
    for r in range(size):
        for c in range(size):
            if matrix[r][c]:
                rects.append(
                    f'<rect x="{c + quiet_zone}" y="{r + quiet_zone}" width="1" height="1"/>')
    body = "".join(rects)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
            f'shape-rendering="crispEdges">'
            f'<rect width="{total}" height="{total}" fill="{light}"/>'
            f'<g fill="{dark}">{body}</g></svg>')
