/* ═══════════════════════════════════════════════════════════════════════
   dettatura.js — dettatura vocale nei campi di testo del portale.

   Strada ibrida (decisione di Andre, 12/09/2026):
   1. il MICROFONO e' il riconoscimento vocale del browser
      (SpeechRecognition / webkitSpeechRecognition, lingua it-IT): gratis, e
      l'audio non esce dal computer del collega — a noi non arriva nulla;
   2. «Ripulisci» manda SOLO il testo a consulti:ripulisci, che lo fa
      riscrivere dall'AI nella forma (punteggiatura, sigle, unita' di misura)
      senza toccare il contenuto clinico. Si torna indietro con «Annulla
      ripulitura»: l'ultima parola e' di chi ha scritto.

   Dove l'API del riconoscimento non c'e' (Firefox) il pulsante del microfono
   NON compare e al suo posto si legge l'aiuto: si detta con gli strumenti del
   sistema operativo (su iPhone e iPad il microfono della tastiera). Su iOS il
   riconoscimento parte solo da un gesto dell'utente: qui parte dal clic sul
   pulsante, che e' esattamente un gesto.

   Il markup lo fa templates/_campo_dettatura.html: ogni campo ha un
   contenitore [data-dettatura] con data-campo (l'id del campo) e, quando la
   bozza esiste gia', data-caso (il pk della richiesta).
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var Riconoscimento = window.SpeechRecognition || window.webkitSpeechRecognition;
  var PUNTEGGIATURA = '.,;:!?)';
  var MAX_RIAVVII = 60;          // l'iPhone chiude l'ascolto a ogni pausa

  function csrf(dentro) {
    var form = dentro && dentro.closest ? dentro.closest('form') : null;
    var campo = (form || document).querySelector('[name=csrfmiddlewaretoken]');
    return campo ? campo.value : '';
  }

  /* Il testo dettato entra nel punto in cui sta il cursore e non cancella
     niente: se c'e' una selezione, la sostituisce (come farebbe la tastiera). */
  function inserisci(campo, frammento) {
    if (!frammento) { return; }
    var inizio = typeof campo.selectionStart === 'number' ? campo.selectionStart : campo.value.length;
    var fine = typeof campo.selectionEnd === 'number' ? campo.selectionEnd : campo.value.length;
    var prima = campo.value.slice(0, inizio);
    var dopo = campo.value.slice(fine);
    var pezzo = frammento;
    if (prima && !/\s$/.test(prima) && PUNTEGGIATURA.indexOf(pezzo.charAt(0)) === -1) { pezzo = ' ' + pezzo; }
    campo.value = prima + pezzo + dopo;
    var cursore = (prima + pezzo).length;
    campo.setSelectionRange(cursore, cursore);
    campo.dispatchEvent(new Event('input', {bubbles: true}));
  }

  function avvia(contenitore) {
    var campo = document.getElementById(contenitore.getAttribute('data-campo'));
    if (!campo) { return; }
    var micro = contenitore.querySelector('[data-microfono]');
    var btnRipulisci = contenitore.querySelector('[data-ripulisci]');
    var btnAnnulla = contenitore.querySelector('[data-annulla]');
    var stato = contenitore.querySelector('[data-stato]');
    var aiuto = contenitore.querySelector('[data-aiuto]');
    var parziale = contenitore.querySelector('[data-parziale]');
    var prima = null;        // il testo prima della ripulitura, per annullare

    function dillo(testo, tono) {
      stato.textContent = testo || '';
      stato.className = 'dettatura-stato' + (tono ? ' ' + tono : '');
    }

    // ── 1. Microfono ──────────────────────────────────────────────────────
    if (micro && Riconoscimento) {
      var reco = new Riconoscimento();
      reco.lang = 'it-IT';
      reco.continuous = true;
      reco.interimResults = true;
      var ascolto = false, riavvii = 0;

      function aspetto() {
        micro.classList.toggle('in-ascolto', ascolto);
        micro.setAttribute('aria-pressed', ascolto ? 'true' : 'false');
        micro.querySelector('.etichetta').textContent = ascolto ? 'Ferma' : 'Detta';
        micro.querySelector('i').className = ascolto ? 'bi bi-stop-fill' : 'bi bi-mic';
        if (!ascolto) { parziale.textContent = ''; }
      }

      reco.onresult = function (e) {
        var incorso = '';
        for (var i = e.resultIndex; i < e.results.length; i++) {
          var testo = e.results[i][0].transcript;
          if (e.results[i].isFinal) { inserisci(campo, testo.trim()); } else { incorso += testo; }
        }
        parziale.textContent = incorso;
      };
      reco.onerror = function (e) {
        if (e.error === 'aborted' || e.error === 'no-speech') { return; }
        ascolto = false;
        aspetto();
        if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
          dillo('Il browser non da\' il permesso di usare il microfono: controlla le impostazioni del sito.',
                'errore');
        } else if (e.error === 'network') {
          dillo('Il riconoscimento vocale non raggiunge la rete: riprova.', 'errore');
        } else {
          dillo('Il riconoscimento vocale si e\' fermato (' + e.error + '): riprova.', 'errore');
        }
      };
      reco.onend = function () {
        // Su iPhone l'ascolto finisce a ogni pausa: se il collega non ha
        // premuto «Ferma», riparte da solo.
        if (ascolto && riavvii < MAX_RIAVVII) {
          riavvii++;
          try { reco.start(); return; } catch (err) { /* gia' avviato */ }
        }
        ascolto = false;
        aspetto();
      };
      micro.addEventListener('click', function () {
        if (ascolto) { ascolto = false; reco.stop(); aspetto(); return; }
        campo.focus();
        try {
          riavvii = 0;
          reco.start();
          ascolto = true;
          dillo('Sto ascoltando: parla, il testo entra dove sta il cursore.', 'ascolto');
          aspetto();
        } catch (err) {
          dillo('Non riesco ad accendere il microfono: riprova.', 'errore');
        }
      });
      micro.hidden = false;
    } else if (aiuto) {
      // Firefox e i browser senza l'API: nessun pulsante, ma si detta comunque.
      aiuto.hidden = false;
    }

    // ── 2. «Ripulisci» con l'AI ───────────────────────────────────────────
    if (btnRipulisci) {
      btnRipulisci.hidden = false;
      btnRipulisci.addEventListener('click', function () {
        var testo = campo.value.trim();
        if (!testo) { dillo('Non c\'e\' niente da ripulire: detta o scrivi qualcosa.', 'errore'); return; }
        btnRipulisci.disabled = true;
        dillo('Sto ripulendo il testo...', 'attesa');
        var corpo = {testo: testo};
        var caso = contenitore.getAttribute('data-caso');
        if (caso) { corpo.caso = caso; }
        fetch(btnRipulisci.getAttribute('data-url'), {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf(contenitore)},
          body: JSON.stringify(corpo)
        }).then(function (r) {
          return r.json().then(function (d) { return {ok: r.ok, dati: d}; });
        }).then(function (esito) {
          btnRipulisci.disabled = false;
          if (!esito.ok) {
            dillo(esito.dati.errore || 'La ripulitura non e\' andata a buon fine: il testo resta com\'era.',
                  'errore');
            return;
          }
          prima = campo.value;
          campo.value = esito.dati.testo;
          campo.dispatchEvent(new Event('input', {bubbles: true}));
          // Le correzioni si mostrano, ma tre bastano: su un referto dettato
          // sono dieci e riempirebbero mezzo schermo del telefono. Tutte
          // nel titolo, per chi vuole vederle.
          var correzioni = esito.dati.correzioni || [];
          var elenco = correzioni.slice(0, 3).join(' · ') +
                       (correzioni.length > 3 ? ' · e altre ' + (correzioni.length - 3) : '');
          dillo('Testo ripulito' + (correzioni.length ? ' · ' + elenco : '') +
                '. Rileggilo: la firma e\' tua.', 'fatto');
          stato.title = correzioni.join('\n');
          btnAnnulla.hidden = false;
        }).catch(function () {
          btnRipulisci.disabled = false;
          dillo('La ripulitura non e\' riuscita a partire: il testo resta com\'era.', 'errore');
        });
      });
    }

    // ── 3. «Annulla ripulitura» ───────────────────────────────────────────
    if (btnAnnulla) {
      btnAnnulla.addEventListener('click', function () {
        if (prima === null) { return; }
        campo.value = prima;
        campo.dispatchEvent(new Event('input', {bubbles: true}));
        prima = null;
        btnAnnulla.hidden = true;
        dillo('Ripulitura annullata: e\' tornato il testo che avevi dettato.');
      });
    }
  }

  document.querySelectorAll('[data-dettatura]').forEach(avvia);
})();
