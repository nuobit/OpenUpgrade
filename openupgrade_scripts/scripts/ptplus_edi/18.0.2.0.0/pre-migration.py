import logging

from openupgradelib import openupgrade

_logger = logging.getLogger(__name__)

LEGACY_MODULE = "__ptplus_legacy__"


@openupgrade.migrate()
def migrate(env, version):
    """Retire the legacy CIUS-PT edi format xmlid before base's orphan GC.

    At 18.0 the vendor rebuilt ptplus_edi (18.0.2.0.0) on account.move.send
    and stopped declaring the legacy account_edi framework record
    ``account.edi.format`` ``cius_pt_211``. base's _process_end orphan
    cleanup (inside -u all) then tries ``DELETE FROM account_edi_format``,
    which FK-RESTRICT-blocked by historical account_edi_document rows and
    the journal m2m -> a benign but RED-flagged "bad query" on EVERY fresh
    run. A hop-close SQL surrogate cannot cure it: it runs after -u all, so
    the first firing always happens. Same casuistry and same fix as ptplus's
    PT-RF CD tax tags at 16.0 (PR#20): minimal retirement, in the module's
    own namespace, BEFORE the GC.

    If the record is still referenced by ANY FK (row existence from the DB
    catalog -- immune to ON DELETE CASCADE masking), move its xmlid to the
    __ptplus_legacy__ namespace: the row, its links and its provenance
    survive, and the GC no longer owns it. If nothing references it, leave
    it for the GC to delete cleanly.
    """
    env.cr.execute(
        """
        SELECT res_id
        FROM ir_model_data
        WHERE module = 'ptplus_edi'
          AND model = 'account.edi.format'
          AND name = 'cius_pt_211'
        """
    )
    row = env.cr.fetchone()
    if not row:
        return
    rec_id = row[0]

    env.cr.execute(
        """
        SELECT c.conrelid::regclass::text, a.attname
        FROM pg_constraint c
        JOIN pg_attribute a
          ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
        WHERE c.contype = 'f'
          AND c.confrelid = 'account_edi_format'::regclass
        """
    )
    referenced = False
    for table, column in env.cr.fetchall():
        env.cr.execute(
            f"SELECT 1 FROM {table} WHERE {column} = %s LIMIT 1",
            (rec_id,),
        )
        if env.cr.fetchone():
            referenced = True
            break

    if referenced:
        openupgrade.logged_query(
            env.cr,
            """
            UPDATE ir_model_data
            SET module = %s, noupdate = true
            WHERE module = 'ptplus_edi'
              AND model = 'account.edi.format'
              AND name = 'cius_pt_211'
            """,
            (LEGACY_MODULE,),
        )
        _logger.info(
            "cius_pt_211 (account.edi.format id %s) still referenced: "
            "xmlid retired to %s",
            rec_id,
            LEGACY_MODULE,
        )
