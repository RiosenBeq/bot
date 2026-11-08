/* Görünüm: açık ya da koyu tema. Bütün sayfalarda <head>'de, defer'siz
   yüklenir: sayfa çizilmeden önce <html data-tema="..."> yazılır, yanlış
   renkte bir an yanıp sönme olmaz. Renkler pano.css ve stil.css'te
   (:root ve :root[data-tema="koyu"]).

   Seçim bu cihazda saklanır (localStorage "tema": "acik" | "koyu"); seçim
   yoksa ("Sistem") cihazın açık / koyu ayarı izlenir ve ayar değişince sayfa
   da değişir. Panoda Sistem ekranındaki Görünüm satırı window.panoTema'yı
   kullanır. Betik çalışmazsa sayfa açık temada kalır. */
"use strict";

(function () {
  const ANAHTAR = "tema";
  const RENK = { acik: "#ffffff", koyu: "#14161c" }; // tarayıcı çubuğu (theme-color)
  const sistem = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  let bellek = null; // depolama yazılamazsa seçim bu sayfada burada durur

  function secim() {
    if (bellek) return bellek;
    try {
      const deger = window.localStorage.getItem(ANAHTAR);
      return deger === "acik" || deger === "koyu" ? deger : "sistem";
    } catch (e) {
      return "sistem"; // gizli pencere ya da kapalı depolama
    }
  }

  function uygula() {
    const s = secim();
    const tema = s === "sistem" ? (sistem && sistem.matches ? "koyu" : "acik") : s;
    document.documentElement.setAttribute("data-tema", tema);
    const renk = document.querySelector('meta[name="theme-color"]');
    if (renk) renk.setAttribute("content", RENK[tema]);
  }

  function sec(deger) {
    const yeni = deger === "acik" || deger === "koyu" ? deger : "sistem";
    bellek = null;
    try {
      if (yeni === "sistem") window.localStorage.removeItem(ANAHTAR);
      else window.localStorage.setItem(ANAHTAR, yeni);
    } catch (e) {
      bellek = yeni; // saklanamıyor: yalnız bu sayfada geçerli
    }
    uygula();
  }

  uygula();
  if (sistem) {
    if (sistem.addEventListener) sistem.addEventListener("change", uygula);
    else if (sistem.addListener) sistem.addListener(uygula);
  }
  // Başka sekmede değişince bu sekme de değişir
  window.addEventListener("storage", function (olay) {
    if (olay.key === ANAHTAR || olay.key === null) uygula();
  });

  window.panoTema = { secim: secim, sec: sec };
})();
