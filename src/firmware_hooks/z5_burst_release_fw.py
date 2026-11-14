"""Z5 C 1.50: release firmware for the burst speed-up = group 108 (portrait UI hooks) + three burst entries.
No loggers. MAIN only, through the official update; boot area untouched.

    python -B research/burst/z5_burst_release_fw.py firmware-input/Z_5_0150.bin --out output/<new dir>/fw/EG165050.BIN
    (run inside output/phase0-*/enter-environment.ps1)

Entries (all inert unless the card module asks for them; with no module the firmware runs exactly as group 108):
  1. 0x10192F96 burst interval (z5_burst_fw.py, L23): P + 0x18 = 0xB500_0000 | silent_code << 8 | mech_code
     with P + 0x1C = ~(P + 0x18). Camera-tested L43-L51 (mech 7 = 125 ms, silent 5 = 166 ms).
  2. 0x10206E6C low-light immediate go (z5_darkgo_fw.py, L48): `bl 0x10208370` answers 0 when flag bit 0 is set.
  3. 0x1020857A skip CAPSEQ's "back to live view" after each shot (z5_lvskip_fw.py, L50) when flag bit 1 is set.
Flag word for 2 and 3 (release format, replaces the readout builds' log-ring markers 'AESK' / 'LVSK'):
  P + 0x14 = 0xBF5A1C00 | bits   (bit 0: immediate go, bit 1: no live-view return; anything else: off).
  A value of that form is below RAM, so a readout build that takes P + 0x14 as its log ring ignores it.
The card module also takes the live-view-restart holds out of the blocking set (no firmware change; L41).
camera_verified: false (the combination; each entry was camera-tested in its readout build).
"""
import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import z5_burst_fw as bf  # noqa: E402

vh, dd, gz = bf.vh, bf.dd, bf.gz
from z5mod_fw.engine import Edit, Feature  # noqa: E402

FLAG_MAGIC = 0xBF5A1C            # top 24 bits of P + 0x14
GO_SITE, GO_EXPECTED, GO_FLAGWORD, GO_BACK = 0x10206E6C, bytes.fromhex('01f080fa'), 0xC18A7640, 0x10206E70
LV_SITE, LV_EXPECTED, LV_CALL, LV_BACK = 0x1020857A, bytes.fromhex('0020faf7edff'), 0x1020355A, 0x10208580

def flag_check(bit, miss):
    """Branch to label `miss` unless P + 0x14 == 0xBF5A1C00 | bits with `bit` set. Uses r0 and r1 only."""
    return f'''
    ldr     r0, ={gz.ANCHOR:#x}
    ldr     r1, [r0]
    ldr     r0, [r0, #4]
    mvns    r0, r0
    cmp     r1, r0
    bne     {miss}
    ldr     r0, ={gz.RAM_LO:#x}
    cmp     r1, r0
    blo     {miss}
    ldr     r0, ={gz.RAM_HI:#x}
    cmp     r1, r0
    bhs     {miss}
    ldr     r1, [r1, #0x14]
    ldr     r0, ={FLAG_MAGIC:#x}
    cmp.w   r0, r1, lsr #8
    bne     {miss}
    tst     r1, #{bit}
    beq     {miss}
'''


STUB = f'''
    .balign 4
    .global burst_go
    .thumb_func
burst_go:
{flag_check(1, 'burst_go_stock')}
    ldr     r1, ={GO_FLAGWORD:#x}
    ldr     r1, [r1]
    movs    r0, #0
    ldr     pc, ={GO_BACK | 1:#x}
burst_go_stock:
    ldr     r1, ={GO_FLAGWORD:#x}
    ldr     r1, [r1]
    movs    r0, #0
    cmp     r1, #0
    it      ne
    movne   r0, #1
    ldr     pc, ={GO_BACK | 1:#x}
    .ltorg

    .balign 4
    .global burst_lv
    .thumb_func
burst_lv:
{flag_check(2, 'burst_lv_stock')}
    ldr     pc, ={LV_BACK | 1:#x}
burst_lv_stock:
    movs    r0, #0
    ldr     r1, ={LV_CALL | 1:#x}
    blx     r1
    ldr     pc, ={LV_BACK | 1:#x}
    .ltorg
'''


def source():
    return bf.source() + STUB


def feature(stock, at):
    f, syms = bf.feature(stock, at)
    v = vh.VENEERS + 8 * (len(vh.HOOKS) + 2)
    if stock[GO_SITE - vh.BASE:GO_SITE - vh.BASE + 4] != GO_EXPECTED:
        raise SystemExit('next-frame call site differs from the expected bytes')
    if stock[LV_SITE - vh.BASE:LV_SITE - vh.BASE + 6] != LV_EXPECTED:
        raise SystemExit('live-view return site differs from the expected bytes')
    veneer = lambda k, name: Edit(f'{name}_veneer', v + 8 * k - vh.BASE, bytes(8),
                                  bytes.fromhex('dff800f0') + struct.pack('<I', syms[name] | 1))
    edits = f.edits + (
        veneer(0, 'burst_go'), veneer(1, 'burst_lv'),
        Edit('burst_go', GO_SITE - vh.BASE, GO_EXPECTED, vh.branch(GO_SITE, v, False)),
        Edit('burst_lv', LV_SITE - vh.BASE, LV_EXPECTED, vh.branch(LV_SITE, v + 8, False) + bytes.fromhex('00bf')),
    )
    return Feature(name=f.name, description=f.description + '; burst immediate go + live-view return skip (module flag)',
                   camera_verified=False, edits=edits, appends=f.appends), syms


def machine(image, flagword):
    u = dd.machine(image)
    u.mem_map(0xC18F8000, 0x2000); u.mem_map(0xC18A7000, 0x1000)
    if flagword is not None:
        block = 0xC18F9000
        u.mem_write(gz.ANCHOR, struct.pack('<II', block, ~block & 0xFFFFFFFF))
        u.mem_write(block + 0x14, struct.pack('<I', flagword))
    return u


def run_go(image, flagword, flag):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP, UC_ARM_REG_LR
    u = machine(image, flagword)
    u.mem_write(GO_FLAGWORD, struct.pack('<I', flag))
    def hook(mu, pc, size, unused):
        if pc == GO_BACK: mu.emu_stop()
    u.hook_add(UC_HOOK_CODE, hook)
    regs = [UC_ARM_REG_R0 + i for i in range(13)]
    for i, r in enumerate(regs): u.reg_write(r, 0x88880000 + i)
    u.reg_write(UC_ARM_REG_SP, 0x50000800); u.reg_write(UC_ARM_REG_LR, 0x10111111)
    u.emu_start(GO_SITE | 1, 0, count=300)
    return tuple(u.reg_read(r) for r in regs), u.reg_read(UC_ARM_REG_SP)


def run_lv(image, flagword):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R4
    u = machine(image, flagword)
    calls = []
    def hook(mu, pc, size, unused):
        if pc == LV_CALL:
            calls.append(mu.reg_read(UC_ARM_REG_R0))
            mu.reg_write(UC_ARM_REG_R0, 0x5A5A); mu.reg_write(UC_ARM_REG_PC, mu.reg_read(UC_ARM_REG_LR))
        elif pc == LV_BACK:
            mu.emu_stop()
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_ARM_REG_R4, 0xC18A75A0); u.reg_write(UC_ARM_REG_SP, 0x50000800); u.reg_write(UC_ARM_REG_LR, 0x10111111)
    u.emu_start(LV_SITE | 1, 0, count=400)
    return calls, u.reg_read(UC_ARM_REG_R4), u.reg_read(UC_ARM_REG_SP)


FLAG_CASES = (None, 0, 0xBF5A1C00, 0xBF5A1C01, 0xBF5A1C02, 0xBF5A1C03, 0xBF5A1D03, 0x3F5A1C03, 0xC2000100, 0xFFFFFFFF)


def verify_switches(stock, image):
    n = 0
    for flag in (0, 1, 0x80000000):
        want = run_go(stock, None, flag)
        assert want[0][0] == (1 if flag else 0) and want[0][1] == flag, want
        for fw in FLAG_CASES:
            on = fw is not None and (fw >> 8) == FLAG_MAGIC and fw & 1
            got = run_go(image, fw, flag); n += 1
            exp = ((0,) if on else (want[0][0],)) + want[0][1:]
            assert got[0] == exp and got[1] == want[1], ('go', hex(flag), fw, got, want)
    want = run_lv(stock, None)
    assert want[0] == [0], want
    for fw in FLAG_CASES:
        skip = fw is not None and (fw >> 8) == FLAG_MAGIC and fw & 2
        got = run_lv(image, fw); n += 1
        assert got[0] == ([] if skip else [0]) and got[1:] == want[1:], ('lv', fw, got, want)
    return dict(passed=True, calls=n)


def build(package, out):
    vh.source, vh.feature = source, feature
    vh.build(package, out)
    from z5mod_fw import container
    _, mods = container.load(package)
    stock = container.main_module(mods).data
    image = out.read_bytes()
    dd.windows = lambda: [(bf.SITE, bf.SITE + 4), (GO_SITE, GO_SITE + 4), (LV_SITE, LV_SITE + 6)]
    incoming = dd.audit_incoming(stock)
    if incoming:
        raise SystemExit(f'branches land inside a replaced window: {incoming}')
    report = dict(burst_rate=bf.verify(stock, image), switches=dict(unicorn=verify_switches(stock, image)),
                  burst_entries=dict(sites=[hex(bf.SITE), hex(GO_SITE), hex(LV_SITE)], flag_word='P+0x14 = 0xBF5A1C00 | bits',
                                     incoming_branch_audit=dict(found=incoming)))
    rp = out.with_name(out.name + '.json')
    data = json.loads(rp.read_text(encoding='utf-8'))
    data.update(report)
    rp.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print({k: (v.get('unicorn', 'ok') if isinstance(v, dict) and 'unicorn' in v else ('passed' if isinstance(v, dict) and v.get('passed') else 'ok'))
           for k, v in report.items()})


if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) != 3 or args[1] != '--out':
        raise SystemExit(__doc__)
    build(pathlib.Path(args[0]), pathlib.Path(args[2]))
