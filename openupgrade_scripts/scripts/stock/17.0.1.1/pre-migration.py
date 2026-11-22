# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from openupgradelib import openupgrade

_field_renames = [
    ("stock.move", "stock_move", "quantity_done", "quantity"),
]

_column_copies = {
    "stock_move_line": [
        ("qty_done", "quantity", None),
    ]
}


def fix_move_line_quantity(env):
    """
    v17 combines what used to be reserved_uom_qty and qty_done.
    The new quantity column is a copy of qty_done, and we keep it
    on the lines that had a quantity done, as that is what
    validating their picking would move in v16. The open lines
    that were only reserved take their reserved quantity.

    In post-migration, we'll recompute the quantity field and the
    state of moves affected.
    """
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE stock_move_line
        SET quantity = reserved_uom_qty
        WHERE
        state IN ('assigned', 'partially_available')
        AND reserved_uom_qty <> 0
        AND COALESCE(qty_done, 0) = 0
        """,
    )


def reset_move_line_quantity_on_views(env):
    """
    v16 allowed a quantity done on a line not done whose source is a view, as it
    wasn't a reservation. In v17 that quantity is a reservation, held by a quant of
    the source, and quants aren't allowed on views: writing, unlinking or validating
    such a line would raise, and from v18 on so would stock.quant~_clean_reservations,
    run by the inventory views and by the procurement scheduler. Unless a quant there
    matches them (product, lot, package and owner), leave the lines of storable
    products without quantity and mark them for post-migration, which removes them,
    so that their moves are reserved again from other locations.
    """
    legacy = openupgrade.get_legacy_name("view_line")
    openupgrade.logged_query(
        env.cr, f"ALTER TABLE stock_move_line ADD COLUMN {legacy} BOOLEAN"
    )
    openupgrade.logged_query(
        env.cr,
        f"""
        UPDATE stock_move_line sml
        SET quantity = 0, {legacy} = TRUE
        FROM stock_location sl, product_product pp, product_template pt
        WHERE sl.id = sml.location_id
            AND sl.usage = 'view'
            AND pp.id = sml.product_id
            AND pt.id = pp.product_tmpl_id
            AND pt.type = 'product'
            AND sml.state IN (
                'draft', 'waiting', 'confirmed', 'partially_available', 'assigned'
            )
            AND NOT EXISTS (
                SELECT 1 FROM stock_quant sq
                WHERE sq.product_id = sml.product_id
                    AND sq.location_id = sml.location_id
                    AND sq.lot_id IS NOT DISTINCT FROM sml.lot_id
                    AND sq.package_id IS NOT DISTINCT FROM sml.package_id
                    AND sq.owner_id IS NOT DISTINCT FROM sml.owner_id
            )
        """,
    )


def _prefill_sml_quantity_product_uom(env):
    openupgrade.add_columns(
        env,
        [("stock.move.line", "quantity_product_uom", "float", None, "stock_move_line")],
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE stock_move_line sml
        SET quantity_product_uom =
        CASE
            WHEN sml.product_uom_id != pt.uom_id
                AND uom_pt.category_id = uom_sml.category_id
            THEN ROUND(
                sml.quantity * uom_pt.factor / uom_sml.factor,
                CASE
                    WHEN uom_pt.rounding = 1.0 THEN 0
                ELSE scale(uom_pt.rounding)
                END
            )
        ELSE sml.quantity
        END
        FROM product_product pp,
            uom_uom uom_sml,
            product_template pt,
            uom_uom uom_pt
        WHERE pp.id = sml.product_id
            AND uom_sml.id = sml.product_uom_id
            AND pt.id = pp.product_tmpl_id
            AND uom_pt.id = pt.uom_id
        """,
    )


def prefill_picked(env):
    """
    Pre-fill picked for stock moves and move lines to reduce ORM
    recomputation during migration. On the moves not done nor cancelled, it
    marks the lines that had a quantity done in v16. A cancelled move and its
    lines aren't picked, as v17 unpicks a move it cancels.
    """
    openupgrade.add_columns(
        env,
        [
            ("stock.move", "picked", "boolean", True, "stock_move"),
            ("stock.move.line", "picked", "boolean", True, "stock_move_line"),
        ],
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE stock_move_line sml
        SET picked = FALSE
        FROM stock_move sm
        WHERE sml.move_id = sm.id
          AND sm.state != 'done'
          AND (
              sm.state = 'cancel'
              OR COALESCE(sml.qty_done, 0) = 0
              OR COALESCE(sml.quantity, 0) = 0
          )
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE stock_move sm
        SET picked = False
        FROM stock_move sm2
        LEFT JOIN stock_move_line sml
            ON sml.move_id = sm2.id
        WHERE sm.state != 'done'
            AND sml.id IS NULL
            AND sm.id = sm2.id
        """,
    )
    # Need to set sms picked to False when none of the related smls is picked
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE stock_move sm
        SET picked=False
        FROM stock_move_line sml
        WHERE sml.move_id = sm.id
          AND NOT sml.picked
          AND NOT EXISTS (
              SELECT 1 FROM stock_move_line sml2
              WHERE sml2.move_id = sm.id AND sml2.picked
          )
        """,
    )


@openupgrade.migrate()
def migrate(env, version):
    openupgrade.rename_fields(env, _field_renames)
    openupgrade.copy_columns(env.cr, _column_copies)
    fix_move_line_quantity(env)
    reset_move_line_quantity_on_views(env)
    _prefill_sml_quantity_product_uom(env)
    prefill_picked(env)
