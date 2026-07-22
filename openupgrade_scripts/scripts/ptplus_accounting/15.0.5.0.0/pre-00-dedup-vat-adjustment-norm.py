from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    # Some 14.0 databases already carry l10n_pt_vat_adjustment_norm_id (the
    # 15.0 target name) while the old vat_adjustment_norm_id duplicate also
    # exists on account_move. The module's own pre-migration then calls
    # openupgrade.rename_fields() old -> new and fails because the target
    # exists. Drop the old duplicate first, but only when it is provably
    # empty. Named pre-00-* so it sorts — and therefore runs — before the
    # module's own pre-migration.py (same-version stage scripts execute in
    # basename order).
    cr = env.cr
    if not (
        openupgrade.column_exists(cr, "account_move", "vat_adjustment_norm_id")
        and openupgrade.column_exists(
            cr, "account_move", "l10n_pt_vat_adjustment_norm_id"
        )
    ):
        return
    cr.execute(
        "SELECT count(*) FROM account_move WHERE vat_adjustment_norm_id IS NOT NULL"
    )
    old_non_null = cr.fetchone()[0]
    if old_non_null:
        raise RuntimeError(
            "Refusing to drop account_move.vat_adjustment_norm_id: "
            "%s non-null rows" % old_non_null
        )
    openupgrade.logged_query(
        cr,
        """
        DELETE FROM ir_model_data
         WHERE model = 'ir.model.fields'
           AND res_id IN (
                SELECT id FROM ir_model_fields
                 WHERE model = 'account.move'
                   AND name = 'vat_adjustment_norm_id'
           )
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        DELETE FROM ir_model_fields
         WHERE model = 'account.move'
           AND name = 'vat_adjustment_norm_id'
        """,
    )
    openupgrade.logged_query(
        cr, "ALTER TABLE account_move DROP COLUMN vat_adjustment_norm_id"
    )
