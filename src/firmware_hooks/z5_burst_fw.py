"""Z5 C 1.50: burst-rate entry on top of the group 108 firmware (MAIN only, official update; boot area untouched).

    python -B research/burst/z5_burst_fw.py firmware-input/Z_5_0150.bin --out output/<new dir>/EG165050.BIN
    (run inside output/phase0-*/enter-environment.ps1)

L25 (2026-11-14): silent burst arrives with code 2-4 (camera: code 4 only changed the mechanical burst).

0x10192F96 maps a speed code (r0, 0-13) to the burst interval in ms: 1000 500 333 250 222 166 142 125 111 100
90 83 76 71; with r2 == 1 (silent) codes 2-4 give 400. The new entry replaces its first 4 bytes
(push {r4-r6, lr}; movs r4, #0) with a branch to a stub. The stub changes the arguments only for code 4
with r2 != 1 (mechanical high speed) and codes 2-4 with r2 == 1 (silent), and only when the SDK state block P (anchor pair P, ~P at 0xC18F8120) holds a
setting written by a card module that knows it:
    P + 0x18 = 0xB500_0000 | silent_code << 8 | mech_code,   P + 0x1C = ~(P + 0x18)
    mech_code   (1-13): new code when r2 != 1 and code == 4;    0 = keep
    silent_code (1-13): new code and r2 = 0 when r2 == 1 and code is 2-4;    0 = keep
The block is zeroed when it is allocated and no released module writes those words, so with no module,
an older module or no setting, the function runs exactly as stock. The stub never calls the module.
Writes only new files. camera_verified: false.
"""
import hashlib
import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'vertical-ui'))
import z5_vui_hooks as vh  # noqa: E402
from z5mod_fw.engine import Edit, Feature  # noqa: E402

dd, gz = vh.dd, vh.gz
SITE = 0x10192F96
EXPECTED = bytes.fromhex('70b50024')          # push {r4, r5, r6, lr}; movs r4, #0
GROUP108_SHA256 = '6389847f5ae1e65fb8b06569bde48252486ec1818041b076b03263c562b604bf'
MAGIC = 0xB500
TABLE = [1000, 500, 333, 250, 222, 166, 142, 125, 111, 100, 90, 83, 76, 71]

STUB = '''
    .balign 4
    .global burst
    .thumb_func
burst:
    ldr     r3, =%(anchor)#x
    ldr     r12, [r3]
    ldr     r3, [r3, #4]
    mvns    r3, r3
    cmp     r12, r3
    bne     9f
    ldr     r3, =%(lo)#x
    cmp     r12, r3
    blo     9f
    ldr     r3, =%(hi)#x
    cmp     r12, r3
    bhs     9f
    ldr     r3, [r12, #0x18]
    ldr     r12, [r12, #0x1c]
    mvns    r12, r12
    cmp     r3, r12
    bne     9f
    lsrs    r12, r3, #16
    cmp.w   r12, #%(magic)#x
    bne     9f
    cmp     r2, #1
    beq     1f
    cmp     r0, #4
    bne     9f
    uxtb    r12, r3
    b       2f
1:  cmp     r0, #2
    blo     9f
    cmp     r0, #4
    bhi     9f
    ubfx    r12, r3, #8, #8
2:  cmp.w   r12, #0
    beq     9f
    cmp.w   r12, #14
    bhs     9f
    mov     r0, r12
    cmp     r2, #1
    bne     9f
    movs    r2, #0
9:  push    {r4, r5, r6, lr}
    movs    r4, #0
    ldr     pc, =%(back)#x
    .ltorg
''' % dict(anchor=gz.ANCHOR, lo=gz.RAM_LO, hi=gz.RAM_HI, magic=MAGIC, back=(SITE + 4) | 1)

_source, _feature = vh.source, vh.feature


def source():
    return _source() + STUB


def feature(stock, at):
    f, syms = _feature(stock, at)
    veneer = vh.VENEERS + 8 * (len(vh.HOOKS) + 1)          # after the text veneer: earlier veneers stay put
    if stock[SITE - vh.BASE:SITE - vh.BASE + 4] != EXPECTED:
        raise SystemExit('burst site differs from the expected bytes')
    edits = f.edits + (
        Edit('burst_veneer', veneer - vh.BASE, bytes(8), bytes.fromhex('dff800f0') + struct.pack('<I', syms['burst'] | 1)),
        Edit('burst_rate', SITE - vh.BASE, EXPECTED, vh.branch(SITE, veneer, False)),
    )
    return Feature(name=f.name, description=f.description + '; burst-rate entry', camera_verified=False,
                   edits=edits, appends=f.appends), syms


def run_rate(image, code, flag, cfg):
    """Call 0x10192F96(code, 0, flag) in Unicorn; the setting read 0x101EDE04 returns 0."""
    from unicorn import UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
    u = dd.machine(image)
    ram = 0xC18F8000
    u.mem_map(ram, 0x2000)
    block = ram + 0x1000
    if cfg is not None:
        u.mem_write(gz.ANCHOR, struct.pack('<II', block, ~block & 0xFFFFFFFF))
        u.mem_write(block + 0x18, struct.pack('<II', cfg, ~cfg & 0xFFFFFFFF))
    done = 0x50000100
    def hook(mu, pc, size, unused):
        if pc == 0x101EDE04:                    # setting 0x494: not 1
            mu.reg_write(UC_ARM_REG_R0, 0)
            mu.reg_write(UC_ARM_REG_PC, mu.reg_read(UC_ARM_REG_LR))
        elif pc == done:
            mu.emu_stop()
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_ARM_REG_R0, code); u.reg_write(UC_ARM_REG_R1, 0); u.reg_write(UC_ARM_REG_R2, flag)
    u.reg_write(UC_ARM_REG_SP, 0x50000800); u.reg_write(UC_ARM_REG_LR, done | 1)
    u.emu_start(SITE | 1, 0, count=400)
    return u.reg_read(UC_ARM_REG_R0)


def verify(stock, image):
    rows, n = [], 0
    for code in range(15):
        for flag in (0, 1, 2):
            want = run_rate(stock, code, flag, None)
            for cfg in (None, 0, 0x12345678):        # no block, zero setting, garbage without the pair
                got = run_rate(image, code, flag, cfg); n += 1
                assert got == want, ('unset differs', code, flag, cfg, got, want)
            for mech in range(0, 15):
                for silent in (0, 5, 13, 14):
                    cfg = MAGIC << 16 | silent << 8 | mech
                    got = run_rate(image, code, flag, cfg); n += 1
                    exp = want
                    if flag == 1 and 2 <= code <= 4 and 0 < silent < 14: exp = TABLE[silent]
                    if flag != 1 and code == 4 and 0 < mech < 14: exp = TABLE[mech]
                    assert got == exp, ('set differs', code, flag, hex(cfg), got, exp)
            rows.append((code, flag, want))
    return dict(passed=True, calls=n, stock=[f'code {c} flag {f}: {w}' for c, f, w in rows if c in (2, 3, 4, 5)])


def build(package, out):
    vh.source, vh.feature = source, feature
    vh.build(package, out)
    from z5mod_fw import container
    _, mods = container.load(package)
    stock = container.main_module(mods).data
    image = out.read_bytes()
    dd.windows = lambda: [(SITE, SITE + 4)]
    incoming = dd.audit_incoming(stock)
    if incoming:
        raise SystemExit(f'branches land inside the burst window: {incoming}')
    report = dict(burst_rate=dict(site=hex(SITE), expected=EXPECTED.hex(), magic=hex(MAGIC), base_group108=GROUP108_SHA256,
                                  incoming_branch_audit=dict(found=incoming), unicorn=verify(stock, image)))
    rp = out.with_name(out.name + '.json')
    data = json.loads(rp.read_text(encoding='utf-8'))
    data.update(report)
    rp.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['burst_rate']['unicorn'], indent=1))


if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) != 3 or args[1] != '--out':
        raise SystemExit(__doc__)
    build(pathlib.Path(args[0]), pathlib.Path(args[2]))
