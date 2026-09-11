/* ═══════════════════════════════════════════════════════════════════════
   elenco_filtrato.js — un campo di testo con sotto l'elenco delle voci che
   corrispondono a cio' che si scrive (combobox ARIA 1.2 con listbox), senza
   librerie. Nessun riferimento al dominio: candidato per vetway-ui 0.3.0.

   Markup atteso:
     <div class="elenco-filtrato">
       <input role="combobox" aria-autocomplete="list" aria-expanded="false"
              aria-controls="ID_LISTA" data-elenco-filtrato="ID_JSON"
              data-chiave-da="NOME_RADIO" data-avviso="ID_AVVISO">
       <ul class="elenco-filtrato-voci" id="ID_LISTA" role="listbox" hidden></ul>
     </div>
     <div id="ID_AVVISO" hidden>Non e' nell'elenco...</div>
     {{ dati|json_script:"ID_JSON" }}   {chiave: [voci, ...], ...}

   L'elenco usato e' quello della chiave scelta con i radio NOME_RADIO (qui:
   la specie). Cambiando chiave, un valore che non sta nel nuovo elenco si
   svuota. Un valore fuori elenco resta (l'avviso lo dice); uno che
   corrisponde a meno di maiuscole e accenti prende la grafia dell'elenco.

   Regola del filtro (la stessa di consulti/razze.py:filtra): minuscole senza
   accenti; prima le voci che iniziano con il testo, poi quelle che lo
   contengono, ciascun gruppo nell'ordine dell'elenco.

   Tastiera: frecce su/giu' per muoversi, Invio sceglie la voce evidenziata
   (senza voce evidenziata Invio invia il form come sempre), Esc chiude,
   Tab esce. Tocco e mouse: si tocca la voce.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  function piano(testo) {
    return (testo || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function filtra(voci, testo) {
    var cerca = piano(testo);
    if (!cerca) { return voci.slice(); }
    var iniziano = [], contengono = [];
    voci.forEach(function (v) {
      var p = piano(v);
      if (p.indexOf(cerca) === 0) { iniziano.push(v); }
      else if (p.indexOf(cerca) > 0) { contengono.push(v); }
    });
    return iniziano.concat(contengono);
  }

  function avvia(input) {
    var sorgente = document.getElementById(input.getAttribute('data-elenco-filtrato'));
    var lista = document.getElementById(input.getAttribute('aria-controls'));
    if (!sorgente || !lista) { return; }
    var dati = JSON.parse(sorgente.textContent);
    var nomeChiave = input.getAttribute('data-chiave-da');
    var avviso = document.getElementById(input.getAttribute('data-avviso') || '');
    var form = input.form || document;
    var voci = [], attiva = -1, timerChiudi = null;

    function chiave() {
      if (!nomeChiave) { return Object.keys(dati)[0]; }
      var scelto = form.querySelector('[name="' + nomeChiave + '"]:checked');
      return scelto ? scelto.value : '';
    }
    function elenco() { return dati[chiave()] || []; }
    function esatta() {
      var p = piano(input.value);
      if (!p) { return null; }
      return elenco().filter(function (v) { return piano(v) === p; })[0] || null;
    }

    function segnaposto() {
      input.placeholder = chiave() ? 'Scrivi per cercare, es. meticcio' : 'Scegli prima la specie';
    }

    function mostraAvviso(si) {
      if (!avviso) { return; }
      avviso.hidden = !si;
      if (si) { input.setAttribute('aria-describedby', avviso.id); }
      else { input.removeAttribute('aria-describedby'); }
    }

    function chiudi() {
      lista.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      attiva = -1;
    }

    function disegna() {
      voci = filtra(elenco(), input.value);
      lista.innerHTML = '';
      attiva = -1;
      input.removeAttribute('aria-activedescendant');
      // Niente da proporre, o il testo e' gia' esattamente l'unica voce: chiuso.
      if (!voci.length || (voci.length === 1 && esatta() === voci[0] && input.value === voci[0])) {
        chiudi();
        return;
      }
      voci.forEach(function (v, i) {
        var li = document.createElement('li');
        li.id = lista.id + '-' + i;
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', 'false');
        li.textContent = v;
        lista.appendChild(li);
      });
      lista.scrollTop = 0;
      lista.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    }

    function evidenzia(i) {
      if (!voci.length) { return; }
      var voce = lista.children[attiva];
      if (voce) { voce.setAttribute('aria-selected', 'false'); }
      attiva = Math.max(0, Math.min(i, voci.length - 1));
      voce = lista.children[attiva];
      voce.setAttribute('aria-selected', 'true');
      input.setAttribute('aria-activedescendant', voce.id);
      voce.scrollIntoView({block: 'nearest'});
    }

    function scegli(i) {
      input.value = voci[i];
      chiudi();
      mostraAvviso(false);
      input.dispatchEvent(new Event('change', {bubbles: true}));
    }

    // Fuori elenco: l'avviso; dentro a meno di maiuscole/accenti: la grafia dell'elenco.
    function controlla() {
      var voce = esatta();
      if (voce) { input.value = voce; }
      mostraAvviso(Boolean(input.value.trim() && chiave() && !voce));
    }

    input.addEventListener('input', function () { mostraAvviso(false); disegna(); });
    input.addEventListener('focus', function () { clearTimeout(timerChiudi); disegna(); });
    input.addEventListener('click', function () { if (lista.hidden) { disegna(); } });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (lista.hidden) { disegna(); }
        evidenzia(attiva + 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (!lista.hidden) { evidenzia(attiva - 1); }
      } else if (e.key === 'Enter' && !lista.hidden && attiva >= 0) {
        e.preventDefault();
        scegli(attiva);
      } else if (e.key === 'Escape' && !lista.hidden) {
        e.preventDefault();
        chiudi();
      } else if (e.key === 'Tab') {
        chiudi();
      }
    });
    input.addEventListener('blur', function () {
      // Un attimo di respiro: un tocco sulla voce arriva dopo il blur su alcuni browser.
      timerChiudi = setTimeout(function () { chiudi(); controlla(); }, 150);
    });
    // Il fuoco resta sul campo mentre si tocca o si clicca una voce.
    lista.addEventListener('mousedown', function (e) { e.preventDefault(); });
    lista.addEventListener('click', function (e) {
      var voce = e.target.closest('[role="option"]');
      if (!voce) { return; }
      clearTimeout(timerChiudi);
      scegli(Array.prototype.indexOf.call(lista.children, voce));
    });

    if (nomeChiave) {
      form.addEventListener('change', function (e) {
        if (e.target.name !== nomeChiave) { return; }
        segnaposto();
        if (input.value.trim() && !esatta()) { input.value = ''; }
        mostraAvviso(false);
        chiudi();
      });
    }
    segnaposto();
    if (input.value.trim()) { controlla(); }
  }

  document.querySelectorAll('input[data-elenco-filtrato]').forEach(avvia);
})();
