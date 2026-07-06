from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    # The 15.0.5.0.0 upgrade adds the stored computed field
    # stock_picking.l10n_pt_is_national. Creating the column here makes the
    # ORM skip its whole-table "Storing computed values" pass (millions of
    # rows), which cannot fit in memory during `-u all`. The field is
    # recomputed in controlled batches at the target version.
    openupgrade.logged_query(
        env.cr,
        """
        ALTER TABLE stock_picking
        ADD COLUMN IF NOT EXISTS l10n_pt_is_national boolean
        """,
    )
