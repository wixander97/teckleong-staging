# -*- coding: utf-8 -*-

# Part of Probuse Consulting Service Pvt Ltd. See LICENSE file for full copyright and licensing details.

{
    'name': "Hide Inbox Chat",
    'license': 'AGPL-3',
    'summary': """Hide Chatter & Inbox
Hide Discussion Menu and chatter from Odoo Tray""",
    'description': """
        Hide Chatter & Inbox
        Hide Discussion Menu and chatter from Odoo Tray
        
    """,
    'version': "15.0",
    'author': "David Montero Crespo",
    'support': 'softwareescarlata@gmail.com',
    'images': ['static/description/img.png'],
    'category' : 'tools',
    'depends': ['base'],
    'data':[

    ],
    'assets': {
        'web.assets_qweb': [
            'remove_chat_inbox/static/src/xml/*.xml',
        ],
    },
    'installable' : True,
    'application' : False,
    'auto_install' : False,

}
