/* Burst speed-up: install-time code (runs once from the original module image). Image code is in
 * burst_speed.inc, which must stay before Z5_IMAGE_END. */

/* The switch page: two rows shaped like the battery page's. Returns 1 or a refusal >= 110. */
static u32 install_burst_page(cm_t *c, u32 *title, u32 first_map)
{
    const u32 *th = (const u32 *)TEMPLATE_HDR;
    if (((const u32 *)LAYOUTS_2ROW)[0] != 2u) return 110u;
    u32 *rows = (u32 *)z5_alloc(2u * ROW_SIZE, 0);
    u32 *disp = (u32 *)z5_alloc(2u * 4u, 0);
    u32 *hdr = (u32 *)z5_alloc(7u * 4u, 0);
    if (!rows || !disp || !hdr) return 111u;
    u32 kind = c->hans ? F_UTF16 : F_ASCII;
    copy_words(rows, (const u32 *)GRID_ROWS, ROW_WORDS);
    copy_words(rows + ROW_WORDS, rows, ROW_WORDS);
    rows[0] = BURST_SLOT_MECH;  rows[4] = PLAIN_ROW | kind; rows[6] = BURST_ID_MECH;
    rows[ROW_WORDS] = BURST_SLOT_SIL;  rows[ROW_WORDS + 4u] = PLAIN_ROW | kind; rows[ROW_WORDS + 6u] = BURST_ID_SIL;
    disp[0] = build_map(first_map, img_addr(c, burst_mech_ok), STAY);
    disp[1] = build_map(first_map, img_addr(c, burst_sil_ok), STAY);
    if (!disp[0] || !disp[1]) return 112u;
    hdr[0] = th[0]; hdr[1] = LAYOUTS_2ROW; hdr[2] = (u32)title;
    hdr[3] = (u32)rows; hdr[4] = (u32)disp; hdr[5] = (2u << 16) | 2u; hdr[6] = th[6];
    c->burst_rows = (u32)rows;
    c->burst_hdr = (u32)hdr;
    return 1u;
}

/* Module code, once per power-up after the menu: words, then the task. */
static void burst_start(cm_t *c)
{
    burst_words(c, 0u);
    z5_task *t = (z5_task *)z5_alloc(sizeof(z5_task), 0);
    if (!t) { c->burst_task_rc = 0xE1000000u; return; }
    char name[8] = {'B', 'U', 'R', 'S', 'T', 'S', 'P', 0};
    t->start_rc = -1;
    c->burst_task_rc = (u32)z5_task_create_raw(t, name, 0x30u, (void *)img_addr(c, burst_task));
    if (!c->burst_task_rc && t->start_rc) c->burst_task_rc = 0xE2000000u | ((u32)t->start_rc & 0xFFFFFFu);
}
