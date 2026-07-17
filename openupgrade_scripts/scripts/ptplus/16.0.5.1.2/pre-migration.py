import logging

from openupgradelib import openupgrade

_logger = logging.getLogger(__name__)

# Retired namespace for xmlids of records ptplus stopped shipping but the
# instance's history still references. No module by this name ever exists, so
# Odoo's orphan-xmlid collector (_process_end only processes REAL modules being
# loaded) never touches it — while the full original identity stays recorded in
# ir_model_data (visible as External ID in dev mode, queryable forever). Chosen
# over deleting the pointer because account.account.tag has no note/comment
# field to carry provenance: the renamed pointer IS the provenance.
LEGACY_MODULE = "__ptplus_legacy__"


@openupgrade.migrate()
def migrate(env, version):
    # WHY (archaeology, verified against ptplus 15/16/17/18/19 data + the
    # vendor's own migration scripts):
    #
    # Through 15.0, ptplus classifies PT withholding (retenção na fonte) on move
    # lines with per-payment-guide-code TAGS: "PT-RF CD <code>" (xmlid
    # ptplus.tax_tag_rf_cd_*, 26 tags in data/account_tax_data.xml; the codes
    # are the official AT guia-de-pagamento codes — 102 trabalho independente,
    # 104 prediais, 2xx IRC, ... — all still officially current).
    #
    # At 16.0 the vendor rebuilds the whole RF system: dedicated withholding
    # TAXES appear (account_tax_template_rfirs_* / rfirc_*), and from 17.0 the
    # template CSV carries the guide code as FIELDS on the tax
    # (l10n_pt_wh_tax_type / l10n_pt_wh_code / l10n_pt_wh_income_type). The
    # vendor's own scripts (migrations/16.0.5.1.0, .5.1.2) migrate the OTHER tag
    # families by name filter (replace_tags()/delete_tags() on "RF DM/M10/M30/
    # IS…", clearing the m2m before the tag goes), but no filter matches
    # "PT-RF CD" and the family is re-declared under no other xmlid: it is
    # dropped with NO data migration. At settle, the orphan-xmlid collector
    # tries to DELETE every tax_tag_rf_cd_* the module no longer declares; the
    # FK-held ones fail ("bad query: DELETE FROM account_account_tag …"), the
    # 15->16 hop goes RED and the 18 settle hits a FATAL through the same path.
    #
    # FIX — selective retirement (the migration script the vendor forgot):
    #   * CD tags REFERENCED anywhere: move their ir_model_data pointer to the
    #     retired namespace above. Record, links and provenance all survive;
    #     the collector's condemned DELETE is never attempted.
    #   * CD tags referenced NOWHERE: left alone — the collector deletes them
    #     cleanly (no error, nothing lost, no zombie rows). On an install with
    #     no old-system history the family disappears entirely.
    #
    # "Referenced" is decided by ROW EXISTENCE in EVERY table holding a FK to
    # account_account_tag, discovered dynamically from the catalog — NOT by
    # whether the collector's DELETE would fail. The difference matters: some
    # m2m rel tables carry ON DELETE CASCADE, so a tag linked only through one
    # of those would be deleted "successfully" while silently stripping the
    # classification off history. Existence-based selection is immune to that.
    #
    # A remap onto the new structure is deliberately NOT attempted: the
    # replacement is a field on per-rate taxes (one code -> many taxes), there
    # is no tag-shaped target, and nothing at 16+ reads the CD tags (verified:
    # zero references in data/migrations through 19.0; no account.tax.report
    # line ever pointed at them). Idempotent: on a re-run the referenced ones
    # already sit in the legacy namespace and the unused ones are gone.
    env.cr.execute(
        """
        SELECT res_id
        FROM ir_model_data
        WHERE model = 'account.account.tag'
          AND module = 'ptplus'
          AND name ~ '^tax_tag_rf_cd_'
        """
    )
    cd_ids = [r[0] for r in env.cr.fetchall()]
    if not cd_ids:
        _logger.info("ptplus PT-RF CD tags: none pending — nothing to do")
        return

    # every (table, column) with a FK into account_account_tag, straight from
    # the catalog so any install's extra consumers are covered too.
    # conrelid::regclass::text comes out correctly quoted when needed.
    env.cr.execute(
        """
        SELECT c.conrelid::regclass::text, a.attname
        FROM pg_constraint c
        JOIN pg_attribute a
          ON a.attrelid = c.conrelid
         AND a.attnum = ANY (c.conkey)
        WHERE c.contype = 'f'
          AND c.confrelid = 'account_account_tag'::regclass
        """
    )
    used = set()
    for table, column in env.cr.fetchall():
        env.cr.execute(
            f"SELECT DISTINCT {column} FROM {table} WHERE {column} = ANY (%s)",
            (cd_ids,),
        )
        used.update(r[0] for r in env.cr.fetchall())

    unused = sorted(set(cd_ids) - used)
    _logger.info(
        "ptplus PT-RF CD tags: %s referenced -> xmlid retired to %s (record + "
        "links + provenance kept); %s unreferenced -> left for the orphan "
        "collector to remove cleanly. kept=%s dropped=%s",
        len(used),
        LEGACY_MODULE,
        len(unused),
        sorted(used),
        unused,
    )
    if used:
        openupgrade.logged_query(
            env.cr,
            """
            UPDATE ir_model_data
               SET module = %s, noupdate = true
             WHERE model = 'account.account.tag'
               AND module = 'ptplus'
               AND name ~ '^tax_tag_rf_cd_'
               AND res_id IN %s
            """,
            (LEGACY_MODULE, tuple(used)),
        )
