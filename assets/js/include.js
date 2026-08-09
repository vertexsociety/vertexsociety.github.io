(function () {
  function markActive() {
    var here = location.pathname.replace(/index\.html$/, '') || '/';
    var links = document.querySelectorAll('.site-nav a');
    for (var i = 0; i < links.length; i++) {
      var p = links[i].pathname.replace(/index\.html$/, '') || '/';
      if (p === here) links[i].classList.add('active');
    }
  }
  var nodes = document.querySelectorAll('[data-include]');
  var pending = nodes.length;
  if (!pending) { markActive(); return; }
  Array.prototype.forEach.call(nodes, function (el) {
    fetch(el.getAttribute('data-include'))
      .then(function (r) { return r.text(); })
      .then(function (html) { el.insertAdjacentHTML('afterend', html); })
      .catch(function () {})
      .then(function () { el.remove(); if (--pending === 0) markActive(); });
  });
})();