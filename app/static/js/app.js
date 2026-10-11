/* Renderização dos gráficos (pizza, barras) via Chart.js.
   Os dados são embutidos na página em <script id="page-data">. */
(function () {
  "use strict";

  const PALETA = [
    "#1f5fa8", "#12805c", "#d99a00", "#b3382c", "#6b3fa0",
    "#2f9e8f", "#e07b39", "#4a6fa5", "#8fbf3f", "#c2557a",
    "#3b7dd8", "#7d5ba6", "#0f9b8e", "#a68a00", "#c0392b",
  ];

  const brl = new Intl.NumberFormat("pt-BR");

  function lerDados() {
    const el = document.getElementById("page-data");
    if (!el) return {};
    try {
      return JSON.parse(el.textContent);
    } catch (err) {
      console.error("Falha ao ler page-data", err);
      return {};
    }
  }

  function baseOptions(extraLegenda) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: extraLegenda || { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0) || 1;
              const v = ctx.parsed.y !== undefined ? ctx.parsed.y : ctx.parsed;
              return ` ${ctx.label}: ${brl.format(v)} (${(v / total * 100).toFixed(1)}%)`;
            },
          },
        },
      },
    };
  }

  function novo(id) {
    const el = document.getElementById(id);
    return el ? el.getContext("2d") : null;
  }

  function graficoPizza(id, rotulos, valores) {
    const ctx = novo(id);
    if (!ctx) return;
    new Chart(ctx, {
      type: "pie",
      data: {
        labels: rotulos,
        datasets: [{
          data: valores,
          backgroundColor: rotulos.map((_, i) => PALETA[i % PALETA.length]),
          borderColor: "#fff",
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { boxWidth: 14, font: { size: 12 } } },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const total = ctx.dataset.data.reduce((a, b) => a + b, 0) || 1;
                return ` ${ctx.label}: ${brl.format(ctx.parsed)} (${(ctx.parsed / total * 100).toFixed(1)}%)`;
              },
            },
          },
        },
      },
    });
  }

  function graficoBarras(id, rotulos, valores, horizontal, cor) {
    const ctx = novo(id);
    if (!ctx) return;
    new Chart(ctx, {
      type: "bar",
      data: {
        labels: rotulos,
        datasets: [{
          data: valores,
          backgroundColor: rotulos.map((_, i) => cor || PALETA[i % PALETA.length]),
          borderRadius: 6,
        }],
      },
      options: Object.assign(baseOptions(), {
        indexAxis: horizontal ? "y" : "x",
        scales: {
          x: {
            beginAtZero: true,
            ticks: horizontal
              ? { callback: (v) => brl.format(v) }
              : { autoSkip: false, maxRotation: 45, minRotation: 0, font: { size: 11 } },
            grid: { color: "#eef2f7" },
          },
          y: {
            beginAtZero: true,
            ticks: horizontal ? { font: { size: 11 } } : { callback: (v) => brl.format(v) },
            grid: { color: "#eef2f7" },
          },
        },
      }),
    });
  }

  function iniciaDashboard(d) {
    graficoPizza(
      "graficoCategoria",
      (d.categoria || []).map((r) => r.rotulo),
      (d.categoria || []).map((r) => r.total)
    );

    const partidos = (d.partido || []).slice(0, 8);
    graficoPizza(
      "graficoPartido",
      partidos.map((r) => r.rotulo),
      partidos.map((r) => r.total)
    );

    graficoBarras(
      "graficoCandidatos",
      (d.candidatos || []).map((r) => r.rotulo),
      (d.candidatos || []).map((r) => r.total),
      true
    );

    graficoBarras(
      "graficoZona",
      (d.zona || []).map((r) => "Zona " + r.rotulo),
      (d.zona || []).map((r) => r.total),
      false,
      "#1f5fa8"
    );
  }

  function iniciaCandidatos(d) {
    graficoBarras(
      "graficoTopCandidatos",
      (d.candidatos || []).map((r) => r.rotulo),
      (d.candidatos || []).map((r) => r.total),
      true
    );

    const partidos = (d.partido || []).slice(0, 10);
    graficoBarras(
      "graficoPartidos",
      partidos.map((r) => r.rotulo),
      partidos.map((r) => r.total),
      false
    );
  }

  function iniciaZonas(d) {
    graficoBarras(
      "graficoZonas",
      (d.zona || []).map((r) => "Zona " + r.rotulo),
      (d.zona || []).map((r) => r.total),
      false,
      "#12805c"
    );

    const zonas = (d.zona || []).slice().sort((a, b) => b.total - a.total);
    graficoPizza(
      "graficoZonasPizza",
      zonas.map((r) => "Zona " + r.rotulo),
      zonas.map((r) => r.total)
    );
  }

  /* Combobox com busca digitada: filtra as opções do <select multiple>
     correspondente a [data-filter-for]. Os já selecionados permanecem visíveis. */
  function ligarBuscaEmListas() {
    const campos = document.querySelectorAll("[data-filter-for]");
    campos.forEach(function (input) {
      const alvo = document.getElementById(input.getAttribute("data-filter-for"));
      if (!alvo || alvo.tagName !== "SELECT") return;
      input.addEventListener("input", function () {
        const termo = input.value.trim().toLowerCase();
        Array.prototype.forEach.call(alvo.options, function (op) {
          const visivel =
            op.selected || !termo || op.text.toLowerCase().indexOf(termo) !== -1;
          op.style.display = visivel ? "" : "none";
          op.hidden = !visivel;
        });
      });
    });
  }

  function iniciar() {
    ligarBuscaEmListas();
    if (typeof Chart === "undefined") return;
    const dados = lerDados();
    const pagina = document.body.dataset.page;
    if (pagina === "dashboard") iniciaDashboard(dados);
    else if (pagina === "candidatos") iniciaCandidatos(dados);
    else if (pagina === "zonas") iniciaZonas(dados);
  }

  window.addEventListener("DOMContentLoaded", iniciar);
})();
