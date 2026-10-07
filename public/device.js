/* Náhodné ID prohlížeče (jen v tomto zařízení, nic osobního) + záznam otevření stránky pro Logy. */
(function () {
  var d = "";
  try {
    d = localStorage.getItem("did") || "";
    if (!d) { d = Math.random().toString(36).slice(2, 10) + Math.random().toString(36).slice(2, 6); localStorage.setItem("did", d); }
  } catch (e) { /* bez úložiště se zařízení nerozliší, vše ostatní funguje */ }
  window.DID = d;
  try { new Image().src = "/ping.gif?e=view&d=" + encodeURIComponent(d) + "&p=" + encodeURIComponent(location.pathname) + "&r=" + Date.now().toString(36); } catch (e) {}
})();
