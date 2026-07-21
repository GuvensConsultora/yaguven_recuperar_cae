import logging

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import html_escape

_logger = logging.getLogger(__name__)

AMOUNT_TOLERANCE = 0.01


class RecuperarCaePropuesta(models.Model):
    _name = 'yaguven.recuperar_cae.propuesta'
    _description = 'Propuesta de recuperación de CAE (comprobante fantasma AFIP)'
    _order = 'create_date desc'

    company_id = fields.Many2one('res.company', required=True, readonly=True)
    journal_id = fields.Many2one('account.journal', required=True, readonly=True)
    l10n_latam_document_type_id = fields.Many2one(
        'l10n_latam.document.type', string='Tipo de comprobante',
        required=True, readonly=True)
    numero_afip = fields.Integer('Número autorizado por AFIP', required=True, readonly=True)
    cae = fields.Char('CAE', readonly=True)
    cae_vencimiento = fields.Date('Vencimiento CAE', readonly=True)
    fecha_afip = fields.Date('Fecha del comprobante (AFIP)', readonly=True)
    importe_total = fields.Float('Importe total (AFIP)', readonly=True)
    move_fantasma_id = fields.Many2one(
        'account.move', string='Borrador que coincide (fantasma)', readonly=True)
    move_origen_id = fields.Many2one(
        'account.move', string='Factura que disparó la detección', readonly=True)
    estado = fields.Selection([
        ('pendiente', 'Pendiente de confirmar'),
        ('revision_manual', 'Revisión manual (sin match único)'),
        ('aplicada', 'Aplicada'),
        ('error', 'Error al aplicar'),
    ], default='pendiente', required=True, readonly=True)
    mensaje = fields.Html('Explicación', readonly=True)

    _sql_constraints = [
        ('gap_unico', 'unique(journal_id, l10n_latam_document_type_id, numero_afip)',
         'Ya existe una propuesta para este comprobante.'),
    ]

    # ------------------------------------------------------------------
    # Escaneo / detección
    # ------------------------------------------------------------------

    @api.model
    def _escanear_journal(self, journal, doc_types=None, move_origen=None):
        """Compara AFIP vs Odoo para el/los tipo(s) de comprobante del journal.
        Reutiliza propuestas pendientes existentes en vez de duplicarlas."""
        if not doc_types:
            grouped = self.env['account.move'].read_group(
                [('journal_id', '=', journal.id), ('state', '=', 'posted'),
                 ('l10n_latam_document_type_id', '!=', False)],
                ['l10n_latam_document_type_id'], ['l10n_latam_document_type_id'])
            doc_type_ids = [g['l10n_latam_document_type_id'][0] for g in grouped]
            doc_types = self.env['l10n_latam.document.type'].browse(doc_type_ids)

        propuestas = self.browse()
        for doc_type in doc_types:
            propuestas |= self._escanear_doc_type(journal, doc_type, move_origen=move_origen)
        return propuestas

    @api.model
    def _escanear_doc_type(self, journal, doc_type, move_origen=None):
        ultimo_afip = journal._l10n_ar_get_afip_last_invoice_number(doc_type)

        posted = self.env['account.move'].search([
            ('journal_id', '=', journal.id),
            ('l10n_latam_document_type_id', '=', doc_type.id),
            ('state', '=', 'posted'),
        ])
        numeros_posted = [
            int(m.l10n_latam_document_number.split('-')[1])
            for m in posted if m.l10n_latam_document_number
        ]
        ultimo_odoo = max(numeros_posted) if numeros_posted else 0

        if ultimo_afip <= ultimo_odoo:
            return self.browse()

        propuestas = self.browse()
        for numero in range(ultimo_odoo + 1, ultimo_afip + 1):
            existente = self.search([
                ('journal_id', '=', journal.id),
                ('l10n_latam_document_type_id', '=', doc_type.id),
                ('numero_afip', '=', numero),
            ], limit=1)
            if existente:
                if move_origen and not existente.move_origen_id:
                    existente.move_origen_id = move_origen.id
                propuestas |= existente
                continue
            propuestas |= self._crear_propuesta(journal, doc_type, numero, move_origen)
        return propuestas

    @api.model
    def _crear_propuesta(self, journal, doc_type, numero, move_origen):
        company = journal.company_id
        con = company._l10n_ar_get_connection('wsfe')
        client, auth = con._get_client()[0], con._get_client()[1]
        resp = client.service.FECompConsultar(Auth=auth, FeCompConsReq={
            'CbteTipo': int(doc_type.code),
            'PtoVta': journal.l10n_ar_afip_pos_number,
            'CbteNro': numero,
        })
        data = resp['ResultGet']
        importe = float(data['ImpTotal'])

        candidatos = self.env['account.move'].search([
            ('journal_id', '=', journal.id),
            ('l10n_latam_document_type_id', '=', doc_type.id),
            ('state', '=', 'draft'),
            ('amount_total', '>=', importe - AMOUNT_TOLERANCE),
            ('amount_total', '<=', importe + AMOUNT_TOLERANCE),
        ])

        vals = {
            'company_id': company.id,
            'journal_id': journal.id,
            'l10n_latam_document_type_id': doc_type.id,
            'numero_afip': numero,
            'cae': data['CodAutorizacion'],
            'cae_vencimiento': self._afip_fecha(data['FchVto']),
            'fecha_afip': self._afip_fecha(data['CbteFch']),
            'importe_total': importe,
            'move_origen_id': move_origen.id if move_origen else False,
        }

        if len(candidatos) == 1:
            vals['move_fantasma_id'] = candidatos.id
            vals['estado'] = 'pendiente'
            vals['mensaje'] = self._mensaje_pendiente(journal, numero, data, candidatos)
        else:
            vals['estado'] = 'revision_manual'
            vals['mensaje'] = self._mensaje_revision(journal, numero, data, candidatos)

        return self.create(vals)

    @api.model
    def _afip_fecha(self, valor):
        # AFIP devuelve fechas como 'YYYYMMDD'.
        if not valor:
            return False
        return f'{valor[0:4]}-{valor[4:6]}-{valor[6:8]}'

    # ------------------------------------------------------------------
    # Mensajes (siempre Markup + html_escape, C.4)
    # ------------------------------------------------------------------

    @api.model
    def _numero_fmt(self, journal, numero):
        return f'{journal.l10n_ar_afip_pos_number:05d}-{numero:08d}'

    @api.model
    def _mensaje_pendiente(self, journal, numero, data, move):
        num_fmt = self._numero_fmt(journal, numero)
        partes = [
            f'<p>AFIP ya autorizó el comprobante <strong>{html_escape(num_fmt)}</strong> '
            f'el {html_escape(self._afip_fecha(data["CbteFch"]))}, pero no se guardó en '
            f'Odoo (se cortó la conexión) — por eso quedó trabada la facturación de '
            f'{html_escape(journal.name)}.</p>',
            f'<p>Encontramos que corresponde al borrador de '
            f'<strong>${html_escape(f"{move.amount_total:,.2f}")}</strong> '
            f'({html_escape(move.partner_id.name or "")}).</p>',
            '<p>Al confirmar: se completa ese borrador con el número y CAE reales y se '
            'postea — no se le vuelve a pedir autorización a AFIP.</p>',
            f'<p>CAE de AFIP para verificar: {html_escape(data["CodAutorizacion"])}</p>',
        ]
        return Markup(''.join(partes))

    @api.model
    def _mensaje_revision(self, journal, numero, data, candidatos):
        num_fmt = self._numero_fmt(journal, numero)
        importe_fmt = f'{float(data["ImpTotal"]):,.2f}'
        if not candidatos:
            detalle = 'no encontramos ningún borrador con ese importe'
        else:
            detalle = (
                f'encontramos {len(candidatos)} borradores con el mismo importe, no se '
                'puede determinar cuál es sin revisión manual'
            )
        partes = [
            f'<p>AFIP ya autorizó el comprobante <strong>{html_escape(num_fmt)}</strong> '
            f'por <strong>${html_escape(importe_fmt)}</strong>, pero no se guardó en '
            f'Odoo.</p>',
            f'<p>No lo pudimos matchear solos: {html_escape(detalle)}. Requiere '
            'revisión manual antes de aplicar.</p>',
        ]
        return Markup(''.join(partes))

    # ------------------------------------------------------------------
    # Aplicación
    # ------------------------------------------------------------------

    def action_confirmar(self):
        self.ensure_one()
        if self.estado != 'pendiente':
            raise UserError('Esta propuesta no está pendiente de confirmación.')

        move = self.move_fantasma_id
        # B.14: re-verificar en vivo antes de tocar nada — pudo cambiar desde la detección.
        if move.state != 'draft' or move.l10n_ar_afip_auth_code:
            raise UserError(
                'El borrador cambió de estado desde que se detectó esta propuesta — '
                'revisar a mano antes de reintentar.')

        num_fmt = self._numero_fmt(self.journal_id, self.numero_afip)
        move.write({
            'l10n_latam_document_number': num_fmt,
            'l10n_ar_afip_auth_code': self.cae,
            'l10n_ar_afip_auth_code_due': self.cae_vencimiento,
            'invoice_date': self.fecha_afip,
        })
        move.write({
            'l10n_ar_afip_auth_mode': 'CAE',
            'l10n_ar_afip_result': 'A',
        })

        try:
            move.action_post()
        except Exception:
            _logger.exception('Error al postear el comprobante recuperado %s', move.id)
            self.estado = 'error'
            raise UserError(
                'El CAE se escribió pero el posteo del comprobante recuperado falló — '
                'revisar el registro a mano.')

        move.message_post(
            body=Markup(
                f'<p>CAE recuperado automáticamente (Yagüven — Recuperar CAE de AFIP). '
                f'Comprobante {html_escape(num_fmt)}, CAE {html_escape(self.cae)}.</p>'),
            subject='CAE recuperado',
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )

        resultado_origen = ''
        origen = self.move_origen_id
        if origen and origen != move and origen.state == 'draft':
            try:
                origen.action_post()
                resultado_origen = (
                    f'<p>Tu factura (${html_escape(f"{origen.amount_total:,.2f}")}) '
                    f'también quedó posteada, como '
                    f'{html_escape(origen.l10n_latam_document_number or "")}.</p>'
                )
            except Exception:
                _logger.exception(
                    'CAE recuperado pero no se pudo reintentar el posteo original %s',
                    origen.id)
                resultado_origen = (
                    '<p>El fantasma se corrigió, pero tu factura original todavía no '
                    'pudo postearse — probá de nuevo desde la factura.</p>'
                )

        self.write({
            'estado': 'aplicada',
            'mensaje': Markup((self.mensaje or '') + resultado_origen),
        })
