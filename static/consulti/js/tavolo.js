/* ═══════════════════════════════════════════════════════════════════════
   tavolo.js — il tavolo di smistamento dell'eco (passo 3).

   Un file (.posto-file) si sposta in due modi, entrambi verso
   consulti:smistamento_sposta (se il posto e' occupato i due file si
   scambiano; e' solo una proposta, la conferma e' «Confermo lo smistamento»):
   - trascinandolo su una riga, sul referto o sui «Da smistare» (elementi
     con data-destinazione);
   - con il menu «Sposta in...»: col mouse o col dito parte alla scelta;
     da tastiera (le frecce cambiano la voce) parte con Invio o il pulsante
     «Sposta», che per questo resta.
   Dopo lo spostamento la pagina si ricarica e torna dove si era.
   Senza JavaScript il menu con il pulsante fa una POST normale.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var primo = document.querySelector('form[data-sposta]');
  var CHIAVE = 'consulti-tavolo-scroll';
  try {
    var y = sessionStorage.getItem(CHIAVE);
    if (y !== null) { sessionStorage.removeItem(CHIAVE); window.scrollTo(0, parseInt(y, 10) || 0); }
  } catch (e) { /* storage non disponibile */ }
  if (!primo) return;
  var URL_SPOSTA = primo.getAttribute('action');
  var csrf = primo.querySelector('[name=csrfmiddlewaretoken]').value;

  function avviso(testo) {
    var box = document.getElementById('avviso-tavolo');
    if (!box) {
      box = document.createElement('div');
      box.id = 'avviso-tavolo';
      box.className = 'alert alert-danger avviso-tavolo';
      box.setAttribute('role', 'alert');
      document.body.appendChild(box);
    }
    box.textContent = testo;
    box.hidden = false;
    clearTimeout(box._timer);
    box._timer = setTimeout(function () { box.hidden = true; }, 6000);
  }

  async function sposta(allegato, destinazione) {
    var dati = new FormData();
    dati.append('allegato', allegato);
    dati.append('destinazione', destinazione);
    document.body.classList.add('tavolo-in-corso');
    try {
      var r = await fetch(URL_SPOSTA, {method: 'POST', headers: {'X-CSRFToken': csrf, 'Accept': 'application/json'},
                                       body: dati});
      var j = {};
      try { j = await r.json(); } catch (e) { /* non JSON */ }
      if (!r.ok) { avviso(j.errore || 'Spostamento non riuscito: ricarica la pagina.'); return; }
      try { sessionStorage.setItem(CHIAVE, String(window.scrollY)); } catch (e) { /* niente */ }
      location.reload();
    } catch (e) {
      avviso('Connessione interrotta: riprova.');
    } finally {
      document.body.classList.remove('tavolo-in-corso');
    }
  }

  // ── Menu «Sposta in...» ───────────────────────────────────────────────
  document.querySelectorAll('form[data-sposta]').forEach(function (form) {
    var menu = form.querySelector('select');
    var allegato = form.querySelector('[name=allegato]').value;
    var daTastiera = 0;
    menu.addEventListener('keydown', function (e) {
      daTastiera = Date.now();
      if (e.key === 'Enter' && menu.value) { e.preventDefault(); sposta(allegato, menu.value); }
    });
    menu.addEventListener('change', function () {
      if (!menu.value || Date.now() - daTastiera < 800) return;
      sposta(allegato, menu.value);
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (menu.value) sposta(allegato, menu.value);
    });
  });

  // ── Trascinamento ─────────────────────────────────────────────────────
  var TIPO = 'application/x-consulti-allegato';
  var inVolo = null;
  document.addEventListener('dragstart', function (e) {
    var el = e.target.closest && e.target.closest('.posto-file[draggable=true]');
    if (!el) return;
    inVolo = el.dataset.allegato;
    e.dataTransfer.setData(TIPO, inVolo);
    e.dataTransfer.setData('text/plain', el.dataset.nome || '');
    e.dataTransfer.effectAllowed = 'move';
    el.classList.add('in-volo');
    document.body.classList.add('trascinando-file');
  });
  document.addEventListener('dragend', function (e) {
    var el = e.target.closest && e.target.closest('.posto-file');
    if (el) el.classList.remove('in-volo');
    document.body.classList.remove('trascinando-file');
    document.querySelectorAll('.bersaglio').forEach(function (b) { b.classList.remove('bersaglio'); });
    inVolo = null;
  });
  function bersaglioDi(e) {
    if (!inVolo) return null;
    return e.target.closest ? e.target.closest('[data-destinazione]') : null;
  }
  document.addEventListener('dragover', function (e) {
    var b = bersaglioDi(e);
    if (!b) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    document.querySelectorAll('.bersaglio').forEach(function (x) { if (x !== b) x.classList.remove('bersaglio'); });
    b.classList.add('bersaglio');
  });
  document.addEventListener('drop', function (e) {
    var b = bersaglioDi(e);
    if (!b) return;
    e.preventDefault();
    b.classList.remove('bersaglio');
    var allegato = inVolo;
    inVolo = null;
    // Lasciato dov'era gia': niente da fare.
    if (b.querySelector('.posto-file[data-allegato="' + allegato + '"]')) return;
    sposta(allegato, b.dataset.destinazione);
  });
})();
