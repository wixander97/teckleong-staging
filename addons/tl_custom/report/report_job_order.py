# -*- coding: utf-8 -*-
from collections import OrderedDict
from odoo import api, models


class ReportJobOrder(models.AbstractModel):
    _name = 'report.tl_custom.report_job_order'
    _description = 'Report Job Order'

    # ---- helpers -------------------------------------------------------------

    def _merge_balances(self, balances):
        merged = {}
        for b in balances or []:
            key = (
                b.get('product_id'),
                float(b.get('length_balance') or 0),
                float(b.get('width_balance') or 0),
                float(b.get('kg_balance') or 0)
            )
            if key not in merged:
                merged[key] = {
                    'product_id': b.get('product_id'),
                    'length_balance': float(b.get('length_balance') or 0),
                    'width_balance': float(b.get('width_balance') or 0),
                    'kg_balance': float(b.get('kg_balance') or 0),
                    'quantity': float(b.get('quantity') or 0),
                }
            else:
                merged[key]['quantity'] += float(b.get('quantity') or 0)
        return list(merged.values())

    def _merge_cuts(self, cuts):
        merged = OrderedDict()
        for c in cuts or []:
            key = (c.get('dimension'), c.get('lot_name'), c.get('location_id'))
            if key not in merged:
                merged[key] = c.copy()
                merged[key]['used_qty'] = float(c.get('used_qty') or 0)
                merged[key]['balances'] = self._merge_balances(c.get('balances') or [])
            else:
                merged[key]['used_qty'] += float(c.get('used_qty') or 0)
                merged[key]['balances'] = self._merge_balances(
                    (merged[key].get('balances') or []) + (c.get('balances') or [])
                )
                if 'cut_balance_stock' in c:
                    merged[key]['cut_balance_stock'] = c['cut_balance_stock']
                if 'cut_balance_stock_bc' in c:
                    merged[key]['cut_balance_stock_bc'] = c['cut_balance_stock_bc']
        return list(merged.values())

    def _group_items(self, arr):
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
            grouped[key]['total_done'] += float(line.get('done_quantity') or 0)
            grouped[key]['cuts'].extend(line.get('cuts') or [])

        for item in grouped.values():
            item['cuts'] = self._merge_cuts(item['cuts'])

        return list(grouped.values()) or []   # <--- IMPORTANT SAFETY

    # ---- MAIN ---------------------------------------------------------------

    @api.model
    def _get_report_values(self, docids, data=None):
        arr = []
        job_orders = self.env['job.order'].browse(docids)

        for o in job_orders:
            stock = []
            def _skey(pid, lid, loc):
                return (pid, lid, loc)

            def _stock_update(line, qty):
                pid = line.product_id.id if line.product_id else line.product_id_stored.id
                lid = line.lot_id.id if line.lot_id else line.lot_id_stored
                loc = line.lot_location_id.complete_name if line.lot_location_id else line.lot_location_id_stored
                key = _skey(pid, lid, loc)

                before = (line.on_hand_quantity if line.product_id and o.state != 'done'
                        else line.on_hand_quantity_stored)
                before = float(before or 0)

                after = before - float(qty or 0)

                found = next((s for s in stock if _skey(s['product_id'], s['lot_id'], s['lot_location_id']) == key), None)
                if found:
                    found['quantity'] = after
                else:
                    stock.append({'product_id': pid, 'lot_id': lid, 'lot_location_id': loc, 'quantity': after})

                return before, after

            def _wh(loc):
                if not loc:
                    return ''
                parent = loc.location_id.location_id.name if (loc.location_id and loc.location_id.location_id) else ''
                return parent + '/' + loc.name if parent else loc.complete_name

            records = o.job_order_child_ids if o.type == 'multiple_location' else [o]

            for rec in records:
                for req in rec.job_order_line_ids:
                    # single-line cutting (1 JO line → 1 cut line group)
                    mono = rec.job_order_cutting_ids.filtered(
                        lambda x: len(x.line_ids) == 1 and x.line_ids.job_order_line_id.id == req.id
                    )

                    done_q = sum(mono.line_ids.mapped('done_quantity'))
                    cuts = []

                    for line in mono:
                        used = sum(line.line_ids.mapped('done_quantity')) if line.is_no_cutting else 1

                        # ✅ get before & after from stock tracker
                        before_cut, left = _stock_update(line, used)

                        cuts.append({
                            'dimension': line.product_id.name if line.product_id else line.product_id_stored.name,
                            'lot_name': line.lot_id.name if line.lot_id else line.lot_id_stored,
                            'used_qty': used,
                            'location_name': _wh(line.lot_location_id),
                            'location_id': line.lot_location_id.id if line.lot_location_id else False,
                            'balances': [{
                                'product_id': b.parent_product_id.id,
                                'length_balance': b.length_balance,
                                'width_balance': b.width_balance,
                                'kg_balance': b.kg_balance,
                                'quantity': b.qty,
                            } for b in line.balance_ids],

                            'cut_balance_stock_bc': before_cut,
                            'cut_balance_stock': left,
                        })

                    arr.append({
                        'dimension': req.product_id.name,
                        'description': req.product_id.categ_id.name,
                        'uom': req.product_id.uom_id.name,
                        'done_quantity': done_q,
                        'cuts': cuts,
                        'electrode_number': req.electrode_number,
                    })

        items = self._group_items(arr)

        return {
            'doc_ids': docids,
            'doc_model': 'job.order',
            'docs': job_orders,
            'items': items,
        }
