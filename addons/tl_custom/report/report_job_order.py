# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import OrderedDict, defaultdict
from odoo import api, fields, models


class ReportJobOrder(models.AbstractModel):
    _name = 'report.tl_custom.report_job_order'
    _description = 'Report Job Order'

    # ---- helpers -------------------------------------------------------------

    def _merge_balances(self, balances):
        """Gabung balance yang sama (product/size) dan jumlahkan qty."""
        merged = {}
        for b in balances or []:
            key = (b.get('product_id'),
                   float(b.get('length_balance') or 0),
                   float(b.get('width_balance') or 0),
                   float(b.get('kg_balance') or 0))
            if key not in merged:
                merged[key] = {
                    'product_id': b.get('product_id'),
                    'length_balance': b.get('length_balance') or 0.0,
                    'width_balance': b.get('width_balance') or 0.0,
                    'kg_balance': b.get('kg_balance') or 0.0,
                    'quantity': float(b.get('quantity') or 0.0),
                }
            else:
                merged[key]['quantity'] += float(b.get('quantity') or 0.0)
        return list(merged.values())

    def _merge_cuts(self, cuts):
        """Gabung baris cut yang identik (dimension + lot + location)."""
        merged = OrderedDict()
        for c in cuts or []:
            key = (c.get('dimension'), c.get('lot_name'), c.get('location_id'))
            if key not in merged:
                merged[key] = c.copy()
                merged[key]['used_qty'] = float(c.get('used_qty') or 0.0)
                merged[key]['balances'] = self._merge_balances(c.get('balances') or [])
            else:
                merged[key]['used_qty'] += float(c.get('used_qty') or 0.0)
                # keep the latest stock balance figures seen
                if 'cut_balance_stock' in c:
                    merged[key]['cut_balance_stock'] = c['cut_balance_stock']
                if 'cut_balance_stock_bc' in c:
                    merged[key]['cut_balance_stock_bc'] = c['cut_balance_stock_bc']
                merged[key]['balances'] = self._merge_balances(
                    (merged[key].get('balances') or []) + (c.get('balances') or [])
                )
        return list(merged.values())

    def _group_items(self, arr):
        """
        Group by (dimension/parent item) so header muncul sekali per item,
        lalu list 'cuts' di bawahnya.
        """
        grouped = OrderedDict()
        for line in arr:
            key = (line['dimension'], line['description'], line['uom'])
            if key not in grouped:
                grouped[key] = {
                    'dimension': key[0],
                    'description': key[1],
                    'uom': key[2],
                    'total_done': 0.0,
                    'cuts': [],
                    'electrode_number': line.get('electrode_number'),
                }
            grouped[key]['total_done'] += float(line.get('done_quantity') or 0.0)
            grouped[key]['cuts'].extend(line.get('cuts') or [])

        # rapikan cuts (merge duplikat)
        for item in grouped.values():
            item['cuts'] = self._merge_cuts(item['cuts'])
        return list(grouped.values())

    # ---- main ---------------------------------------------------------------

    @api.model
    def _get_report_values(self, docids, data=None):
        """
        NOTE:
        - Bagian di bawah masih mengambil data dari struktur yang sudah kamu punya.
        - Setelah arr terisi, kita group menjadi items → dipakai di QWeb.
        """
        arr = []

        for o in self.env['job.order'].browse(docids):
            stock = []

            def _stock_key(product_id, lot_id, lot_loc_name):
                return (product_id, lot_id, lot_loc_name)

            def _update_running_stock(line, used_qty):
                """Kurangi stok berjalan per (product, lot, location)."""
                if line.product_id:
                    key = _stock_key(line.product_id.id, line.lot_id.id, line.lot_location_id.complete_name)
                else:
                    key = _stock_key(line.product_id_stored.id, line.lot_id_stored, line.lot_location_id_stored)

                # cari existing
                found = None
                for s in stock:
                    if _stock_key(s['product_id'], s['lot_id'], s['lot_location_id']) == key:
                        found = s
                        break

                if found:
                    found['quantity'] -= used_qty
                    return found['quantity']
                else:
                    if o.state == 'done':
                        left_stock = (line.on_hand_quantity_stored or 0) - used_qty
                    else:
                        left_stock = (line.stock_quantity_id.quantity or 0) - used_qty
                    stock.append({
                        'product_id': key[0],
                        'lot_id': key[1],
                        'quantity': left_stock,
                        'lot_location_id': key[2],
                    })
                    return left_stock

            def _warehouse_display(loc):
                if not loc:
                    return ''
                # Tampilkan "Warehouse/SubLocation"
                if loc.location_id and loc.location_id.location_id and loc.location_id.location_id.name == 'Physical Locations':
                    parent = loc.location_id.name
                else:
                    parent = loc.location_id.location_id.name if loc.location_id and loc.location_id.location_id else ''
                return (parent + '/' + loc.name) if parent else loc.complete_name

            # ---- SINGLE / MULTI sama logikanya: susun arr flat dulu ----
            records = [o]
            if o.type == 'multiple_location':
                records = o.job_order_child_ids

            for rec in records:
                for requested in rec.job_order_line_ids:
                    # cutting dengan 1 line (no mixing)
                    mono_cutting = rec.job_order_cutting_ids.filtered(
                        lambda x: (len(x.line_ids) == 1 and x.line_ids.job_order_line_id.id == requested.id)
                    )
                    done_quantity = sum(mono_cutting.line_ids.mapped('done_quantity'))
                    cut_arr = []

                    for line in mono_cutting:
                        # kumpulkan balances
                        balance_arr = []
                        for b in line.balance_ids:
                            balance_arr.append({
                                'product_id': b.parent_product_id.id,
                                'length_balance': b.length_balance,
                                'width_balance': b.width_balance,
                                'kg_balance': b.kg_balance,
                                'quantity': b.qty,
                            })

                        # qty dipakai
                        used_qty = 1.0
                        if line.is_no_cutting:
                            for cl in line.line_ids:
                                used_qty = float(cl.done_quantity or 0.0)

                        running_left = _update_running_stock(line, used_qty)

                        cut_arr.append({
                            'dimension': (line.product_id.name if line.product_id else line.product_id_stored.name),
                            'lot_name': (line.lot_id.name if line.lot_id else line.lot_id_stored),
                            'used_qty': used_qty,
                            'location_name': (_warehouse_display(line.lot_location_id) or line.lot_location_id_stored),
                            'location_id': line.lot_location_id.id if line.lot_location_id else False,
                            'balances': balance_arr,
                            'cut_balance_stock': running_left,
                            'cut_balance_stock_bc': (line.on_hand_quantity if (line.product_id and o.state != 'done') else line.on_hand_quantity_stored),
                        })

                    arr.append({
                        'dimension': requested.product_id.name,
                        'description': requested.product_id.categ_id.name,
                        'uom': requested.product_id.uom_id.name,
                        'done_quantity': done_quantity,
                        'cuts': cut_arr,
                        'electrode_number': requested.electrode_number,
                    })

                # cutting yang punya banyak line (mix)
                mixing = rec.job_order_cutting_ids.filtered(lambda x: len(x.line_ids) > 1)
                for cut_double in mixing:
                    # balances khusus muncul sekali di cut terakhir (seperti versi lama)
                    balance_arr = [{
                        'product_id': b.parent_product_id.id,
                        'length_balance': b.length_balance,
                        'width_balance': b.width_balance,
                        'kg_balance': b.kg_balance,
                        'quantity': b.qty,
                    } for b in cut_double.balance_ids]

                    running_left = 0
                    used_qty = 1.0
                    if cut_double.product_id:
                        running_left = _update_running_stock(cut_double, used_qty)
                    else:
                        # kalau pakai stored hanya untuk printed info
                        if o.state == 'done':
                            running_left = (cut_double.on_hand_quantity_stored or 0) - used_qty
                        else:
                            running_left = (cut_double.stock_quantity_id.quantity or 0) - used_qty

                    cut_arr_mix = [{
                        'dimension': (cut_double.product_id.name if cut_double.product_id else cut_double.product_id_stored.name),
                        'lot_name': (cut_double.lot_id.name if cut_double.lot_id else cut_double.lot_id_stored),
                        'used_qty': used_qty,
                        'location_name': (_warehouse_display(cut_double.lot_location_id) or cut_double.lot_location_id_stored),
                        'location_id': cut_double.lot_location_id.id if cut_double.lot_location_id else False,
                        'balances': balance_arr,
                        'cut_balance_stock': running_left,
                        'cut_balance_stock_bc': (cut_double.on_hand_quantity if (cut_double.product_id and o.state != 'done') else cut_double.on_hand_quantity_stored),
                    }]

                    for l in cut_double.line_ids:
                        arr.append({
                            'dimension': l.job_order_line_id.product_id.name,
                            'description': l.job_order_line_id.product_id.categ_id.name,
                            'uom': l.job_order_line_id.product_id.uom_id.name,
                            'done_quantity': float(l.done_quantity or 0.0),
                            'cuts': cut_arr_mix,
                            'electrode_number': l.job_order_line_id.electrode_number,
                        })

        # ---- group untuk dipakai Qweb ----
        items = self._group_items(arr)

        return {
            'doc_ids': docids,
            'doc_model': 'job.order',
            'docs': self.env['job.order'].browse(docids),
            'items': items,      # ← gunakan di Qweb
        }
