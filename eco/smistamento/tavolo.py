"""
Il tavolo di smistamento: dove sta ogni file dell'eco, e la conferma.

Ogni allegato di un'eco ha una PropostaSmistamento: una riga del catalogo,
il referto dell'ecografo, oppure «da smistare». Le proposte le scrive lo
smistamento automatico (esecuzione.py) e le cambia chi carica, trascinando
un file o con «Sposta in...» (`sposta`). **Nessuna ProiezioneCaricata nasce
da una proposta** finche' chi carica non preme «Confermo lo smistamento»
(`conferma`): e' la stessa filosofia del lettore SEIVA di VetCardio,
proporre e non scrivere mai senza conferma. Cosa manca per inviare lo dice
sempre consulti.regole (che guarda le ProiezioneCaricata): qui non si
riscrive la regola.

Il caricamento riga per riga di prima resta: un file lasciato su una riga
crea subito la sua ProiezioneCaricata (e' gia' una scelta di chi carica) e
qui diventa una proposta «RIGA», gia' confermata.
"""

from django.db import transaction

from consulti.caricamento import genere_file
from consulti.models import Allegato, CategoriaAllegato, StatoAllegato

STATO_CONFERMATO = 'confermato'
STATO_SICURO = 'sicuro'
STATO_VERIFICA = 'verifica'
STATO_MANUALE = 'manuale'


class SpostamentoNonValido(Exception):
    """Il messaggio e' pensato per l'utente."""


def _modelli():
    from eco.models import FonteProposta, ProiezioneCaricata, ProiezioneCatalogo, PropostaSmistamento
    return FonteProposta, ProiezioneCaricata, ProiezioneCatalogo, PropostaSmistamento


def registra_da_cartella(allegato, percorso='', modificato_il=None):
    """Un file arrivato dalla zona unica: nasce «da smistare», con cio' che
    serve all'ordine di acquisizione."""
    FonteProposta, _pc, _cat, PropostaSmistamento = _modelli()
    return PropostaSmistamento.objects.create(
        richiesta=allegato.richiesta, allegato=allegato, fonte=FonteProposta.DA_SMISTARE,
        percorso_originale=(percorso or '')[:500], modificato_il=modificato_il)


def allegati_eco(richiesta):
    return richiesta.allegati.exclude(stato=StatoAllegato.SCARTATO)


def assicura_proposte(richiesta):
    """Ogni file dell'eco ha la sua proposta. Un file senza proposta (caricato
    nella riga o nella zona del referto, o da una versione precedente) la
    prende da cio' che e' gia' confermato; se un'altra proposta occupava quel
    posto, quella torna da smistare."""
    FonteProposta, _pc, _cat, PropostaSmistamento = _modelli()
    senza = allegati_eco(richiesta).filter(proposta_smistamento__isnull=True).prefetch_related('proiezioni')
    for allegato in senza:
        pc = next(iter(allegato.proiezioni.all()), None)
        with transaction.atomic():
            if pc is not None:
                PropostaSmistamento.objects.filter(richiesta=richiesta, proiezione=pc.proiezione).update(
                    proiezione=None, fonte=FonteProposta.DA_SMISTARE, sicura=False,
                    motivo='Il posto e\' andato al file caricato direttamente nella riga.')
                PropostaSmistamento.objects.create(richiesta=richiesta, allegato=allegato, proiezione=pc.proiezione,
                                                   nota=pc.nota, fonte=FonteProposta.RIGA)
            elif allegato.categoria == CategoriaAllegato.ECO_REFERTO_PDF:
                PropostaSmistamento.objects.filter(richiesta=richiesta, referto=True).update(
                    referto=False, fonte=FonteProposta.DA_SMISTARE, sicura=False,
                    motivo='Il referto e\' quello caricato nella sua zona.')
                PropostaSmistamento.objects.create(richiesta=richiesta, allegato=allegato, referto=True,
                                                   fonte=FonteProposta.RIGA)
            else:
                PropostaSmistamento.objects.create(richiesta=richiesta, allegato=allegato)


def stato_confermato(richiesta):
    """(allegato_id -> proiezione_id delle ProiezioneCaricata, id dei PDF
    referto confermati)."""
    confermate = dict(richiesta.proiezioni.values_list('allegato_id', 'proiezione_id'))
    referti = set(richiesta.allegati.filter(categoria=CategoriaAllegato.ECO_REFERTO_PDF).values_list('pk', flat=True))
    return confermate, referti


def e_confermata(proposta, confermate, referti):
    """La proposta coincide con cio' che e' gia' confermato (per un file da
    smistare: che non stia confermato da nessuna parte)."""
    if proposta.proiezione_id:
        return confermate.get(proposta.allegato_id) == proposta.proiezione_id
    if proposta.referto:
        return proposta.allegato_id in referti
    return proposta.allegato_id not in confermate and proposta.allegato_id not in referti


def bollino(proposta, confermata):
    FonteProposta = _modelli()[0]
    if proposta.da_smistare:
        return ''
    if confermata or proposta.fonte == FonteProposta.RIGA:
        return STATO_CONFERMATO
    if proposta.fonte == FonteProposta.MANUALE:
        return STATO_MANUALE
    return STATO_SICURO if proposta.sicura else STATO_VERIFICA


def _compatibile(allegato, proiezione=None, referto=False):
    """None se il file puo' andare li', altrimenti la frase che dice perche' no."""
    genere = genere_file(allegato.nome_originale or allegato.file.name, allegato.mime)
    nome = allegato.nome_originale or 'il file'
    if referto:
        return None if genere == 'pdf' else f'Il referto dell\'ecografo e\' un PDF: «{nome}» non lo e\'.'
    if proiezione is None:
        return None
    if genere == 'pdf':
        return f'«{nome}» e\' un PDF: puo\' essere solo il referto dell\'ecografo.'
    if genere == 'dicom' or proiezione.tipo_media == 'ENTRAMBI':
        return None
    if proiezione.tipo_media == 'CLIP' and genere != 'video':
        return f'In «{proiezione.nome}» va un filmato: «{nome}» e\' un\'immagine.'
    if proiezione.tipo_media == 'STATICA' and genere != 'immagine':
        return f'In «{proiezione.nome}» va un\'immagine: «{nome}» e\' un filmato.'
    return None


def destinazioni(richiesta, allegato, righe):
    """Le voci del menu «Sposta in...» per un file: [(valore, etichetta)]
    solo dove il file puo' andare. `righe`: ProiezioneCatalogo in ordine."""
    voci = []
    if _compatibile(allegato, referto=True) is None:
        voci.append(('referto', 'Referto dell\'ecografo (PDF)'))
    for p in righe:
        if _compatibile(allegato, proiezione=p) is None:
            voci.append((f'proiezione:{p.pk}', p.nome))
    voci.append(('nessuna', 'Da smistare (togli dalla riga)'))
    return voci


def sposta(richiesta, allegato, destinazione, nota=None):
    """Mette un file in una riga ('proiezione:<id>'), nel referto ('referto')
    o fra i file da smistare ('nessuna'). Se il posto e' occupato i due file
    si scambiano (se l'altro puo' andare dov'era questo; se no torna da
    smistare). Solo proposte: la conferma e' `conferma`."""
    FonteProposta, _pc, ProiezioneCatalogo, PropostaSmistamento = _modelli()
    assicura_proposte(richiesta)
    proiezione, referto = None, False
    if destinazione == 'referto':
        referto = True
    elif destinazione.startswith('proiezione:'):
        try:
            pk = int(destinazione.split(':', 1)[1])
        except ValueError:
            pk = None
        proiezione = ProiezioneCatalogo.objects.filter(pk=pk, attiva=True).first()
        if proiezione is None:
            raise SpostamentoNonValido('Riga non trovata nel catalogo: ricarica la pagina.')
    elif destinazione != 'nessuna':
        raise SpostamentoNonValido('Destinazione sconosciuta: ricarica la pagina.')
    errore = _compatibile(allegato, proiezione=proiezione, referto=referto)
    if errore:
        raise SpostamentoNonValido(errore)

    with transaction.atomic():
        p = PropostaSmistamento.objects.select_for_update().get(allegato=allegato)
        vecchia_riga, vecchio_referto = p.proiezione, p.referto
        occupante = None
        if proiezione is not None:
            occupante = PropostaSmistamento.objects.filter(richiesta=richiesta, proiezione=proiezione) \
                .exclude(pk=p.pk).first()
        elif referto:
            occupante = PropostaSmistamento.objects.filter(richiesta=richiesta, referto=True).exclude(pk=p.pk).first()
        # Prima si libera il posto di questo file (vincolo: una riga, un file).
        p.proiezione, p.referto = None, False
        p.save(update_fields=['proiezione', 'referto'])
        if occupante is not None:
            occupante.proiezione, occupante.referto = None, False
            puo_scambiare = (vecchia_riga is not None or vecchio_referto) and _compatibile(
                occupante.allegato, proiezione=vecchia_riga, referto=vecchio_referto) is None
            if puo_scambiare:
                occupante.proiezione, occupante.referto = vecchia_riga, vecchio_referto
                occupante.motivo = f'Scambiato con «{allegato.nome_originale}».'
            else:
                occupante.motivo = f'Il posto e\' andato a «{allegato.nome_originale}».'
            occupante.fonte, occupante.sicura = FonteProposta.MANUALE, False
            occupante.save()
        p.proiezione, p.referto = proiezione, referto
        p.fonte, p.sicura = FonteProposta.MANUALE, False
        p.motivo = ''
        if nota is not None:
            p.nota = (nota or '').strip()[:200]
        p.save()
    return p


class SmistamentoNonValido(Exception):
    """Il messaggio e' pensato per l'utente."""


def conferma(richiesta, utente, note=None):
    """Le proposte diventano cio' che conta per inviare: ProiezioneCaricata
    per le righe, categoria ECO_REFERTO_PDF per il referto. `note`:
    {proiezione_id: testo} per i filmati liberi (obbligatoria). Ritorna
    (righe piene, file rimasti da smistare)."""
    _f, ProiezioneCaricata, _cat, PropostaSmistamento = _modelli()
    assicura_proposte(richiesta)
    note = note or {}
    proposte = list(PropostaSmistamento.objects.filter(richiesta=richiesta)
                    .select_related('allegato', 'proiezione'))
    for p in proposte:
        if p.proiezione_id and p.proiezione_id in note:
            p.nota = (note[p.proiezione_id] or '').strip()[:200]
        # La nota di un filmato libero e' FACOLTATIVA (decisione di Andre del
        # 12/09): un filmato libero non e' obbligatorio, e pretendere la nota
        # lo rendeva tale — chi aveva messo un file li' non poteva confermare
        # finche' non scriveva qualcosa.
    with transaction.atomic():
        voluto = {p.allegato_id: p for p in proposte if p.proiezione_id}
        for pc in list(richiesta.proiezioni.all()):
            p = voluto.get(pc.allegato_id)
            if p is None or p.proiezione_id != pc.proiezione_id:
                pc.delete()
            elif pc.nota != p.nota:
                pc.nota = p.nota
                pc.save(update_fields=['nota'])
        gia = set(richiesta.proiezioni.values_list('allegato_id', 'proiezione_id'))
        for p in voluto.values():
            if (p.allegato_id, p.proiezione_id) not in gia:
                ProiezioneCaricata.objects.create(richiesta=richiesta, proiezione=p.proiezione,
                                                  allegato=p.allegato, nota=p.nota)
            p.save(update_fields=['nota'])
            _allinea_categoria(p.allegato, p.proiezione)
        referti = {p.allegato_id for p in proposte if p.referto}
        for a in Allegato.objects.filter(richiesta=richiesta, categoria=CategoriaAllegato.ECO_REFERTO_PDF) \
                .exclude(pk__in=referti):
            a.categoria = CategoriaAllegato.ALTRO
            a.save(update_fields=['categoria'])
        Allegato.objects.filter(pk__in=referti).update(categoria=CategoriaAllegato.ECO_REFERTO_PDF)
        da_smistare = sum(1 for p in proposte if p.da_smistare)
        # Ogni conferma e' una correzione umana, cioe' la verita': si registra
        # per la misura dello smistamento (eco/smistamento/esiti.py).
        from . import esiti
        esiti.registra_conferma(richiesta, proposte)
        richiesta.registra('SMISTAMENTO_CONFERMATO', utente, righe=len(voluto), referto=bool(referti),
                           da_smistare=da_smistare)
    return len(voluto), da_smistare


def _allinea_categoria(allegato, proiezione):
    """Un DICOM (o un file senza categoria eco) prende la categoria della riga."""
    voluta = CategoriaAllegato.ECO_STATICA if proiezione.tipo_media == 'STATICA' else CategoriaAllegato.ECO_CLIP
    genere = genere_file(allegato.nome_originale or allegato.file.name, allegato.mime)
    if genere == 'video':
        voluta = CategoriaAllegato.ECO_CLIP
    elif genere == 'immagine':
        voluta = CategoriaAllegato.ECO_STATICA
    if allegato.categoria != voluta:
        allegato.categoria = voluta
        allegato.save(update_fields=['categoria'])


def modifiche_da_confermare(richiesta):
    """Quante proposte non coincidono con lo stato confermato."""
    _f, _pc, _cat, PropostaSmistamento = _modelli()
    confermate, referti = stato_confermato(richiesta)
    return sum(1 for p in PropostaSmistamento.objects.filter(richiesta=richiesta)
               if not e_confermata(p, confermate, referti))
