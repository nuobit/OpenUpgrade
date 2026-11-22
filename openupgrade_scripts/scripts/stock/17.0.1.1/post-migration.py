# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import logging
from collections import defaultdict

from openupgradelib import openupgrade
from psycopg2 import sql

from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


def _stock_scrap_convert_move_id_m2o_to_o2m(env):
    """
    Convert m2o to o2m in 'stock.scrap'
    """
    openupgrade.m2o_to_x2m(
        env.cr, env["stock.scrap"], "stock_scrap", "move_ids", "move_id"
    )


def _without_tracking(env):
    """
    The states recomputed here are those the pickings already had, told in v17's
    terms: no change to post in their chatter
    """
    return env(context=dict(env.context, mail_notrack=True))


def fix_move_quantity(env):
    """
    Recompute the quantity of the open moves whose lines changed in pre-migration,
    as a line now holds its quantity done, or its reserved quantity when nothing
    was done, and the state that follows from it.
    """
    env = _without_tracking(env)
    env.cr.execute(
        """
        SELECT DISTINCT move_id FROM stock_move_line
        WHERE state IN ('waiting', 'confirmed', 'partially_available', 'assigned')
            AND (reserved_uom_qty <> 0 OR qty_done <> 0)
        """
    )
    moves = env["stock.move"].browse(_id for (_id,) in env.cr.fetchall())
    env.add_to_compute(moves._fields["quantity"], moves)
    moves._recompute_recordset(["quantity"])
    moves._recompute_state()
    env.flush_all()


def remove_move_lines_on_views(env):
    """
    Remove the lines that pre-migration left without quantity on a view, as v17
    removes the lines of a move it unreserves, so that their moves are reserved
    again from other locations. A move whose demand is lower than what its lines
    had done in v16, such as the move v16 makes for a line added to an open
    picking, asks for that quantity, so that validating it doesn't cancel it.
    """
    env = _without_tracking(env)
    env.cr.execute(
        sql.SQL("SELECT id FROM stock_move_line WHERE {}").format(
            sql.Identifier(openupgrade.get_legacy_name("view_line"))
        )
    )
    lines = env["stock.move.line"].browse(_id for (_id,) in env.cr.fetchall())
    if not lines:
        return
    moves = lines.move_id
    env.cr.execute(
        """
        SELECT move_id, product_uom_id, qty_done FROM stock_move_line
        WHERE move_id IN %s AND qty_done <> 0
        """,
        (tuple(moves.ids),),
    )
    done = defaultdict(float)
    for move_id, uom_id, qty_done in env.cr.fetchall():
        move = moves.browse(move_id)
        uom = env["uom.uom"].browse(uom_id)
        done[move] += uom._compute_quantity(qty_done, move.product_uom)
    for move, quantity in done.items():
        demand = move.product_uom_qty
        rounding = move.product_uom.rounding
        if float_compare(quantity, demand, precision_rounding=rounding) > 0:
            move.with_context(do_not_unreserve=True).product_uom_qty = quantity
    _logger.warning(
        "%s move lines not done, taken from a view location, removed to be reserved "
        "again; their pickings: %s",
        len(lines),
        ", ".join(sorted(set(lines.picking_id.mapped("name")))),
    )
    lines.with_context(preserve_state=True).unlink()
    moves.filtered(lambda move: move.state != "draft")._recompute_state()
    env.flush_all()


def link_returned_pickings(env):
    """
    Link pickings containing returned moves to the pickings containing the moves
    being returned
    """
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE stock_picking
        SET
        return_id = returned_move.picking_id
        FROM
        stock_move
        JOIN stock_move returned_move
        ON stock_move.origin_returned_move_id = returned_move.id
        WHERE
        stock_move.picking_id = stock_picking.id
        """,
    )


def set_picking_type_return_location(env):
    """
    Set default_location_return_id on picking types from the destination location
    of the warehouse's return picking type
    """
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE stock_picking_type
        SET
        default_location_return_id = COALESCE(
            picking_return_type.default_location_dest_id,
            warehouse_return_type.default_location_dest_id
        )
        FROM
        stock_picking_type self
        JOIN stock_warehouse
        ON self.warehouse_id=stock_warehouse.id
        LEFT JOIN stock_picking_type picking_return_type
        ON self.return_picking_type_id=picking_return_type.id
        LEFT JOIN stock_picking_type warehouse_return_type
        ON stock_warehouse.return_type_id=warehouse_return_type.id
        WHERE
        stock_picking_type.id=self.id
        """,
    )


@openupgrade.migrate()
def migrate(env, version):
    openupgrade.load_data(env, "stock", "17.0.1.1/noupdate_changes.xml")
    openupgrade.delete_record_translations(
        env.cr, "stock", ["mail_template_data_delivery_confirmation"]
    )
    _stock_scrap_convert_move_id_m2o_to_o2m(env)
    fix_move_quantity(env)
    remove_move_lines_on_views(env)
    link_returned_pickings(env)
    set_picking_type_return_location(env)
