// Painel de configurações: marca os campos alterados e mostra no botão quantos
// valores serão gravados. Sem JS o formulário funciona igual, só sem a contagem.
(function () {
  "use strict";

  function iniciar() {
    var form = document.querySelector("form[data-lote]");
    if (!form) return;
    var botao = form.querySelector("[data-botao-lote]");
    var campos = form.querySelectorAll("[data-novo]");

    function atualizar() {
      var n = 0;
      for (var i = 0; i < campos.length; i++) {
        var campo = campos[i];
        var original = (campo.getAttribute("data-original") || "").trim();
        var alterado = campo.value.trim() !== "" && campo.value.trim() !== original;
        var bloco = campo.closest(".param");
        if (bloco) {
          if (alterado) bloco.setAttribute("data-alterado", "");
          else bloco.removeAttribute("data-alterado");
        }
        if (alterado) n++;
      }
      botao.textContent = n === 0 ? "Salvar alterações"
        : n === 1 ? "Salvar 1 alteração" : "Salvar " + n + " alterações";
    }

    form.addEventListener("input", atualizar);
    atualizar();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
