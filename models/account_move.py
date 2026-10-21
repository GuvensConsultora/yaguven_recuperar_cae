import logging

from odoo import SUPERUSER_ID, api, models

_logger = logging.getLogger(__name__)

SALTAR = 'yaguven_recuperar_cae_saltar'


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        """Engancha en `_post` y NO envuelve al `super()` en un savepoint.

        Dos cosas medidas en la 20 mandan este diseño:

        - **El punto de venta postea la factura del ticket con `_post()`**, no con `action_post()`
          (`pos.order._generate_pos_order_invoice`), y `action_post()` llama a `_post(soft=False)`.
          Un solo override cubre la caja y contabilidad.
        - **`l10n_ar_edi` hace `cr.commit()` adentro del posteo** para guardar el ticket de acceso de
          ARCA (`res_company._l10n_ar_get_connection`). Con un savepoint abierto eso revienta con
          «Pending savepoints not released, cannot commit!» y **ninguna factura electrónica postea**.
          Por eso acá no hay savepoint, y por eso la recuperación corre en **otra transacción**: si la
          hiciéramos en ésta, su propio commit arrastraría un posteo a medio hacer.
        """
        if self.env.context.get(SALTAR):
            return super()._post(soft=soft)
        try:
            return super()._post(soft=soft)
        except Exception:
            resueltos = self._yaguven_recuperar_cae()
            if not resueltos:
                raise
            # Cuáles se resolvieron lo dice la recuperación, NO el estado leído de la base: Odoo
            # abre sus transacciones en REPEATABLE READ, así que lo que la recuperación commiteó en
            # su propia transacción es invisible desde ésta — `invalidate_all()` relee contra la
            # misma foto y sigue viendo «borrador». Filtrar por estado hacía que el reintento
            # agarrara un comprobante ya posteado y la operación terminara bien pero con error.
            pendientes = self - self.browse(resueltos)
            if not pendientes:
                return self
            self.env.invalidate_all()
            return super(AccountMove, pendientes.with_context(**{SALTAR: True}))._post(soft=soft)

    # ------------------------------------------------------------------

    def _yaguven_recuperar_cae(self):
        """Resuelve el comprobante fantasma en una transacción aparte.

        Devuelve los ids de los comprobantes de ESTE recordset que quedaron resueltos y posteados
        por la recuperación, para que el que llama no los reintente. El trabajo va
        en un cursor nuevo por dos razones: consultar a ARCA commitea, y lo que anotemos tiene que
        sobrevivir al rollback de la excepción que estamos por volver a levantar.
        """
        candidatos = [
            m for m in self
            if m.state == 'draft'
            and m.move_type in ('out_invoice', 'out_refund')
            and m.journal_id.l10n_ar_afip_ws
            and m.l10n_latam_document_type_id
        ]
        if not candidatos:
            return []

        datos = [(m.journal_id.id, m.l10n_latam_document_type_id.id, m.id) for m in candidatos]
        resueltos = []
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {
                    'allowed_company_ids': self.company_id.ids or [self.env.company.id],
                })
                propuesta_model = env['yaguven.recuperar_cae.propuesta']
                for journal_id, doc_type_id, move_id in datos:
                    journal = env['account.journal'].browse(journal_id)
                    doc_type = env['l10n_latam.document.type'].browse(doc_type_id)
                    origen = env['account.move'].browse(move_id)
                    try:
                        propuestas = propuesta_model._escanear_journal(
                            journal, doc_types=doc_type, move_origen=origen)
                    except Exception:
                        _logger.exception(
                            'Recuperar CAE: falló la consulta a ARCA para el diario %s', journal_id)
                        continue
                    for propuesta in propuestas.sorted('numero_afip'):
                        arreglado = propuesta.move_fantasma_id.id
                        if propuesta._aplicar_automatica():
                            resueltos.append(arreglado)
                # El `with` commitea al salir: las propuestas y el fantasma arreglado quedan, pase
                # lo que pase con la transacción de afuera.
        except Exception:
            _logger.exception('Recuperar CAE: falló la recuperación en transacción aparte')
            return []
        return resueltos
