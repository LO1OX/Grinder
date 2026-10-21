// Jarvis Kino Desktop – Brücke zwischen Kino-Webseite und mpv-Player.
//
// - Startet die Seite ein Video, wird es nicht im Browser abgespielt, sondern
//   an mpv übergeben (spielt AV1/HEVC/H.264 direkt, Hardware-Dekodierung).
// - Das <video>-Element der Seite bekommt währenddessen die Werte von mpv
//   (currentTime, duration, paused …) und passende Ereignisse. So speichert
//   die Seite den Fortschritt ("Weiterschauen") mit ihrer eigenen Logik.
// - Kino-JSON-Antworten (Serien, Staffeln, Folgen) werden an die App gereicht,
//   damit der Player eine Folgen-Liste anzeigen kann.
(function () {
  'use strict';
  if (window.__jarvisKino) return;

  var VIDEO_RE = /\/api\/video\/(?:datei|stream|status|abspielbar|vorbereiten)\/([^\/?#]+)/;
  var FORTSCHRITT_RE = /\/api\/video\/fortschritt/;
  var KINO_JSON_RE = /\/api\/(?:kino|video)\//;
  var MEDIEN_EREIGNISSE = ['abort', 'canplay', 'canplaythrough', 'durationchange', 'emptied', 'ended', 'error',
    'loadeddata', 'loadedmetadata', 'loadstart', 'pause', 'play', 'playing', 'progress', 'ratechange',
    'seeked', 'seeking', 'stalled', 'suspend', 'timeupdate', 'volumechange', 'waiting'];

  var synthetisch = new WeakSet();
  var zustaende = new WeakMap();
  var aktiv = null;
  var letzteId = null;
  var vorlage = null; // zuletzt gemeldetes Fortschritt-Format
  var py = null;
  var warteschlange = [];

  function ruf(name) {
    var args = Array.prototype.slice.call(arguments, 1);
    if (py) { try { py[name].apply(py, args); } catch (e) { /* App weg */ } }
    else warteschlange.push([name, args]);
  }

  function verbinden() {
    if (typeof QWebChannel === 'undefined' || typeof qt === 'undefined' || !qt.webChannelTransport) {
      setTimeout(verbinden, 50);
      return;
    }
    new QWebChannel(qt.webChannelTransport, function (kanal) {
      py = kanal.objects.jarvis;
      warteschlange.splice(0).forEach(function (r) { py[r[0]].apply(py, r[1]); });
    });
  }
  verbinden();

  function absolut(url) {
    try { return new URL(url, document.baseURI).href; } catch (e) { return String(url || ''); }
  }
  function idAus(url) {
    var m = VIDEO_RE.exec(url || '');
    return m ? decodeURIComponent(m[1]) : null;
  }
  function merkeUrl(url) {
    var id = idAus(url);
    if (id) letzteId = id;
  }

  // ---------------------------------------------------------------- Codecs
  // mpv kann alles abspielen. Die Seite soll deshalb nie den Server zum
  // Umwandeln bitten (spart Prozessor auf Jarvis).
  var KANN_ALLES = /hev1|hvc1|hevc|h\.?265|av01|av1|matroska|x-matroska|webm|dts|ac-?3|ec-?3|eac3|truehd|flac|opus|vp9|vp09/i;
  var origCanPlay = HTMLMediaElement.prototype.canPlayType;
  HTMLMediaElement.prototype.canPlayType = function (typ) {
    if (KANN_ALLES.test(String(typ))) return 'probably';
    return origCanPlay.call(this, typ);
  };
  if (window.MediaSource && MediaSource.isTypeSupported) {
    var origMse = MediaSource.isTypeSupported.bind(MediaSource);
    MediaSource.isTypeSupported = function (typ) { return KANN_ALLES.test(String(typ)) || origMse(typ); };
  }
  if (navigator.mediaCapabilities && navigator.mediaCapabilities.decodingInfo) {
    var origInfo = navigator.mediaCapabilities.decodingInfo.bind(navigator.mediaCapabilities);
    navigator.mediaCapabilities.decodingInfo = function (cfg) {
      var typ = cfg && cfg.video && cfg.video.contentType;
      if (typ && KANN_ALLES.test(typ)) return Promise.resolve({ supported: true, smooth: true, powerEfficient: true });
      return origInfo(cfg);
    };
  }

  // ---------------------------------------------------------- Netzwerk
  function kopfzeilen(h) {
    var aus = {};
    if (!h) return aus;
    if (typeof Headers !== 'undefined' && h instanceof Headers) h.forEach(function (v, k) { aus[k] = v; });
    else if (Array.isArray(h)) h.forEach(function (p) { aus[p[0]] = p[1]; });
    else Object.keys(h).forEach(function (k) { aus[k] = h[k]; });
    return aus;
  }

  function aktuellerZustand() {
    return aktiv ? zustaende.get(aktiv) : null;
  }

  function vorlageMerken(url, methode, kopf, body) {
    var text = null;
    if (typeof body === 'string') text = body;
    else if (typeof URLSearchParams !== 'undefined' && body instanceof URLSearchParams) text = body.toString();
    else if (typeof Blob !== 'undefined' && body instanceof Blob) {
      body.text().then(function (t) { vorlageMerken(url, methode, kopf, t); });
      return;
    }
    var st = aktuellerZustand();
    if (text === null || !st || !st.id || !(st.pos > 5)) return;
    var art = /^\s*\{/.test(text) ? 'json' : 'form';
    var obj;
    try { obj = art === 'json' ? JSON.parse(text) : Object.fromEntries(new URLSearchParams(text)); } catch (e) { return; }
    var felder = { faktor: 1 };
    Object.keys(obj).forEach(function (k) {
      var v = obj[k];
      if (typeof v === 'boolean' || v === null || typeof v === 'object') return;
      var n = Number(v);
      if (String(v) === st.id) felder.id = k;
      else if (v === '' || isNaN(n)) return;
      else if (!felder.pos && Math.abs(n - st.pos) < 3) felder.pos = k;
      else if (!felder.pos && Math.abs(n / 1000 - st.pos) < 3) { felder.pos = k; felder.faktor = 1000; }
      else if (st.dauer > 0 && Math.abs(n / felder.faktor - st.dauer) < 3) felder.dauer = k;
    });
    var abs = absolut(url);
    var idInUrl = abs.indexOf(encodeURIComponent(st.id)) >= 0;
    if (!felder.pos || (!felder.id && !idInUrl)) return;
    var neu = JSON.stringify({ url: abs, felder: felder });
    if (vorlage === neu) return;
    vorlage = neu;
    ruf('vorlage', JSON.stringify({ url: abs, methode: methode === 'BEACON' ? 'POST' : methode, kopf: kopfzeilen(kopf),
      art: art, obj: obj, felder: felder, id_in_url: idInUrl, alte_id: st.id }));
  }

  var origFetch = window.fetch;
  window.fetch = function (eingabe, init) {
    var url = absolut(typeof eingabe === 'string' ? eingabe : (eingabe && eingabe.url) || String(eingabe));
    var methode = String((init && init.method) || (eingabe && eingabe.method) || 'GET').toUpperCase();
    try {
      merkeUrl(url);
      if (FORTSCHRITT_RE.test(url) && methode !== 'GET' && init) vorlageMerken(url, methode, init.headers, init.body);
    } catch (e) { /* nie die Seite stören */ }
    var p = origFetch.apply(this, arguments);
    if (KINO_JSON_RE.test(url) && methode === 'GET') {
      p.then(function (r) {
        var ct = (r.headers.get('content-type') || '');
        if (r.ok && ct.indexOf('json') >= 0) {
          r.clone().text().then(function (t) { if (t.length < 4e6) ruf('kinodaten', absolut(url), t); }).catch(function () {});
        }
      }).catch(function () {});
    }
    return p;
  };

  var origOpen = XMLHttpRequest.prototype.open;
  var origSend = XMLHttpRequest.prototype.send;
  var origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.open = function (methode, url) {
    this.__jk = { methode: String(methode || 'GET').toUpperCase(), url: absolut(url), kopf: {} };
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
    if (this.__jk) this.__jk.kopf[k] = v;
    return origSetHeader.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function (body) {
    var info = this.__jk;
    if (info) {
      try {
        merkeUrl(info.url);
        if (FORTSCHRITT_RE.test(info.url) && info.methode !== 'GET') vorlageMerken(info.url, info.methode, info.kopf, body);
        if (KINO_JSON_RE.test(info.url) && info.methode === 'GET') {
          var xhr = this;
          this.addEventListener('load', function () {
            try {
              var ct = xhr.getResponseHeader('content-type') || '';
              if (xhr.status === 200 && ct.indexOf('json') >= 0 && (xhr.responseType === '' || xhr.responseType === 'text')) {
                ruf('kinodaten', absolut(info.url), xhr.responseText);
              }
            } catch (e) { /* egal */ }
          });
        }
      } catch (e) { /* nie die Seite stören */ }
    }
    return origSend.apply(this, arguments);
  };

  if (navigator.sendBeacon) {
    var origBeacon = navigator.sendBeacon.bind(navigator);
    navigator.sendBeacon = function (url, daten) {
      try { if (FORTSCHRITT_RE.test(absolut(url))) vorlageMerken(url, 'BEACON', null, daten); } catch (e) { /* egal */ }
      return origBeacon(url, daten);
    };
  }

  // ------------------------------------------------------- Video-Element
  var P = HTMLMediaElement.prototype;
  var origPlay = P.play;
  var origPause = P.pause;
  var origLoad = P.load;
  var echt = {
    zeit: Object.getOwnPropertyDescriptor(P, 'currentTime'),
    quelle: Object.getOwnPropertyDescriptor(P, 'currentSrc'),
    src: Object.getOwnPropertyDescriptor(P, 'src')
  };

  function feuern(el, typ) {
    var e = new Event(typ);
    synthetisch.add(e);
    try { el.dispatchEvent(e); } catch (x) { /* egal */ }
  }

  function aktuelleQuelle(el) {
    var st = zustaende.get(el);
    var attr = Element.prototype.getAttribute.call(el, 'src');
    if (attr) return absolut(attr);
    if (!st) {
      var q = echt.quelle.get.call(el);
      if (q) return q;
    }
    var s = el.querySelector('source[src]');
    return s ? absolut(s.getAttribute('src')) : '';
  }

  function ueberschreiben(el) {
    var z = function () { return zustaende.get(el); };
    Object.defineProperties(el, {
      currentTime: {
        configurable: true,
        get: function () { return z().pos; },
        set: function (v) {
          var st = z();
          st.pos = Math.max(0, Number(v) || 0);
          st.gesetzt = true;
          if (st.aktiv) ruf('springen', st.pos);
        }
      },
      duration: { configurable: true, get: function () { return z().dauer > 0 ? z().dauer : NaN; } },
      paused: { configurable: true, get: function () { return !z().aktiv || z().pausiert; } },
      ended: { configurable: true, get: function () { return z().beendet; } },
      readyState: { configurable: true, get: function () { return z().dauer > 0 ? 4 : 0; } },
      currentSrc: { configurable: true, get: function () { return z().quelle; } },
      src: {
        configurable: true,
        get: function () { return echt.src.get.call(el); },
        set: function (v) {
          echt.src.set.call(el, v);
          var st = z();
          st.quelle = absolut(v);
          st.id = idAus(st.quelle) || st.id;
          st.pos = 0; st.dauer = 0; st.beendet = false; st.gesetzt = false;
        }
      }
    });
  }

  function titelVon(el) {
    var kandidaten = [el.getAttribute('title'), el.getAttribute('aria-label'), el.dataset && (el.dataset.titel || el.dataset.title)];
    var h = document.querySelector('[class*="titel"] h1, [class*="titel"] h2, [class*="player"] h1, [class*="player"] h2, h1');
    if (h) kandidaten.push(h.textContent);
    kandidaten.push(document.title);
    for (var i = 0; i < kandidaten.length; i++) {
      var t = (kandidaten[i] || '').trim();
      if (t) return t.slice(0, 200);
    }
    return '';
  }

  function startAusQuelle(q) {
    var m = /[#&?](?:t|start)=(\d+(?:\.\d+)?)/.exec(q || '');
    return m ? Number(m[1]) : 0;
  }

  function uebergeben(el) {
    var quelle = aktuelleQuelle(el);
    var st = zustaende.get(el);
    var istWeb = /^https?:/i.test(quelle);
    var id = idAus(quelle) || (st && st.quelle === quelle ? st.id : null) || (!istWeb ? letzteId : null);
    if (!id && !istWeb) return false; // unbekannte Quelle: im Browser lassen
    var start;
    if (st && st.quelle === quelle) {
      start = st.pos;
    } else if (st) {
      start = st.gesetzt ? st.pos : startAusQuelle(quelle);
      st.quelle = quelle; st.id = id; st.dauer = 0;
    } else {
      var echteZeit = 0;
      try { echteZeit = echt.zeit.get.call(el) || 0; } catch (e) { /* egal */ }
      start = echteZeit > 1 ? echteZeit : startAusQuelle(quelle);
      st = { quelle: quelle, id: id, pos: start, dauer: 0, pausiert: false, beendet: false, aktiv: false, gesetzt: false };
      zustaende.set(el, st);
      ueberschreiben(el);
    }
    st.pos = start; st.beendet = false; st.pausiert = false; st.aktiv = true; st.gesetzt = false;
    aktiv = el;
    try { origPause.call(el); } catch (e) { /* egal */ }
    if (!/^blob:/i.test(quelle)) {
      // Browser soll die Datei nicht parallel laden.
      try { el.preload = 'none'; origLoad.call(el); } catch (e) { /* egal */ }
    }
    ruf('abspielen', JSON.stringify({ id: id, quelle: quelle, start: start, titel: titelVon(el), seite: location.href }));
    feuern(el, 'play');
    return true;
  }

  P.play = function () {
    if (this instanceof HTMLVideoElement) {
      var st = zustaende.get(this);
      if (st && st.aktiv) return Promise.resolve();
      try { if (uebergeben(this)) return Promise.resolve(); } catch (e) { ruf('log', 'Übergabe fehlgeschlagen: ' + e); }
    }
    return origPlay.apply(this, arguments);
  };

  // Ereignisse des echten (stummen) Elements vor der Seite verbergen und
  // Autoplay-Videos ebenfalls an mpv übergeben.
  MEDIEN_EREIGNISSE.forEach(function (typ) {
    window.addEventListener(typ, function (e) {
      if (synthetisch.has(e)) return;
      var el = e.target;
      if (!(el instanceof HTMLMediaElement)) return;
      if (typ === 'play' && el instanceof HTMLVideoElement && !(zustaende.get(el) || {}).aktiv) {
        try { if (uebergeben(el)) { e.stopImmediatePropagation(); return; } } catch (x) { /* egal */ }
      }
      if (zustaende.has(el)) e.stopImmediatePropagation();
    }, true);
  });

  function schliessenVersuchen(el) {
    try { if (document.fullscreenElement) document.exitFullscreen(); } catch (e) { /* egal */ }
    setTimeout(function () {
      if (!el.isConnected || !el.getClientRects().length) return;
      var opts = { key: 'Escape', code: 'Escape', keyCode: 27, which: 27, bubbles: true, cancelable: true };
      var ziel = document.activeElement || document.body;
      ziel.dispatchEvent(new KeyboardEvent('keydown', opts));
      ziel.dispatchEvent(new KeyboardEvent('keyup', opts));
    }, 200);
  }

  // ---------------------------------------------------- Schnittstelle App
  window.__jarvisKino = {
    stand: function (pos, dauer, pausiert) {
      var st = aktuellerZustand();
      if (!st) return;
      var alteDauer = st.dauer;
      st.pos = pos;
      if (dauer > 0) st.dauer = dauer;
      if (!alteDauer && st.dauer) { feuern(aktiv, 'loadedmetadata'); feuern(aktiv, 'durationchange'); feuern(aktiv, 'canplay'); }
      if (pausiert !== st.pausiert) {
        st.pausiert = pausiert;
        feuern(aktiv, pausiert ? 'pause' : 'play');
        if (!pausiert) feuern(aktiv, 'playing');
      }
      feuern(aktiv, 'timeupdate');
    },
    ende: function (pos, dauer, bisZumSchluss, mitFolgen) {
      var el = aktiv;
      var st = aktuellerZustand();
      aktiv = null;
      if (!st) return;
      st.pos = pos; if (dauer > 0) st.dauer = dauer;
      st.aktiv = false; st.pausiert = true;
      feuern(el, 'timeupdate');
      feuern(el, 'pause');
      if (bisZumSchluss && !mitFolgen) {
        st.beendet = true;
        feuern(el, 'ended');
      } else {
        schliessenVersuchen(el);
      }
    },
    aktiv: function () { return !!aktiv; }
  };
})();
