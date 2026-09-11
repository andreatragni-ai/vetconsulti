/* ═══════════════════════════════════════════════════════════════════════
   anteprime.js — la miniatura JPEG di un file, fatta nel browser prima di
   caricarlo (window.ConsultiAnteprime.genera(file) -> Promise<Blob|null>).

   - Immagine: ridotta a 800 px sul lato lungo.
   - Filmato che il browser sa decodificare (MP4/MOV in H.264, WebM): un
     fotogramma verso meta' durata con <video> + <canvas>. Si guardano tre
     fotogrammi (50, 30, 70 %) e si tiene quello di meta', a meno che un
     altro abbia molto piu' colore: un filmato color Doppler in diastole puo'
     avere poco colore proprio a meta', e lo smistamento decide B-mode o
     color dai pixel della miniatura (eco/smistamento/colore.py, stesse
     soglie qui sotto).
   - Tutto il resto (AVI, WMV, DICOM, PDF) o un filmato che non si apre
     entro 12 secondi: null. Il file parte lo stesso; la miniatura, se c'e'
     ffmpeg, la fa il server.
   Il server la rifa' comunque con Pillow (consulti/anteprime.py): qui conta
   solo non mandare fotogrammi neri o illeggibili.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var LATO = 800;
  var QUALITA = 0.82;
  var ATTESA_MS = 12000;

  function eImmagine(file) {
    return /^image\/(jpeg|png|gif|bmp|webp)$/.test(file.type) || /\.(jpe?g|png|gif|bmp|webp)$/i.test(file.name);
  }
  function eVideo(file) {
    return /^video\//.test(file.type) || /\.(mp4|m4v|mov|webm|ogv|avi|wmv|mkv|mpe?g)$/i.test(file.name);
  }

  function disegna(sorgente, larghezza, altezza, lato) {
    var scala = Math.min(1, lato / Math.max(larghezza, altezza));
    var tela = document.createElement('canvas');
    tela.width = Math.max(1, Math.round(larghezza * scala));
    tela.height = Math.max(1, Math.round(altezza * scala));
    tela.getContext('2d').drawImage(sorgente, 0, 0, tela.width, tela.height);
    return tela;
  }

  // Pixel saturi non verdi nella fascia centrale: come colore.py (S > 0,45,
  // V > 0,25, tinta fuori da 70-170 gradi, via il 6 % in alto e il 15 % in basso).
  // Ritorna anche la luminosita' massima, per scartare i fotogrammi neri.
  function misura(tela) {
    var piccola = disegna(tela, tela.width, tela.height, 200);
    var ctx = piccola.getContext('2d');
    var y0 = Math.floor(piccola.height * 0.06), y1 = Math.floor(piccola.height * 0.85);
    var d = ctx.getImageData(0, y0, piccola.width, Math.max(1, y1 - y0)).data;
    var colorati = 0, massimo = 0;
    for (var i = 0; i < d.length; i += 4) {
      var r = d[i] / 255, g = d[i + 1] / 255, b = d[i + 2] / 255;
      var mx = Math.max(r, g, b), mn = Math.min(r, g, b);
      if (mx * 255 > massimo) massimo = mx * 255;
      if (mx < 0.25 || mx === 0 || (mx - mn) / mx < 0.45) continue;
      var h;
      if (mx === r) h = 60 * (((g - b) / (mx - mn)) % 6);
      else if (mx === g) h = 60 * ((b - r) / (mx - mn) + 2);
      else h = 60 * ((r - g) / (mx - mn) + 4);
      if (h < 0) h += 360;
      if (h >= 70 && h <= 170) continue;
      colorati++;
    }
    return {colorati: colorati, massimo: massimo};
  }

  function aBlob(tela) {
    return new Promise(function (ok) { tela.toBlob(function (b) { ok(b); }, 'image/jpeg', QUALITA); });
  }

  function daImmagine(file) {
    return new Promise(function (ok) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      var chiuso = false;
      function fine(valore) { if (chiuso) return; chiuso = true; URL.revokeObjectURL(url); ok(valore); }
      img.onload = function () {
        try { aBlob(disegna(img, img.naturalWidth, img.naturalHeight, LATO)).then(fine); } catch (e) { fine(null); }
      };
      img.onerror = function () { fine(null); };
      setTimeout(function () { fine(null); }, ATTESA_MS);
      img.src = url;
    });
  }

  function vaiA(video, tempo) {
    return new Promise(function (ok, ko) {
      var t = setTimeout(function () { ko(new Error('seek')); }, 4000);
      video.onseeked = function () { clearTimeout(t); ok(); };
      video.currentTime = tempo;
    });
  }

  function daVideo(file) {
    return new Promise(function (ok) {
      var video = document.createElement('video');
      video.muted = true;
      video.playsInline = true;
      video.preload = 'auto';
      var url = URL.createObjectURL(file);
      var chiuso = false;
      function fine(valore) {
        if (chiuso) return;
        chiuso = true;
        clearTimeout(timer);
        URL.revokeObjectURL(url);
        video.removeAttribute('src');
        try { video.load(); } catch (e) { /* niente */ }
        ok(valore);
      }
      var timer = setTimeout(function () { fine(null); }, ATTESA_MS);
      video.onerror = function () { fine(null); };
      video.onloadeddata = async function () {
        video.onloadeddata = null;
        try {
          var durata = isFinite(video.duration) && video.duration > 0 ? video.duration : 0;
          var w = video.videoWidth, h = video.videoHeight;
          if (!w || !h) { fine(null); return; }
          var migliore = null, colori = -1;
          var frazioni = durata ? [0.5, 0.3, 0.7] : [0];
          for (var i = 0; i < frazioni.length; i++) {
            if (durata) await vaiA(video, durata * frazioni[i]);
            var tela = disegna(video, w, h, LATO);
            var m = misura(tela);
            if (m.massimo < 30) continue;                 // fotogramma nero: non vale
            if (migliore === null || m.colorati > Math.max(colori * 1.5, colori + 40)) {
              migliore = tela;
              colori = m.colorati;
            }
          }
          fine(migliore ? await aBlob(migliore) : null);
        } catch (e) {
          fine(null);
        }
      };
      video.src = url;
    });
  }

  window.ConsultiAnteprime = {
    genera: function (file) {
      try {
        if (eImmagine(file)) return daImmagine(file);
        if (eVideo(file)) return daVideo(file);
      } catch (e) { /* browser senza canvas o video */ }
      return Promise.resolve(null);
    }
  };
})();
