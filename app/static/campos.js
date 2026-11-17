// Campos de data/hora: no celular (ponteiro grosso) mantém o seletor nativo;
// no desktop (ponteiro fino) troca por texto com máscara dd/mm/aaaa e HH:MM.
// O servidor aceita os dois formatos (ISO do nativo e pt-BR do texto).
(function () {
  "use strict";

  var CONFIG = {
    data: { placeholder: "dd/mm/aaaa", digitos: 8, cortes: [2, 4], sep: "/" },
    hora: { placeholder: "HH:MM", digitos: 4, cortes: [2], sep: ":" }
  };

  function isoParaBr(tipo, valor) {
    if (tipo === "data") {
      var d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(valor);
      return d ? d[3] + "/" + d[2] + "/" + d[1] : valor;
    }
    var h = /^(\d{2}:\d{2})(:\d{2})?$/.exec(valor);  // descarta segundos
    return h ? h[1] : valor;
  }

  // Reconstrói o texto a partir só dos dígitos, inserindo o separador antes
  // das posições de corte: "17112026" -> "17/11/2026", "0915" -> "09:15"
  function mascarar(cfg, texto) {
    var digitos = texto.replace(/\D/g, "").slice(0, cfg.digitos);
    var saida = "";
    for (var i = 0; i < digitos.length; i++) {
      if (cfg.cortes.indexOf(i) !== -1) saida += cfg.sep;
      saida += digitos[i];
    }
    return saida;
  }

  function converter(input) {
    var tipo = input.getAttribute("data-campo");
    var cfg = CONFIG[tipo];
    if (!cfg || input.hasAttribute("data-convertido")) return;
    // getAttribute primeiro: o input nativo descarta valores fora de ISO
    // (ex.: texto digitado que voltou do servidor com erro)
    var valor = input.getAttribute("value") || input.value || "";
    input.type = "text";
    input.inputMode = "numeric";
    input.placeholder = cfg.placeholder;
    input.maxLength = cfg.digitos + cfg.cortes.length;
    input.autocomplete = "off";
    input.value = isoParaBr(tipo, valor);
    input.setAttribute("data-convertido", "");
    input.addEventListener("input", function () {
      // Data ISO colada (2026-11-17) vira BR antes da máscara, que leria só os dígitos
      var bruto = input.value.trim();
      if (tipo === "data" && /^\d{4}-\d{2}-\d{2}$/.test(bruto)) bruto = isoParaBr(tipo, bruto);
      input.value = mascarar(cfg, bruto);
    });
  }

  function aplicar(raiz) {
    if (!window.matchMedia || !window.matchMedia("(pointer: fine)").matches) return;
    var alvos = raiz.querySelectorAll ? raiz.querySelectorAll("input[data-campo]") : [];
    for (var i = 0; i < alvos.length; i++) converter(alvos[i]);
  }

  // "A informar" / "A combinar": marcada a opção, o campo fica desabilitado
  // (não é enviado) e deixa de ser obrigatório; vale em qualquer ponteiro
  function ligarSentinelas(raiz) {
    var caixas = raiz.querySelectorAll ? raiz.querySelectorAll("input[data-sentinela-de]") : [];
    for (var i = 0; i < caixas.length; i++) {
      (function (caixa) {
        if (caixa.hasAttribute("data-ligada")) return;
        caixa.setAttribute("data-ligada", "");
        var form = caixa.form || document;
        var alvos = form.querySelectorAll('[name="' + caixa.getAttribute("data-sentinela-de") + '"]');
        function sincronizar() {
          for (var j = 0; j < alvos.length; j++) {
            var alvo = alvos[j];
            if (alvo.required) alvo.setAttribute("data-obrigatorio", "");
            alvo.disabled = caixa.checked;
            alvo.required = !caixa.checked && alvo.hasAttribute("data-obrigatorio");
          }
        }
        caixa.addEventListener("change", sincronizar);
        sincronizar();
      })(caixas[i]);
    }
  }

  function iniciar(raiz) { aplicar(raiz); ligarSentinelas(raiz); }

  // htmx.onLoad roda no carregamento inicial e em cada fragmento trocado
  if (window.htmx) {
    window.htmx.onLoad(iniciar);
  } else {
    document.addEventListener("DOMContentLoaded", function () { iniciar(document); });
  }
})();
