{
    'name': 'Yagüven — Recuperar CAE de AFIP (comprobantes fantasma)',
    'version': '20.0.3.0.0',
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
  comprobante faltante y se matchea contra los borradores del journal por importe.
- **Se resuelve sin intervención**: completa el comprobante fantasma con su número y CAE
  reales (sin volver a pedir autorización a AFIP), lo postea y reintenta el posteo que
  había quedado trabado. El enganche está en `_post`, así que cubre tanto la factura que
  carga contabilidad como la del ticket de caja, que el punto de venta postea por su
  cuenta. Es un circuito de venta: nadie puede quedarse esperando a que otra persona lo
  destrabe.
- Si hay varios borradores con el mismo importe toma el más reciente y lo deja dicho en el
  chatter, con cuáles eran los otros, para poder controlarlo después.
- Si no hay NINGÚN borrador con ese importe no se puede resolver solo —no existe a qué
  ponerle el CAE— y queda anotado para revisión.
- La recuperación corre en una TRANSACCIÓN APARTE, y el posteo no se envuelve en ningún
  savepoint: `l10n_ar_edi` hace `commit()` adentro del posteo para guardar el ticket de
  acceso de ARCA, y con un savepoint abierto eso aborta con «Pending savepoints not
  released» — dejando sin postear a TODA factura electrónica.
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
