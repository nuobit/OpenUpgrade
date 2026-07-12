from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    """Drop the stale website_sale.payment_footer template.

    Odoo 17 removed this template from website_sale (payment page redesign).
    The end-of-pass obsolete-record cleanup deletes records one statement at
    a time, so the FK ir_ui_view_inherit_id_fkey blocks it whenever a view
    inheriting payment_footer is scheduled for deletion later in the same
    pass, and the stale 16.0 markup survives into the 17.0 database. Any view
    still inheriting the dead template (website COW copies included) is dead
    data too, so delete the whole inherit closure in ONE statement — FK
    checks run at statement end, making the closure delete atomic. Keyed on
    the stable view key: idempotent, and immune to record-id drift between
    dumps.
    """
    openupgrade.logged_query(
        env.cr,
        """
        WITH RECURSIVE doomed(id) AS (
            SELECT id FROM ir_ui_view
             WHERE key = 'website_sale.payment_footer'
            UNION
            SELECT v.id FROM ir_ui_view v
              JOIN doomed d ON v.inherit_id = d.id
        )
        DELETE FROM ir_model_data
         WHERE model = 'ir.ui.view'
           AND res_id IN (SELECT id FROM doomed)
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        WITH RECURSIVE doomed(id) AS (
            SELECT id FROM ir_ui_view
             WHERE key = 'website_sale.payment_footer'
            UNION
            SELECT v.id FROM ir_ui_view v
              JOIN doomed d ON v.inherit_id = d.id
        )
        DELETE FROM ir_ui_view
         WHERE id IN (SELECT id FROM doomed)
        """,
    )
