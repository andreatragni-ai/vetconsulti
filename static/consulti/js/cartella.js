/* ═══════════════════════════════════════════════════════════════════════
   cartella.js — la zona unica del passo 3 dell'eco: l'esame intero.

   Da dove arrivano i file:
   - cartella trascinata (desktop): si attraversa con webkitGetAsEntry e
     createReader().readEntries(), anche nelle sottocartelle;
   - «Scegli la cartella» (<input webkitdirectory>, desktop);
   - «Scegli i file» (<input multiple>): ovunque, ed e' l'unico pulsante su
     iPad e iPhone, dove i browser non aprono cartelle.
   Si scartano i file di sistema (.DS_Store, Thumbs.db, desktop.ini, file e
   cartelle nascosti, __MACOSX) e i formati che non servono, dicendo quanti.

   Poi, uno alla volta nell'ordine di acquisizione (nome naturale): la
   miniatura (anteprime.js) e il file, con la POST semplice o a pezzi per i
   file grandi e i filmati (stessi endpoint di carica.js, zona «cartella»).
   Lo stesso file gia' caricato non si duplica (il server risponde 409
   gia_presente). Avanzamento complessivo: «12 di 27 file caricati». Alla
   fine parte lo smistamento automatico e la pagina si ricarica: la
   sorveglianza htmx dello stato mostra il tavolo quando e' pronto.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var zona = document.querySelector('[data-cartella]');
  var radice = document.querySelector('[data-carica]');
  if (!zona || !radice) return;

  var URL_CARICA = radice.dataset.urlCarica;
  var URL_PEZZI = radice.dataset.urlPezzi.replace(/stato\/$/, '');
  var URL_AVVIA = zona.dataset.urlAvvia;
  var MAX_SEMPLICE = parseInt(radice.dataset.maxSemplice, 10);
  var MAX_PEZZI = parseInt(radice.dataset.maxPezzi, 10);
  var MAX_CLIP = parseInt(zona.dataset.maxClip || '0', 10);
  var PEZZO = 4 * 1024 * 1024;
  var csrfEl = document.querySelector('[name=csrfmiddlewaretoken]');
  var csrf = csrfEl ? csrfEl.value : '';
  var area = zona.querySelector('[data-area-cartella]');
  var pannello = zona.querySelector('[data-avanzamento]');
  var conteggio = zona.querySelector('[data-conteggio]');
  var corrente = zona.querySelector('[data-corrente]');
  var barra = zona.querySelector('[data-barra]');
  var note = zona.querySelector('[data-note]');
  var statoEl = zona.querySelector('[data-stato]');
  var occupato = false;

  // iPad e iPhone: niente cartelle nei browser (anche Safari su iPadOS, che si
  // presenta come un Mac con lo schermo tattile).
  var IOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
            (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var CARTELLE = !IOS && ('webkitdirectory' in document.createElement('input'));
  if (!CARTELLE) {
    zona.querySelectorAll('[data-solo-cartella]').forEach(function (el) { el.hidden = true; });
    var testo = zona.querySelector('[data-testo-mouse]');
    if (testo) testo.textContent = 'Scegli tutti i file dell\'esame insieme';
  }

  var UTILI = /\.(pdf|jpe?g|png|gif|bmp|webp|tiff?|heic|heif|mp4|m4v|mov|avi|webm|mkv|wmv|mpe?g|ogv|dcm|dicom)$/i;
  var FILMATO = /\.(mp4|m4v|mov|avi|webm|mkv|wmv|mpe?g|ogv|dcm|dicom)$/i;
  var ordineNaturale = new Intl.Collator('it', {numeric: true, sensitivity: 'base'});

  function perche_scartato(nome, percorso) {
    if (/^\./.test(nome) || /^(thumbs\.db|desktop\.ini|dicomdir|icon\r?)$/i.test(nome)) return 'sistema';
    if (/(^|\/)(__MACOSX|\.[^/]+)\//.test(percorso)) return 'sistema';
    if (!UTILI.test(nome)) return 'formato';
    return null;
  }

  // ── Attraversamento della cartella trascinata ─────────────────────────
  function leggiFile(voce) { return new Promise(function (ok, ko) { voce.file(ok, ko); }); }
  function leggiVoci(lettore) { return new Promise(function (ok, ko) { lettore.readEntries(ok, ko); }); }
  async function attraversa(voce, prefisso, esito) {
    if (voce.isFile) {
      var file = await leggiFile(voce);
      esito.push({file: file, percorso: prefisso + file.name});
    } else if (voce.isDirectory) {
      var lettore = voce.createReader();
      var voci;
      // readEntries restituisce al piu' 100 voci per volta: si richiama finche' e' vuoto.
      do {
        voci = await leggiVoci(lettore);
        for (var i = 0; i < voci.length; i++) await attraversa(voci[i], prefisso + voce.name + '/', esito);
      } while (voci.length);
    }
  }
  async function daTrascinamento(dt) {
    // Le voci si prendono SUBITO: dopo il primo await il DataTransfer non vale piu'.
    var voci = [], sciolti = [];
    Array.prototype.forEach.call(dt.items || [], function (item) {
      if (item.kind !== 'file') return;
      var voce = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
      if (voce) voci.push(voce);
      else { var f = item.getAsFile(); if (f) sciolti.push({file: f, percorso: f.name}); }
    });
    if (!voci.length && !sciolti.length) {
      Array.prototype.forEach.call(dt.files || [], function (f) { sciolti.push({file: f, percorso: f.name}); });
    }
    var esito = sciolti.slice();
    for (var i = 0; i < voci.length; i++) await attraversa(voci[i], '', esito);
    return esito;
  }
  function daInput(input) {
    return Array.prototype.map.call(input.files, function (f) {
      return {file: f, percorso: f.webkitRelativePath || f.name};
    });
  }

  // ── Invio di un file ──────────────────────────────────────────────────
  function mb(n) {
    var v = n / 1048576;
    return (v < 10 ? v.toFixed(1) : Math.round(v).toString()).replace('.', ',');
  }
  async function leggiJson(r) { try { return await r.json(); } catch (e) { return {}; } }
  function campi(dati, voce) {
    dati.append('slot', 'cartella');
    dati.append('percorso', voce.percorso);
    if (voce.file.lastModified) dati.append('modificato_il', String(voce.file.lastModified));
  }
  async function semplice(voce, anteprima) {
    var dati = new FormData();
    dati.append('file', voce.file);
    if (anteprima) dati.append('anteprima', anteprima, 'anteprima.jpg');
    campi(dati, voce);
    var r = await fetch(URL_CARICA, {method: 'POST', headers: {'X-CSRFToken': csrf, 'Accept': 'application/json'},
                                     body: dati});
    var j = await leggiJson(r);
    if (r.status === 409 && j.gia_presente) return {gia: true};
    if (!r.ok) throw new Error(j.errore || 'Caricamento non riuscito (errore ' + r.status + ').');
    return j;
  }
  async function impronta(file) {
    var h = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
    return Array.from(new Uint8Array(h)).map(function (b) { return b.toString(16).padStart(2, '0'); }).join('');
  }
  async function aPezzi(voce, anteprima, avanza) {
    if (!(window.crypto && crypto.subtle)) {
      throw new Error('Questo browser non puo\' caricare file grandi su una connessione non sicura (serve https).');
    }
    var file = voce.file;
    var sha = await impronta(file);
    var q = new URLSearchParams({slot: 'cartella', nome: file.name, mime: file.type || '', dimensione: file.size,
                                 impronta: sha});
    var r = await fetch(URL_PEZZI + 'stato/?' + q.toString(), {headers: {'Accept': 'application/json'}});
    var j = await leggiJson(r);
    if (r.status === 409 && j.gia_presente) return {gia: true};
    if (!r.ok) throw new Error(j.errore || 'Caricamento non riuscito.');
    var offset = j.ricevuti || 0, tentativi = 0;
    while (offset < file.size) {
      var dati = new FormData();
      dati.append('impronta', sha);
      dati.append('offset', offset);
      dati.append('pezzo', file.slice(offset, offset + PEZZO));
      try {
        r = await fetch(URL_PEZZI + 'pezzo/', {method: 'POST', headers: {'X-CSRFToken': csrf}, body: dati});
        j = await leggiJson(r);
      } catch (e) {
        if (++tentativi > 6) throw new Error('Connessione interrotta: riprova, il caricamento riparte da dove era.');
        await new Promise(function (ok) { setTimeout(ok, 1500 * tentativi); });
        r = await fetch(URL_PEZZI + 'stato/?' + new URLSearchParams({impronta: sha}).toString());
        offset = (await leggiJson(r)).ricevuti || offset;
        continue;
      }
      if (!r.ok) {
        if (j.ricevuti !== undefined) { offset = j.ricevuti; continue; }
        throw new Error(j.errore || 'Caricamento non riuscito.');
      }
      tentativi = 0;
      offset = j.ricevuti;
      avanza(offset / file.size);
    }
    var fine = new FormData();
    fine.append('impronta', sha);
    fine.append('nome', file.name);
    fine.append('mime', file.type || '');
    if (anteprima) fine.append('anteprima', anteprima, 'anteprima.jpg');
    campi(fine, voce);
    r = await fetch(URL_PEZZI + 'concludi/', {method: 'POST', headers: {'X-CSRFToken': csrf}, body: fine});
    j = await leggiJson(r);
    if (r.status === 409 && j.gia_presente) return {gia: true};
    if (!r.ok) throw new Error(j.errore || 'Caricamento non riuscito.');
    return j;
  }

  // ── Tutta la cartella ─────────────────────────────────────────────────
  function nota(testo, errore) {
    var li = document.createElement('li');
    li.textContent = testo;
    if (errore) li.classList.add('errore');
    note.appendChild(li);
  }
  function elenco(nomi) {
    return nomi.slice(0, 4).join(', ') + (nomi.length > 4 ? ' e altri ' + (nomi.length - 4) : '');
  }

  async function caricaTutto(voci) {
    if (occupato || !voci.length) return;
    occupato = true;
    zona.classList.add('in-corso');
    statoEl.textContent = '';
    note.innerHTML = '';
    var sistema = [], formati = [], daCaricare = [];
    voci.forEach(function (v) {
      var motivo = perche_scartato(v.file.name, v.percorso);
      if (motivo === 'sistema') sistema.push(v.file.name);
      else if (motivo === 'formato') formati.push(v.file.name);
      else daCaricare.push(v);
    });
    daCaricare.sort(function (a, b) { return ordineNaturale.compare(a.percorso, b.percorso); });
    pannello.hidden = false;
    var totale = daCaricare.length, fatti = 0, gia = 0, errori = [];
    function aggiorna(frazione) {
      conteggio.textContent = fatti + ' di ' + totale + ' file caricati' + (gia ? ' (' + gia + ' c\'erano gia\')' : '');
      barra.style.width = (totale ? Math.round(((fatti + (frazione || 0)) / totale) * 100) : 100) + '%';
    }
    aggiorna(0);
    if (formati.length) nota(formati.length + ' file ignorati perche\' non servono (' + elenco(formati) + ').');
    if (sistema.length) nota(sistema.length + ' file di sistema ignorati (' + elenco(sistema) + ').');
    for (var i = 0; i < daCaricare.length; i++) {
      var voce = daCaricare[i], file = voce.file;
      corrente.textContent = file.name;
      try {
        if (MAX_CLIP && FILMATO.test(file.name) && file.size > MAX_CLIP) {
          throw new Error('il filmato pesa ' + mb(file.size) + ' MB, il limite e\' ' + mb(MAX_CLIP) +
                          ' MB: esportane uno piu\' breve (massimo 10 secondi) o in MP4.');
        }
        if (file.size > MAX_PEZZI) throw new Error('pesa ' + mb(file.size) + ' MB, il limite e\' ' + mb(MAX_PEZZI) + ' MB.');
        var anteprima = window.ConsultiAnteprime ?
          await window.ConsultiAnteprime.genera(file).catch(function () { return null; }) : null;
        var grande = FILMATO.test(file.name) || file.size > MAX_SEMPLICE;
        var esito = grande ? await aPezzi(voce, anteprima, aggiorna) : await semplice(voce, anteprima);
        if (esito.gia) gia++;
        fatti++;
      } catch (e) {
        fatti++;
        errori.push(file.name + ': ' + e.message);
      }
      aggiorna(0);
    }
    corrente.textContent = '';
    if (gia) nota(gia + ' file c\'erano gia\' e non sono stati ricaricati.');
    errori.forEach(function (e) { nota(e, true); });
    var arrivati = totale - errori.length;
    if (!arrivati) {
      statoEl.textContent = totale ? 'Nessun file e\' stato caricato: guarda i motivi qui sopra.' :
        'Nella cartella non c\'e\' nessun file dell\'esame (PDF, filmati, immagini).';
      statoEl.classList.add('errore');
      zona.classList.remove('in-corso');
      occupato = false;
      return;
    }
    statoEl.textContent = 'Caricati. Ora li smisto nelle righe…';
    try {
      await fetch(URL_AVVIA, {method: 'POST', headers: {'X-CSRFToken': csrf, 'Accept': 'application/json'}});
    } catch (e) { /* la pagina ricaricata dira' lo stato */ }
    if (errori.length) {
      statoEl.textContent = 'Alcuni file non sono arrivati (vedi sopra). Gli altri li sto smistando: ricarica la pagina tra poco.';
      statoEl.classList.add('errore');
      occupato = false;
      zona.classList.remove('in-corso');
      setTimeout(function () { location.reload(); }, 6000);
      return;
    }
    location.reload();
  }

  // ── Eventi ────────────────────────────────────────────────────────────
  zona.querySelectorAll('input[type=file]').forEach(function (input) {
    input.addEventListener('change', function () {
      var voci = daInput(input);
      input.value = '';
      caricaTutto(voci);
    });
  });
  ['dragenter', 'dragover'].forEach(function (ev) {
    area.addEventListener(ev, function (e) {
      if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types, 'Files') < 0) return;
      e.preventDefault();
      area.classList.add('trascina');
    });
  });
  ['dragleave', 'drop'].forEach(function (ev) {
    area.addEventListener(ev, function () { area.classList.remove('trascina'); });
  });
  area.addEventListener('drop', function (e) {
    if (!e.dataTransfer || !e.dataTransfer.files.length) return;
    e.preventDefault();
    daTrascinamento(e.dataTransfer).then(caricaTutto, function () {
      statoEl.textContent = 'Non riesco a leggere la cartella: prova con «Scegli i file».';
      statoEl.classList.add('errore');
    });
  });
  // Uscire mentre si carica perde i file non ancora partiti: lo si chiede.
  window.addEventListener('beforeunload', function (e) {
    if (occupato && statoEl.textContent.indexOf('smisto') < 0) { e.preventDefault(); e.returnValue = ''; }
  });
})();
