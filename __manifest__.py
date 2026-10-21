{
    'name': 'Yagüven — Recuperar CAE de AFIP (comprobantes fantasma)',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localizations/Argentina',
    'summary': 'Detecta y recupera comprobantes autorizados por AFIP que no se guardaron '
               'en Odoo (timeout del WSFE), destrabando la numeración del punto de venta.',
    'description': """
Recuperación de comprobantes fantasma (AFIP autorizó, Odoo no guardó)
=======================================================================
Cuando AFIP autoriza un comprobante (CAE) pero la respuesta no llega a completar el
posteo en Odoo (timeout, corte de conexión), el punto de venta queda trabado: cualquier
factura siguiente del mismo journal + tipo de comprobante es rechazada por AFIP porque
la numeración local quedó un paso atrás.

- Detección automática: si un posteo falla por desalineación de numeración AFIP, se
  compara el último autorizado en AFIP contra el último posteado en Odoo, se consulta el
  comprobante faltante y se matchea contra los borradores del journal por importe/fecha.
- Cada coincidencia se deja como propuesta pendiente de confirmación (nunca se aplica
  sola) con una explicación en criollo y el dato de AFIP para verificar.
- Al confirmar: se completa el comprobante fantasma con su número y CAE reales (sin
  volver a pedir autorización a AFIP) y se reintenta el posteo de la factura que había
  disparado la detección.
- Wizard manual desde el journal para escanear bajo demanda, sin esperar a que falle un
  posteo.
""",
    'author': 'Yagüven C.G.',
    'website': 'https://yaguven.com',
    'license': 'AGPL-3',
    'depends': [
        'account',
        'account_accountant',
        'l10n_ar',
        'l10n_ar_edi',
    ],
    'data': [
        'security/ir.access.csv',
        'views/recuperar_cae_propuesta_views.xml',
        'views/account_journal_views.xml',
    ],
    'installable': True,
    'application': False,
}
