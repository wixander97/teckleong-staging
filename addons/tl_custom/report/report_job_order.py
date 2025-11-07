# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError, AccessError


class ReportJobOrder(models.AbstractModel):
    _name = 'report.tl_custom.report_job_order'
    _description = 'Report Job Order'

    @api.model
    def _get_report_values(self, docids, data=None):
        arr = []

        for o in self.env['job.order'].browse(docids):
            stock = []

            if o.type == 'multiple_location':
                for child in o.job_order_child_ids:
                    for requested in child.job_order_line_ids:
                        cutting = child.job_order_cutting_ids.filtered(lambda x: (len(x.line_ids) == 1 and x.line_ids.job_order_line_id.id == requested.id))
                        done_quantity = 0
                        cut_arr = []

                        for line in cutting.line_ids:
                            done_quantity += line.done_quantity

                        for line in cutting:
                            balance_arr = []

                            for balance in line.balance_ids:
                                if len(balance_arr) == 0:
                                    balance_arr.append({
                                        'product_id': balance.parent_product_id.id,
                                        'length_balance': balance.length_balance,
                                        'width_balance': balance.width_balance,
                                        'kg_balance': balance.kg_balance,
                                        'quantity': balance.qty,
                                    })

                                else:
                                    cutting_balance = list(filter(lambda x: (x['length_balance'] == balance.length_balance and x['width_balance'] == balance.width_balance and x['kg_balance'] == balance.kg_balance), balance_arr))

                                    if cutting_balance:
                                        cutting_balance[0]['quantity'] += 1

                                    else:
                                        balance_arr.append({
                                            'product_id': balance.parent_product_id.id,
                                            'length_balance': balance.length_balance,
                                            'width_balance': balance.width_balance,
                                            'kg_balance': balance.kg_balance,
                                            'quantity': balance.qty,
                                        })

                            if len(cut_arr) == 0:
                                if line.product_id:
                                    stock_filter = list(filter(lambda x: (x['product_id'] == line.product_id.id and x['lot_id'] == line.lot_id.id and x['lot_location_id'] == line.lot_location_id.complete_name) , stock))
                                else:
                                    stock_filter = list(filter(lambda x: (x['product_id'] == line.product_id_stored.id and x['lot_id'] == line.lot_id_stored and x['lot_location_id'] == line.lot_location_id_stored) , stock))

                                stock_quantity = 0

                                used_quantity = 1

                                if line.is_no_cutting:
                                    for cutting_line in line.line_ids:
                                        used_quantity = int(cutting_line.done_quantity)

                                if stock_filter and stock_filter != []:
                                    stock_filter[0]['quantity'] -= used_quantity
                                    stock_quantity = stock_filter[0]['quantity']
                                else:
                                    left_stock = 0

                                    if o.state == 'done':
                                        left_stock = line.on_hand_quantity_stored - used_quantity
                                        stock_quantity = line.on_hand_quantity_stored -used_quantity
                                    else:
                                        left_stock = line.stock_quantity_id.quantity - used_quantity
                                        stock_quantity = line.stock_quantity_id.quantity - used_quantity

                                    stock.append({
                                        'product_id': line.product_id.id if line.product_id else line.product_id_stored.id,
                                        'lot_id': line.lot_id.id if line.product_id else line.lot_id_stored,
                                        'quantity': left_stock,
                                        'lot_location_id': line.lot_location_id.complete_name if line.lot_location_id else line.lot_location_id_stored,
                                    })

                                warehuse_name = ''

                                if line.lot_location_id.location_id.location_id.name == 'Physical Locations':
                                    warehuse_name = line.lot_location_id.location_id.name
                                else:
                                    warehuse_name = line.lot_location_id.location_id.location_id.name

                                if warehuse_name:
                                    warehuse_name = warehuse_name + "/" + line.lot_location_id.name

                                cut_arr.append({
                                    'dimension': line.product_id.name if line.product_id else line.product_id_stored.name,
                                    'lot_name': line.lot_id.name if line.lot_id else line.lot_id_stored,
                                    'used_qty': used_quantity,
                                    'location_name': warehuse_name if warehuse_name else line.lot_location_id_stored,
                                    'location_id': line.lot_location_id.id,
                                    'balances': balance_arr,
                                    'cut_balance_stock': stock_quantity,
                                    'cut_balance_stock_bc': line.on_hand_quantity if line.product_id and o.state != 'done' else line.on_hand_quantity_stored,
                                })
                            else:
                                if line.product_id:
                                    stock_filter = list(filter(lambda x: (x['product_id'] == line.product_id.id and x['lot_id'] == line.lot_id.id and x['lot_location_id'] == line.lot_location_id.complete_name) , stock))
                                else:
                                    stock_filter = list(filter(lambda x: (x['product_id'] == line.product_id_stored.id and x['lot_id'] == line.lot_id_stored and x['lot_location_id'] == line.lot_location_id_stored) , stock))

                                stock_quantity = 0

                                used_quantity = 1

                                if line.is_no_cutting:
                                    for cutting_line in line.line_ids:
                                        used_quantity = int(cutting_line.done_quantity)

                                if stock_filter:
                                    stock_filter[0]['quantity'] -= used_quantity
                                    stock_quantity = stock_filter[0]['quantity']
                                else:
                                    left_stock = 0

                                    if o.state == 'done':
                                        left_stock = line.on_hand_quantity_stored - used_quantity
                                        stock_quantity = line.on_hand_quantity_stored - used_quantity
                                    else:
                                        left_stock = line.stock_quantity_id.quantity - used_quantity
                                        stock_quantity = line.stock_quantity_id.quantity - used_quantity

                                    stock.append({
                                        'product_id': line.product_id.id if line.product_id else line.product_id_stored.id,
                                        'lot_id': line.lot_id.id if line.product_id else line.lot_id_stored,
                                        'quantity': left_stock,
                                        'lot_location_id': line.lot_location_id.complete_name if line.lot_location_id else line.lot_location_id_stored,
                                    })


                                cut = list(filter(lambda x: (x['dimension'] == line.product_id.name and x['lot_name'] == line.lot_id.name and x['location_id'] == line.lot_location_id.id) ,cut_arr))

                                if cut:
                                    cut[0]['used_qty'] += used_quantity
                                    cut[0]['cut_balance_stock'] -= used_quantity

                                    for balance_line in balance_arr:
                                        cutting_balance = list(filter(lambda x: (x['length_balance'] == balance_line['length_balance'] and x['width_balance'] == balance_line['width_balance'] and x['kg_balance'] == balance_line['kg_balance']), cut[0]['balances']))

                                        if cutting_balance:
                                            cutting_balance[0]['quantity'] += 1
                                        else:
                                            cut[0]['balances'].append(balance_line)

                                else:
                                    warehuse_name = ''

                                    if line.lot_location_id.location_id.location_id.name == 'Physical Locations':
                                        warehuse_name = line.lot_location_id.location_id.name
                                    else:
                                        warehuse_name = line.lot_location_id.location_id.location_id.name

                                    if warehuse_name:
                                        warehuse_name = warehuse_name + "/" + line.lot_location_id.name
                                    
                                    cut_arr.append({
                                        'dimension': line.product_id.name if line.product_id else line.product_id_stored.name,
                                        'lot_name': line.lot_id.name if line.lot_id else line.lot_id_stored,
                                        'used_qty': used_quantity,
                                        'location_name': warehuse_name if warehuse_name else line.lot_location_id_stored,
                                        'location_id': line.lot_location_id.id,
                                        'balances': balance_arr,
                                        'cut_balance_stock': stock_quantity,
                                        'cut_balance_stock_bc': line.on_hand_quantity if line.product_id and o.state != 'done' else line.on_hand_quantity_stored,
                                    })

                        arr.append({
                            'dimension': requested.product_id.name,
                            'description': requested.product_id.categ_id.name,
                            'uom': requested.product_id.uom_id.name,
                            'done_quantity': done_quantity,
                            'cuts': cut_arr,
                            'electrode_number': requested.electrode_number,
                        })

                    cutting_double = child.job_order_cutting_ids.filtered(lambda x: len(x.line_ids) > 1)

                    for cut_double in cutting_double:
                        for cutting_double_line in cut_double.line_ids:
                            cut_arr = []

                            if cutting_double_line == cut_double.line_ids[-1]:
                                balance_arr = []

                                for balance in cut_double.balance_ids:
                                    balance_arr.append({
                                        'product_id': balance.parent_product_id.id,
                                        'length_balance': balance.length_balance,
                                        'width_balance': balance.width_balance,
                                        'kg_balance': balance.kg_balance,
                                        'quantity': balance.qty,
                                    })

                                warehuse_name = ''

                                if cut_double.lot_location_id.location_id.location_id.name == 'Physical Locations':
                                    warehuse_name = cut_double.lot_location_id.location_id.name
                                else:
                                    warehuse_name = cut_double.lot_location_id.location_id.location_id.name

                                if warehuse_name:
                                    warehuse_name = warehuse_name + "/" + cut_double.lot_location_id.name

                                if cut_double.product_id:
                                    stock_filter = list(filter(lambda x: (x['product_id'] == cut_double.product_id.id and x['lot_id'] == cut_double.lot_id.id and x['lot_location_id'] == cut_double.lot_location_id.complete_name) , stock))
                                else:
                                    stock_filter = list(filter(lambda x: (x['product_id'] == cut_double.product_id_stored.id and x['lot_id'] == cut_double.lot_id_stored and x['lot_location_id'] == cut_double.lot_location_id_stored) , stock))

                                stock_quantity = 0
                                used_quantity = 1

                                if stock_filter:
                                    stock_filter[0]['quantity'] -= used_quantity
                                    stock_quantity = stock_filter[0]['quantity']
                                else:
                                    if o.state == 'done':
                                        left_stock = cut_double.on_hand_quantity_stored - used_quantity
                                        stock_quantity = cut_double.on_hand_quantity_stored - used_quantity
                                    else:
                                        left_stock = cut_double.stock_quantity_id.quantity - used_quantity
                                        stock_quantity = cut_double.stock_quantity_id.quantity - used_quantity

                                cut_arr.append({
                                    'dimension' : cut_double.product_id.name if cut_double.product_id else cut_double.product_id_stored.name,
                                    'lot_name': cut_double.lot_id.name if cut_double.lot_id else cut_double.lot_id_stored,
                                    'used_qty': 1,
                                    'location_name': warehuse_name if warehuse_name else cut_double.lot_location_id_stored,
                                    'location_id': cut_double.lot_location_id.id,
                                    'balances': balance_arr,
                                    'cut_balance_stock': stock_quantity,
                                    'cut_balance_stock_bc': cut_double.on_hand_quantity if cut_double.product_id and o.state != 'done' else line.on_hand_quantity_stored,
                                })

                            arr.append({
                                'dimension': cutting_double_line.job_order_line_id.product_id.name,
                                'description': cutting_double_line.job_order_line_id.product_id.categ_id.name,
                                'uom': cutting_double_line.job_order_line_id.product_id.uom_id.name,
                                'done_quantity': cutting_double_line.job_order_line_id.done_quantity,
                                'cuts': cut_arr,
                                'electrode_number': cutting_double_line.job_order_line_id.electrode_number,
                            })

            else:
                for requested in o.job_order_line_ids:
                    cutting = o.job_order_cutting_ids.filtered(lambda x: (len(x.line_ids) == 1 and x.line_ids.job_order_line_id.id == requested.id))
                    done_quantity = 0
                    cut_arr = []

                    for line in cutting.line_ids:
                        done_quantity += line.done_quantity

                    for line in cutting:
                        balance_arr = []

                        for balance in line.balance_ids:
                            if len(balance_arr) == 0:
                                balance_arr.append({
                                    'product_id': balance.parent_product_id.id,
                                    'length_balance': balance.length_balance,
                                    'width_balance': balance.width_balance,
                                    'kg_balance': balance.kg_balance,
                                    'quantity': balance.qty,
                                })

                            else:
                                cutting_balance = list(filter(lambda x: (x['length_balance'] == balance.length_balance and x['width_balance'] == balance.width_balance and x['kg_balance'] == balance.kg_balance), balance_arr))

                                if cutting_balance:
                                    cutting_balance[0]['quantity'] += 1

                                else:
                                    balance_arr.append({
                                        'product_id': balance.parent_product_id.id,
                                        'length_balance': balance.length_balance,
                                        'width_balance': balance.width_balance,
                                        'kg_balance': balance.kg_balance,
                                        'quantity': balance.qty,
                                    })

                        if len(cut_arr) == 0:
                            if line.product_id:
                                stock_filter = list(filter(lambda x: (x['product_id'] == line.product_id.id and x['lot_id'] == line.lot_id.id and x['lot_location_id'] == line.lot_location_id.complete_name) , stock))
                            else:
                                stock_filter = list(filter(lambda x: (x['product_id'] == line.product_id_stored.id and x['lot_id'] == line.lot_id_stored and x['lot_location_id'] == line.lot_location_id_stored) , stock))

                            stock_quantity = 0

                            used_quantity = 1

                            if line.is_no_cutting:
                                for cutting_line in line.line_ids:
                                    used_quantity = int(cutting_line.done_quantity)

                            if stock_filter and stock_filter != []:
                                stock_filter[0]['quantity'] -= used_quantity
                                stock_quantity = stock_filter[0]['quantity']
                            else:
                                left_stock = 0

                                if o.state == 'done':
                                    left_stock = line.on_hand_quantity_stored - used_quantity
                                    stock_quantity = line.on_hand_quantity_stored -used_quantity
                                else:
                                    left_stock = line.stock_quantity_id.quantity - used_quantity
                                    stock_quantity = line.stock_quantity_id.quantity - used_quantity

                                stock.append({
                                    'product_id': line.product_id.id if line.product_id else line.product_id_stored.id,
                                    'lot_id': line.lot_id.id if line.product_id else line.lot_id_stored,
                                    'quantity': left_stock,
                                    'lot_location_id': line.lot_location_id.complete_name if line.lot_location_id else line.lot_location_id_stored,
                                })

                            warehuse_name = ''

                            if line.lot_location_id.location_id.location_id.name == 'Physical Locations':
                                warehuse_name = line.lot_location_id.location_id.name
                            else:
                                warehuse_name = line.lot_location_id.location_id.location_id.name

                            if warehuse_name:
                                warehuse_name = warehuse_name + "/" + line.lot_location_id.name

                            cut_arr.append({
                                'dimension': line.product_id.name if line.product_id else line.product_id_stored.name,
                                'lot_name': line.lot_id.name if line.lot_id else line.lot_id_stored,
                                'used_qty': used_quantity,
                                'location_name': warehuse_name if warehuse_name else line.lot_location_id_stored,
                                'location_id': line.lot_location_id.id,
                                'balances': balance_arr,
                                'cut_balance_stock': stock_quantity,
                                'cut_balance_stock_bc': line.on_hand_quantity if line.product_id and o.state != 'done' else line.on_hand_quantity_stored,
                            })
                        else:
                            if line.product_id:
                                stock_filter = list(filter(lambda x: (x['product_id'] == line.product_id.id and x['lot_id'] == line.lot_id.id and x['lot_location_id'] == line.lot_location_id.complete_name) , stock))
                            else:
                                stock_filter = list(filter(lambda x: (x['product_id'] == line.product_id_stored.id and x['lot_id'] == line.lot_id_stored and x['lot_location_id'] == line.lot_location_id_stored) , stock))

                            stock_quantity = 0

                            used_quantity = 1

                            if line.is_no_cutting:
                                for cutting_line in line.line_ids:
                                    used_quantity = int(cutting_line.done_quantity)

                            if stock_filter:
                                stock_filter[0]['quantity'] -= used_quantity
                                stock_quantity = stock_filter[0]['quantity']
                            else:
                                left_stock = 0

                                if o.state == 'done':
                                    left_stock = line.on_hand_quantity_stored - used_quantity
                                    stock_quantity = line.on_hand_quantity_stored - used_quantity
                                else:
                                    left_stock = line.stock_quantity_id.quantity - used_quantity
                                    stock_quantity = line.stock_quantity_id.quantity - used_quantity

                                stock.append({
                                    'product_id': line.product_id.id if line.product_id else line.product_id_stored.id,
                                    'lot_id': line.lot_id.id if line.product_id else line.lot_id_stored,
                                    'quantity': left_stock,
                                    'lot_location_id': line.lot_location_id.complete_name if line.lot_location_id else line.lot_location_id_stored,
                                })


                            cut = list(filter(lambda x: (x['dimension'] == line.product_id.name and x['lot_name'] == line.lot_id.name and x['location_id'] == line.lot_location_id.id) ,cut_arr))

                            if cut:
                                cut[0]['used_qty'] += used_quantity
                                cut[0]['cut_balance_stock'] -= used_quantity

                                for balance_line in balance_arr:
                                    cutting_balance = list(filter(lambda x: (x['length_balance'] == balance_line['length_balance'] and x['width_balance'] == balance_line['width_balance'] and x['kg_balance'] == balance_line['kg_balance']), cut[0]['balances']))

                                    if cutting_balance:
                                        cutting_balance[0]['quantity'] += 1
                                    else:
                                        cut[0]['balances'].append(balance_line)

                            else:
                                warehuse_name = ''

                                if line.lot_location_id.location_id.location_id.name == 'Physical Locations':
                                    warehuse_name = line.lot_location_id.location_id.name
                                else:
                                    warehuse_name = line.lot_location_id.location_id.location_id.name

                                if warehuse_name:
                                    warehuse_name = warehuse_name + "/" + line.lot_location_id.name
                                
                                cut_arr.append({
                                    'dimension': line.product_id.name if line.product_id else line.product_id_stored.name,
                                    'lot_name': line.lot_id.name if line.lot_id else line.lot_id_stored,
                                    'used_qty': used_quantity,
                                    'location_name': warehuse_name if warehuse_name else line.lot_location_id_stored,
                                    'location_id': line.lot_location_id.id,
                                    'balances': balance_arr,
                                    'cut_balance_stock': stock_quantity,
                                    'cut_balance_stock_bc': line.on_hand_quantity if line.product_id and o.state != 'done' else line.on_hand_quantity_stored,
                                })

                    arr.append({
                        'dimension': requested.product_id.name,
                        'description': requested.product_id.categ_id.name,
                        'uom': requested.product_id.uom_id.name,
                        'done_quantity': done_quantity,
                        'cuts': cut_arr,
                        'electrode_number': requested.electrode_number,
                    })

                cutting_double = o.job_order_cutting_ids.filtered(lambda x: len(x.line_ids) > 1)

                for cut_double in cutting_double:
                    for cutting_double_line in cut_double.line_ids:
                        cut_arr = []

                        if cutting_double_line == cut_double.line_ids[-1]:
                            balance_arr = []

                            for balance in cut_double.balance_ids:
                                balance_arr.append({
                                    'product_id': balance.parent_product_id.id,
                                    'length_balance': balance.length_balance,
                                    'width_balance': balance.width_balance,
                                    'kg_balance': balance.kg_balance,
                                    'quantity': balance.qty,
                                })

                            warehuse_name = ''

                            if cut_double.lot_location_id.location_id.location_id.name == 'Physical Locations':
                                warehuse_name = cut_double.lot_location_id.location_id.name
                            else:
                                warehuse_name = cut_double.lot_location_id.location_id.location_id.name

                            if warehuse_name:
                                warehuse_name = warehuse_name + "/" + cut_double.lot_location_id.name

                            if cut_double.product_id:
                                stock_filter = list(filter(lambda x: (x['product_id'] == cut_double.product_id.id and x['lot_id'] == cut_double.lot_id.id and x['lot_location_id'] == cut_double.lot_location_id.complete_name) , stock))
                            else:
                                stock_filter = list(filter(lambda x: (x['product_id'] == cut_double.product_id_stored.id and x['lot_id'] == cut_double.lot_id_stored and x['lot_location_id'] == cut_double.lot_location_id_stored) , stock))


                            stock_quantity = 0
                            used_quantity = 1

                            if stock_filter:
                                stock_filter[0]['quantity'] -= used_quantity
                                stock_quantity = stock_filter[0]['quantity']
                            else:
                                if o.state == 'done':
                                    left_stock = cut_double.on_hand_quantity_stored - used_quantity
                                    stock_quantity = cut_double.on_hand_quantity_stored - used_quantity
                                else:
                                    left_stock = cut_double.stock_quantity_id.quantity - used_quantity
                                    stock_quantity = cut_double.stock_quantity_id.quantity - used_quantity

                            cut_arr.append({
                                'dimension' : cut_double.product_id.name if cut_double.product_id else cut_double.product_id_stored.name,
                                'lot_name': cut_double.lot_id.name if cut_double.lot_id else cut_double.lot_id_stored,
                                'used_qty': 1,
                                'location_name': warehuse_name if warehuse_name else cut_double.lot_location_id_stored,
                                'location_id': cut_double.lot_location_id.id,
                                'balances': balance_arr,
                                'cut_balance_stock': stock_quantity,
                                'cut_balance_stock_bc': cut_double.on_hand_quantity if cut_double.product_id and o.state != 'done' else line.on_hand_quantity_stored,
                            })

                        arr.append({
                            'dimension': cutting_double_line.job_order_line_id.product_id.name,
                            'description': cutting_double_line.job_order_line_id.product_id.categ_id.name,
                            'uom': cutting_double_line.job_order_line_id.product_id.uom_id.name,
                            'done_quantity': cutting_double_line.done_quantity,
                            'cuts': cut_arr,
                            'electrode_number': cutting_double_line.job_order_line_id.electrode_number,
                        })

        return {
            'doc_ids' : docids,
            'doc_model' : self.env['job.order'],
            'data' : data,
            'docs' : self.env['job.order'].browse(docids),
            'arr': arr,
        }
