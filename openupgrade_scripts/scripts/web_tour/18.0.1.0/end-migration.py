from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version=None):
    """
    Set consumed tours from legacy table after migration and remove
    obsolete security rules
    """
    openupgrade.logged_query(
        env.cr,
        f"""
        INSERT INTO res_users_web_tour_tour_rel
        (res_users_id, web_tour_tour_id)
        SELECT legacy_table.user_id, web_tour_tour.id
        FROM
        {openupgrade.get_legacy_name('web_tour_tour')} legacy_table,
        web_tour_tour
        WHERE web_tour_tour.name=legacy_table.name
        ON CONFLICT DO NOTHING
        """,
    )
    # web_tour.tour lost its user_id field in 18.0: any pre-existing
    # per-user record rule (e.g. "own tours", domain [('user_id','=',
    # user.id)]) now references a nonexistent field. Tours are loaded at
    # every web login, so the stale rule blocks ALL logins right after
    # the migration. Drop such rules here, where the module's own data
    # is already reloaded.
    openupgrade.logged_query(
        env.cr,
        """
        DELETE FROM ir_rule
        WHERE model_id = (
            SELECT id FROM ir_model WHERE model = 'web_tour.tour'
        )
        AND domain_force LIKE '%user_id%'
        """,
    )
