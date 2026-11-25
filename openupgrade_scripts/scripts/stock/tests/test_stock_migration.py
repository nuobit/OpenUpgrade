import importlib.util
import os
from collections import defaultdict

from odoo.tests import TransactionCase

from odoo.addons.openupgrade_framework import openupgrade_test

# the post-migration's own functions, called again by a test
_spec = importlib.util.spec_from_file_location(
    "stock_post_migration",
    os.path.join(os.path.dirname(__file__), os.pardir, "17.0.1.1", "post-migration.py"),
)
post_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(post_migration)


@openupgrade_test
class TestStockMigration(TransactionCase):
    def _delivery(self, origin):
        return self.env["stock.picking"].search([("origin", "=", origin)])

    def test_move_quantity(self):
        """
        Test that assigned moves take their reserved quantity
        """
        picking = self.env.ref("stock.outgoing_shipment_main_warehouse4")
        self.assertEqual(picking.move_ids.quantity, 16)
        picking = self.env.ref("stock.incomming_shipment2")
        self.assertEqual(picking.move_ids.quantity, 125)

    def test_open_line_quantity(self):
        """
        Test that an open line keeps its quantity done, never the sum with the
        reserved one, and takes the reserved one when nothing was done, wherever it
        is taken from
        """
        for origin, quantity in (
            ("ou17-reserved", 3),
            ("ou17-done-equal", 4),
            ("ou17-done-more", 8),
            ("ou17-done-less", 6),
            ("ou17-done-unreserved", 2),
            ("ou17-other-unit", 1),
            ("ou17-partially-available", 100),
            ("ou17-receipt", 5),
            ("ou17-empty-line", 0),
        ):
            self.assertEqual(
                self._delivery(origin).move_line_ids.quantity, quantity, origin
            )
        lines = self._delivery("ou17-several-lines").move_line_ids
        self.assertEqual(sorted(lines.mapped("quantity")), [1, 3])

    def test_open_move_quantity_and_state(self):
        """
        Test that the moves of those lines get their quantity and their state
        from them
        """
        for origin, quantity, state in (
            ("ou17-reserved", 3, "assigned"),
            ("ou17-done-equal", 4, "assigned"),
            ("ou17-done-more", 8, "assigned"),
            ("ou17-done-less", 6, "partially_available"),
            ("ou17-done-unreserved", 2, "assigned"),
            ("ou17-other-unit", 1, "assigned"),
            ("ou17-partially-available", 100, "partially_available"),
            ("ou17-several-lines", 4, "assigned"),
            ("ou17-empty-line", 0, "confirmed"),
        ):
            move = self._delivery(origin).move_ids
            self.assertEqual(move.quantity, quantity, origin)
            self.assertEqual(move.state, state, origin)
        move = self._delivery("ou17-receipt").move_ids.filtered(
            lambda move: move.product_id.default_code == "OU17-KILOGRAMS"
        )
        self.assertEqual(move.quantity, 5)
        self.assertEqual(move.state, "assigned")

    def test_no_state_tracking(self):
        """
        Test that recomputing the state of a picking in the migration doesn't
        post a tracking message
        """
        delivery = self._delivery("ou17-done-unreserved")
        self.assertEqual(delivery.state, "assigned")
        self.assertFalse(
            delivery.message_ids.tracking_value_ids.filtered(
                lambda tracking: tracking.field_id.name == "state"
                and tracking.new_value_char == "Ready"
            )
        )

    def test_picked(self):
        """
        Test that on the moves not done nor cancelled a line is picked when it had a
        quantity done, a move when one of its lines is, and that a cancelled move
        and its lines aren't
        """
        for origin, picked in (
            ("ou17-reserved", False),
            ("ou17-done-equal", True),
            ("ou17-done-more", True),
            ("ou17-done-less", True),
            ("ou17-done-unreserved", True),
        ):
            delivery = self._delivery(origin)
            self.assertEqual(delivery.move_line_ids.picked, picked, origin)
            self.assertEqual(delivery.move_ids.picked, picked, origin)
        delivery = self._delivery("ou17-several-lines")
        lines = delivery.move_line_ids.sorted("quantity")
        self.assertEqual(lines.mapped("picked"), [True, False])
        self.assertTrue(delivery.move_ids.picked)
        for origin in ("ou17-cancelled-done", "ou17-cancelled-lineless"):
            cancelled = self._delivery(origin).move_ids.filtered(
                lambda move: move.state == "cancel"
            )
            self.assertFalse(cancelled.picked, origin)
            self.assertFalse(any(cancelled.move_line_ids.mapped("picked")), origin)

    def test_done_moves_picked(self):
        """
        Test that a done move and its lines stay picked and keep their quantity, the
        move of an inventory applied with no difference and a done move without lines
        included
        """
        move = self.env["stock.move"].search(
            [
                ("product_id.default_code", "=", "OU17-INVENTORY-EQUAL"),
                ("is_inventory", "=", True),
            ]
        )
        self.assertEqual(move.state, "done")
        self.assertEqual(move.move_line_ids.quantity, 0)
        self.assertTrue(move.picked)
        self.assertTrue(move.move_line_ids.picked)
        move = self._delivery("ou17-done-lineless").move_ids
        self.assertEqual(move.state, "done")
        self.assertEqual(move.quantity, 1)
        self.assertFalse(move.move_line_ids)
        self.assertTrue(move.picked)

    def test_validate_with_cancelled_moves(self):
        """
        Test that validating a picking where nothing was picked picks its open
        moves, whatever was done on its cancelled ones
        """
        for origin in ("ou17-cancelled-done", "ou17-cancelled-lineless"):
            delivery = self._delivery(origin)
            delivery.button_validate()
            self.assertEqual(delivery.state, "done", origin)

    def test_no_line_on_views(self):
        """
        Test that no line not done of a storable product is taken from a view
        location, unless a quant there matches it, and that the inventory runs
        """
        quant_keys = {
            (
                quant.product_id,
                quant.location_id,
                quant.lot_id,
                quant.package_id,
                quant.owner_id,
            )
            for quant in self.env["stock.quant"].search(
                [("location_id.usage", "=", "view")]
            )
        }
        for line in self.env["stock.move.line"].search(
            [
                ("location_id.usage", "=", "view"),
                ("state", "not in", ("done", "cancel")),
                ("product_id.type", "=", "product"),
            ]
        ):
            self.assertIn(
                (
                    line.product_id,
                    line.location_id,
                    line.lot_id,
                    line.package_id,
                    line.owner_id,
                ),
                quant_keys,
                line.picking_id.origin,
            )
        self.assertFalse(self._delivery("ou17-view-lot").move_line_ids)
        self.env["stock.quant"]._quant_tasks()

    def test_view_lines_reserved_again(self):
        """
        Test that the moves of the lines removed from a view keep their demand, at
        least what was done on them, one above it by less than its unit's rounding
        included, a draft one stays draft, a waiting one waiting, one reserved in
        part keeps its reservation, the migration reserves none of them, a receipt's
        included, and they are reserved and done from stock
        """
        stock = self.env.ref("stock.stock_location_stock")
        delivery = self._delivery("ou17-view")
        self.assertFalse(delivery.move_line_ids)
        self.assertEqual(delivery.move_ids.state, "confirmed")
        delivery = self._delivery("ou17-view-whole-demand")
        self.assertFalse(delivery.move_line_ids)
        self.assertEqual(delivery.move_ids.product_uom_qty, 2.3)
        delivery = self._delivery("ou17-view-draft")
        self.assertEqual(delivery.move_line_ids.location_id, stock)
        self.assertEqual(delivery.move_ids.quantity, 1)
        self.assertEqual(delivery.move_ids.state, "draft")
        delivery = self._delivery("ou17-view-partially")
        self.assertEqual(delivery.move_line_ids.location_id, stock)
        self.assertEqual(delivery.move_ids.quantity, 100)
        self.assertEqual(delivery.move_ids.state, "partially_available")
        delivery = self._delivery("ou17-small-waiting")
        self.assertEqual(delivery.move_line_ids.location_id, stock)
        self.assertEqual(delivery.move_ids.state, "waiting")
        added = self._delivery("ou17-view-added").move_ids.filtered(
            lambda move: move.product_id.default_code == "OU17-VIEW-ADDED"
        )
        self.assertFalse(added.move_line_ids)
        self.assertEqual(added.product_uom_qty, 1)
        receipt = self._delivery("ou17-receipt")
        receipt_added = receipt.move_ids.filtered(
            lambda move: move.product_id.default_code == "OU17-RECEIPT-VIEW-ADDED"
        )
        self.assertFalse(receipt_added.move_line_ids)
        self.assertEqual(receipt_added.product_uom_qty, 1)
        self.assertEqual(receipt_added.state, "confirmed")
        for origin in (
            "ou17-view",
            "ou17-view-draft",
            "ou17-view-added",
            "ou17-view-partially",
            "ou17-view-whole-demand",
        ):
            delivery = self._delivery(origin)
            delivery.action_confirm()
            delivery.action_assign()
            delivery.with_context(skip_backorder=True).button_validate()
            self.assertEqual(delivery.state, "done", origin)
            self.assertEqual(
                delivery.move_line_ids.mapped("location_id"), stock, origin
            )
        self.assertEqual(added.quantity, 1)
        receipt.action_assign()
        receipt.button_validate()
        self.assertEqual(receipt.state, "done")
        self.assertEqual(receipt_added.quantity, 1)

    def test_view_consumable_line_kept(self):
        """
        Test that a consumable's line taken from a view keeps its quantity there, as
        it reserves nothing on a quant, and its picking validates
        """
        delivery = self._delivery("ou17-view-consumable")
        self.assertEqual(delivery.move_line_ids.location_id.usage, "view")
        self.assertEqual(delivery.move_line_ids.quantity, 1)
        delivery.button_validate()
        self.assertEqual(delivery.state, "done")

    def test_remove_view_lines_again(self):
        """
        Test that the removal of the lines taken from a view does nothing on a
        database without such lines, and logs at WARNING the lines it removes with
        their pickings
        """
        with self.assertNoLogs(level="WARNING"):
            post_migration.remove_move_lines_on_views(self.env)
        delivery = self._delivery("ou17-reserved")
        legacy = post_migration.openupgrade.get_legacy_name("view_line")
        self.env.cr.execute(
            f"""
            UPDATE stock_move_line
            SET location_id = %s, quantity = 0, quantity_product_uom = 0,
                {legacy} = TRUE
            WHERE id IN %s
            """,
            (
                self.env.ref("stock.warehouse0").view_location_id.id,
                tuple(delivery.move_line_ids.ids),
            ),
        )
        self.env.invalidate_all()
        with self.assertLogs(level="WARNING") as logs:
            post_migration.remove_move_lines_on_views(self.env)
        self.assertIn(delivery.name, logs.output[0])
        self.assertFalse(delivery.move_line_ids)

    def test_quant_reservations(self):
        """
        Test that the quants of each product, location, lot, package and owner
        reserve the quantity of the open lines of storable products taken from
        them, a fraction of a unit counted in whole units included, and nothing
        where reservation is bypassed
        """

        def key(record):
            return (
                record.product_id,
                record.location_id,
                record.lot_id,
                record.package_id,
                record.owner_id,
            )

        reserved = defaultdict(float)
        for quant in self.env["stock.quant"].search([]):
            reserved[key(quant)] += quant.reserved_quantity
        expected = defaultdict(float)
        for line in self.env["stock.move.line"].search(
            [
                (
                    "state",
                    "in",
                    ("assigned", "partially_available", "waiting", "confirmed"),
                ),
                ("product_id.type", "=", "product"),
            ]
        ):
            if not line.location_id.should_bypass_reservation():
                expected[key(line)] += line.quantity_product_uom
        for group in set(reserved) | set(expected):
            self.assertAlmostEqual(
                reserved[group], expected[group], msg=group[0].display_name
            )

    def test_small_quantities_reserved(self):
        """
        Test that a line whose quantity rounds to nothing in its move's unit leaves
        the move waiting or confirmed, and still reserves its quantity on the quant
        """
        stock = self.env.ref("stock.stock_location_stock")
        for origin, state in (
            ("ou17-small-waiting", "waiting"),
            ("ou17-small-confirmed", "confirmed"),
        ):
            delivery = self._delivery(origin)
            self.assertEqual(delivery.move_ids.state, state, origin)
            self.assertEqual(delivery.move_line_ids.quantity, 1, origin)
        quant = self.env["stock.quant"].search(
            [
                ("product_id.default_code", "=", "OU17-KILOGRAMS"),
                ("location_id", "=", stock.id),
            ]
        )
        self.assertEqual(quant.reserved_quantity, 2)

    def test_validate_releases_reservations(self):
        """
        Test that validating a migrated picking leaves its quant with no reservation,
        neither left behind nor below zero
        """
        for origin in (
            "ou17-done-more",
            "ou17-done-less",
            "ou17-done-unreserved",
            "ou17-whole-stale",
        ):
            delivery = self._delivery(origin)
            delivery.with_context(
                skip_backorder=True, picking_ids_not_to_backorder=delivery.ids
            ).button_validate()
            self.assertEqual(delivery.state, "done", origin)
            quants = self.env["stock.quant"].search(
                [("product_id", "=", delivery.move_ids.product_id.id)]
            )
            self.assertEqual(sum(quants.mapped("reserved_quantity")), 0, origin)

    def test_view_quant_kept(self):
        """
        Test that a quant left with nothing on a view holds the reservation of the
        line taken from it, so that the inventory keeps it and the line validates
        """
        delivery = self._delivery("ou17-view-quant")
        self.assertEqual(delivery.move_line_ids.quantity, 1)
        self.env["stock.quant"]._quant_tasks()
        delivery.button_validate()
        self.assertEqual(delivery.state, "done")

    def test_returned_picking(self):
        """
        Test that we correctly link returned pickings to their origin picking
        """
        returned_picking = self.env.ref("stock.outgoing_shipment_main_warehouse1")
        self.assertTrue(returned_picking.return_ids)

    def test_return_location(self):
        """
        Test that we set the default return location for pickings from the warehouse's
        return picking type from v16
        """
        picking_type = self.env.ref("stock.picking_type_in")
        stock_location = self.env.ref("stock.stock_location_stock")
        self.assertEqual(picking_type.default_location_return_id, stock_location)
