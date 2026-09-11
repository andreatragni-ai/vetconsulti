"""
Cosa si aspetta una riga del catalogo, letto dal suo nome.

Il catalogo (eco/catalogo/catalogo_eco.json) non ha un campo «tipo di
tracciato» ne' «color si/no»: lo dicono i nomi, scritti da Andre con una
convenzione fissa («— B-mode», «— color Doppler», «Doppler pulsato»,
«Doppler continuo», «TDI», «M-mode»). Queste due funzioni sono l'unico
posto che la legge; i test in eco/tests_smistamento.py le provano su tutte
le 27 righe, cosi' un nome cambiato che rompe la convenzione si vede.

Il vincolo di colore vale solo per i FILMATI: le immagini Doppler
«con color» (pulsato transmitralico, polmonare da sinistra) hanno il color
nella finestrella bidimensionale ma sono tracciati spettrali, e il colore
dei pixel non distingue niente.
"""

import re

from .dati import BIDIMENSIONALE, BMODE, COLOR, CONTINUO, M_MODE, PULSATO, TDI, Riga


def tracciato_di(nome):
    n = nome.lower()
    if re.search(r'\btdi\b', n):
        return TDI
    if 'doppler continuo' in n:
        return CONTINUO
    if 'doppler pulsato' in n:
        return PULSATO
    if 'm-mode' in n:
        return M_MODE
    return BIDIMENSIONALE


def colore_di(nome, tipo_media):
    """'color' per i filmati «— color Doppler», 'bmode' per «— B-mode»,
    None per tutto il resto (immagini, filmati liberi)."""
    if tipo_media != 'CLIP':
        return None
    n = nome.lower()
    if 'color doppler' in n:
        return COLOR
    if 'b-mode' in n:
        return BMODE
    return None


def da_catalogo(proiezioni):
    """Righe dello smistamento dalle ProiezioneCatalogo gia' in ordine di
    protocollo (eco.models.in_ordine)."""
    from eco.models import Finestra
    righe = []
    for i, p in enumerate(proiezioni):
        righe.append(Riga(
            id=p.id, codice=p.codice, nome=p.nome, finestra=Finestra(p.finestra).label if p.finestra else '',
            tipo_media=p.tipo_media, ordine=i, libera=p.libera, obbligatoria=p.obbligatoria,
            deve_essere_visibile=p.deve_essere_visibile, tracciato=tracciato_di(p.nome),
            colore=colore_di(p.nome, p.tipo_media)))
    return righe
