/* ═══════════════════════════════════════════════════════════════════════
   carica.js — passo «Carica gli esami» della richiesta guidata.

   Ogni zona e' un <form data-zona> con dentro l'input file (vedi
   consulti/percorso/_zona.html e _file.html). Scegliere o trascinare un
   file lo manda subito:
   - POST semplice (XHR, con barra di avanzamento) per PDF e immagini;
   - a pezzi con ripresa (upload/stato, upload/pezzo, upload/concludi) per
     i filmati, il file dell'Holter (data-a-pezzi) e i file sopra il limite
     della POST semplice. Lo stato riceve anche la zona: il server dice
     subito se il file non va bene, prima di mandare centinaia di MB.
   La categoria la decide il server; qui si controlla solo cio' che evita un
   viaggio inutile (limite di peso, nota del filmato libero). Con ogni
   immagine o filmato parte anche la sua miniatura (anteprime.js).
   Finiti tutti i caricamenti la pagina si ricarica e torna sulla riga
   appena usata (anche se sta in un gruppo che si e' chiuso da solo).
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var radice = document.querySelector('[data-carica]');
  if (!radice) return;

  var URL_CARICA = radice.dataset.urlCarica;
  var URL_PEZZI = radice.dataset.urlPezzi.replace(/stato\/$/, '');
  var MAX_SEMPLICE = parseInt(radice.dataset.maxSemplice, 10);
  var MAX_PEZZI = parseInt(radice.dataset.maxPezzi, 10);
  var PEZZO = 4 * 1024 * 1024;
  var CHIAVE_RITORNO = 'consulti-carica-ritorno';
  var csrfEl = document.querySelector('[name=csrfmiddlewaretoken]');
  var csrf = csrfEl ? csrfEl.value : '';
  var inCorso = 0, riusciti = 0, falliti = 0;
  // I caricamenti a pezzi vanno uno alla volta: su una linea d'ambulatorio
  // dieci filmati in parallelo arrivano tutti piu' tardi, e due file uguali
  // (stessa impronta) si pesterebbero i piedi sul file d'appoggio.
  var codaPezzi = Promise.resolve();
  function inCoda(lavoro) {
    var turno = codaPezzi.then(lavoro, lavoro);
    codaPezzi = turno.catch(function () { /* l'errore lo mostra la zona */ });
    return turno;
  }

  // ── Utilita' ──────────────────────────────────────────────────────────
  function mb(n) {
    var v = n / 1048576;
    return (v < 10 ? v.toFixed(1) : Math.round(v).toString()).replace('.', ',');
  }
  function stato(form, testo, errore) {
    var s = form.querySelector('.zona-carica-stato');
    if (!s) return;
    s.textContent = testo || '';
    s.classList.toggle('errore', !!errore);
  }
  function barra(form, frazione) {
    var p = form.querySelector('.progress');
    if (!p) return;
    p.hidden = frazione === null;
    if (frazione !== null) p.firstElementChild.style.width = Math.round(frazione * 100) + '%';
  }
  function campi(form, dati) {
    ['slot', 'proiezione', 'sostituisci', 'nota'].forEach(function (k) {
      var el = form.querySelector('[name=' + k + ']');
      if (el && el.value) dati.append(k, el.value);
    });
  }
  function eFilmato(file) {
    return /^video\//.test(file.type) || /\.(mp4|m4v|mov|avi|webm|mkv|wmv|mpe?g|ogv|dcm|dicom)$/i.test(file.name);
  }
  function attendi(ms) { return new Promise(function (ok) { setTimeout(ok, ms); }); }
  async function leggiJson(risposta) {
    try { return await risposta.json(); } catch (e) { return {}; }
  }

  // ── POST semplice ─────────────────────────────────────────────────────
  function semplice(form, file, anteprima) {
    return new Promise(function (ok, ko) {
      var dati = new FormData();
      dati.append('file', file);
      if (anteprima) dati.append('anteprima', anteprima, 'anteprima.jpg');
      campi(form, dati);
      var xhr = new XMLHttpRequest();
      xhr.open('POST', URL_CARICA);
      xhr.setRequestHeader('X-CSRFToken', csrf);
      xhr.setRequestHeader('Accept', 'application/json');
      xhr.upload.onprogress = function (e) {
        if (!e.lengthComputable) return;
        barra(form, e.loaded / e.total);
        stato(form, 'Caricati ' + mb(e.loaded) + ' di ' + mb(e.total) + ' MB');
      };
      xhr.onload = function () {
        var j = {};
        try { j = JSON.parse(xhr.responseText); } catch (e) { /* risposta non JSON */ }
        if (xhr.status >= 200 && xhr.status < 300) ok(j);
        else ko(new Error(j.errore || 'Caricamento non riuscito (errore ' + xhr.status + ').'));
      };
      xhr.onerror = function () { ko(new Error('Connessione interrotta: riprova.')); };
      xhr.send(dati);
    });
  }

  // ── A pezzi, con ripresa ──────────────────────────────────────────────
  async function impronta(file) {
    var buf = await file.arrayBuffer();
    var h = await crypto.subtle.digest('SHA-256', buf);
    return Array.from(new Uint8Array(h)).map(function (b) { return b.toString(16).padStart(2, '0'); }).join('');
  }
  async function chiediStato(form, file, sha) {
    var q = new URLSearchParams();
    campi(form, q);
    q.append('nome', file.name);
    q.append('mime', file.type || '');
    q.append('dimensione', file.size);
    q.append('impronta', sha);
    var r = await fetch(URL_PEZZI + 'stato/?' + q.toString(), {headers: {'Accept': 'application/json'}});
    var j = await leggiJson(r);
    if (!r.ok) throw new Error(j.errore || 'Caricamento non riuscito.');
    return j.ricevuti || 0;
  }
  async function aPezzi(form, file, anteprima) {
    if (!(window.crypto && crypto.subtle)) {
      throw new Error('Questo browser non puo\' caricare file grandi su una connessione non sicura (serve https).');
    }
    stato(form, 'Preparo il file…');
    barra(form, 0);
    var sha = await impronta(file);
    var offset = await chiediStato(form, file, sha);
    var tentativi = 0;
    while (offset < file.size) {
      var dati = new FormData();
      dati.append('impronta', sha);
      dati.append('offset', offset);
      dati.append('pezzo', file.slice(offset, offset + PEZZO));
      var r, j;
      try {
        r = await fetch(URL_PEZZI + 'pezzo/', {method: 'POST', headers: {'X-CSRFToken': csrf}, body: dati});
        j = await leggiJson(r);
      } catch (e) {
        // Linea caduta: si aspetta un poco e si chiede al server da dove ripartire.
        if (++tentativi > 6) throw new Error('Connessione interrotta: riprova, il caricamento riparte da dove era.');
        stato(form, 'Connessione interrotta, riprovo…');
        await attendi(1500 * tentativi);
        offset = await chiediStato(form, file, sha);
        continue;
      }
      if (!r.ok) {
        if (j.ricevuti !== undefined) { offset = j.ricevuti; continue; }
        throw new Error(j.errore || 'Caricamento non riuscito.');
      }
      tentativi = 0;
      offset = j.ricevuti;
      barra(form, offset / file.size);
      stato(form, 'Caricati ' + mb(offset) + ' di ' + mb(file.size) + ' MB');
    }
    var fine = new FormData();
    fine.append('impronta', sha);
    fine.append('nome', file.name);
    fine.append('mime', file.type || '');
    if (anteprima) fine.append('anteprima', anteprima, 'anteprima.jpg');
    campi(form, fine);
    stato(form, 'Controllo il file…');
    var rf = await fetch(URL_PEZZI + 'concludi/', {method: 'POST', headers: {'X-CSRFToken': csrf}, body: fine});
    var jf = await leggiJson(rf);
    if (!rf.ok) throw new Error(jf.errore || 'Caricamento non riuscito.');
    return jf;
  }

  // ── Un file in una zona ───────────────────────────────────────────────
  async function carica(form, file) {
    var nota = form.querySelector('[name=nota]');
    if (nota && !nota.value.trim()) {
      stato(form, 'Scrivi prima cosa mostra il filmato o cosa chiedi.', true);
      nota.focus();
      return;
    }
    var limite = parseInt(form.dataset.maxByte || '0', 10);
    if (limite && eFilmato(file) && file.size > limite) {
      stato(form, 'Il filmato pesa ' + mb(file.size) + ' MB: il limite e\' ' + mb(limite) +
            ' MB. Esporta un filmato piu\' breve (una decina di secondi) o in MP4.', true);
      return;
    }
    if (file.size > MAX_PEZZI) {
      stato(form, 'Il file pesa ' + mb(file.size) + ' MB: il limite e\' ' + mb(MAX_PEZZI) + ' MB.', true);
      return;
    }
    var pezzi = form.dataset.aPezzi === '1' || eFilmato(file) || file.size > MAX_SEMPLICE;
    inCorso++;
    form.classList.add('in-corso');
    stato(form, 'Carico ' + file.name + '…');
    try {
      var anteprima = window.ConsultiAnteprime ? await window.ConsultiAnteprime.genera(file).catch(function () { return null; }) : null;
      if (pezzi) stato(form, 'In coda: ' + file.name + '…');
      var j = pezzi ? await inCoda(function () { return aPezzi(form, file, anteprima); }) : await semplice(form, file, anteprima);
      riusciti++;
      barra(form, 1);
      stato(form, 'Caricato: ' + j.nome);
      var riga = form.closest('[id]');
      try { sessionStorage.setItem(CHIAVE_RITORNO, riga ? riga.id : ''); } catch (e) { /* storage non disponibile */ }
    } catch (e) {
      falliti++;
      barra(form, null);
      stato(form, e.message, true);
    } finally {
      inCorso--;
      form.classList.remove('in-corso');
      if (inCorso === 0) {
        if (riusciti && !falliti) location.reload();
        else if (riusciti && falliti) {
          stato(form, (form.querySelector('.zona-carica-stato').textContent || '') +
                ' Gli altri file sono stati caricati: aggiorna la pagina per vederli.', true);
        }
        riusciti = 0; falliti = 0;
      }
    }
  }

  async function caricaTutti(form, files) {
    // Una riga = un file: nelle zone con un posto solo si prende il primo.
    var elenco = Array.prototype.slice.call(files);
    if (!form.querySelector('[name=sostituisci]') && form.closest('.riga-proiezione') &&
        !form.querySelector('[name=nota]') && elenco.length > 1) {
      elenco = elenco.slice(0, 1);
    }
    for (var i = 0; i < elenco.length; i++) await carica(form, elenco[i]);
  }

  document.querySelectorAll('form[data-zona]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      // Con JS il file parte da solo; il pulsante «Carica» e' per chi non ha JS.
      e.preventDefault();
      var input = form.querySelector('input[type=file]');
      if (input && input.files.length) caricaTutti(form, input.files);
    });
    form.addEventListener('change', function (e) {
      if (e.target.type !== 'file' || !e.target.files.length) return;
      var files = e.target.files;
      caricaTutti(form, files).then(function () { e.target.value = ''; });
    });
    if (!form.classList.contains('zona-carica')) return;
    ['dragenter', 'dragover'].forEach(function (ev) {
      form.addEventListener(ev, function (e) { e.preventDefault(); form.classList.add('trascina'); });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      form.addEventListener(ev, function (e) { e.preventDefault(); form.classList.remove('trascina'); });
    });
    form.addEventListener('drop', function (e) {
      if (e.dataTransfer && e.dataTransfer.files.length) caricaTutti(form, e.dataTransfer.files);
    });
  });

  // Un file lasciato fuori da una zona non deve aprirsi nel browser al posto della pagina.
  ['dragover', 'drop'].forEach(function (ev) {
    window.addEventListener(ev, function (e) {
      if (!e.target.closest || !e.target.closest('.zona-carica')) e.preventDefault();
    });
  });

  // ── Dove tornare, gruppi e lista ──────────────────────────────────────
  function apriFino(el) {
    for (var p = el; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true;
  }
  function vaiA(id) {
    var el = id && document.getElementById(id);
    if (!el) return;
    apriFino(el);
    el.scrollIntoView({block: 'start'});
  }
  try {
    var ritorno = sessionStorage.getItem(CHIAVE_RITORNO);
    if (ritorno) { sessionStorage.removeItem(CHIAVE_RITORNO); vaiA(ritorno); }
  } catch (e) { /* storage non disponibile */ }
  if (location.hash) vaiA(location.hash.slice(1));
  // La lista di controllo porta alla riga anche se sta in un gruppo chiuso.
  document.querySelectorAll('.lista-controllo a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      e.preventDefault();
      vaiA(a.getAttribute('href').slice(1));
    });
  });
  // Immagini di riferimento: un clic le ingrandisce nella modale, con le
  // altre della stessa riga come miniature per passare dall'una all'altra.
  var modale = document.getElementById('modalRiferimento');
  if (modale && window.bootstrap) {
    var grande = document.getElementById('modalRiferimentoImmagine');
    var didascalia = document.getElementById('modalRiferimentoDidascalia');
    var titolo = document.getElementById('modalRiferimentoTitolo');
    var strip = document.getElementById('modalRiferimentoMiniature');
    var mostra = function (link) {
      var img = link.querySelector('img');
      grande.src = link.getAttribute('href');
      grande.alt = img ? img.alt : '';
      didascalia.textContent = link.dataset.didascalia || '';
      strip.querySelectorAll('button').forEach(function (b) { b.classList.toggle('attiva', b.dataset.href === link.getAttribute('href')); });
    };
    document.addEventListener('click', function (e) {
      var link = e.target.closest && e.target.closest('[data-ingrandisci]');
      if (!link) return;
      e.preventDefault();
      var galleria = link.closest('[data-galleria]');
      var tutti = galleria ? Array.prototype.slice.call(galleria.querySelectorAll('[data-ingrandisci]')) : [link];
      titolo.textContent = galleria ? galleria.dataset.galleria : 'Riferimento';
      strip.innerHTML = '';
      if (tutti.length > 1) {
        tutti.forEach(function (altro) {
          var b = document.createElement('button');
          b.type = 'button';
          b.dataset.href = altro.getAttribute('href');
          b.setAttribute('aria-label', altro.dataset.didascalia || 'Riferimento');
          var mini = document.createElement('img');
          mini.src = altro.getAttribute('href');
          mini.alt = '';
          b.appendChild(mini);
          b.addEventListener('click', function () { mostra(altro); });
          strip.appendChild(b);
        });
      }
      mostra(link);
      bootstrap.Modal.getOrCreateInstance(modale).show();
    });
  }

  // Su telefono una lista lunga starebbe tutta sopra le zone: si parte chiusi.
  var elenco = document.querySelector('.elenco-controllo');
  if (elenco && window.matchMedia('(max-width: 767.98px)').matches &&
      elenco.querySelectorAll('.lista-controllo li').length > 4) {
    elenco.open = false;
  }
})();
