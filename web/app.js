(function () {
  const stateLoading = document.getElementById("state-loading");
  const stateEmpty = document.getElementById("state-empty");
  const stateError = document.getElementById("state-error");
  const errorMsg = document.getElementById("error-msg");
  const container = document.getElementById("opportunities");
  const filterOrigin = document.getElementById("filter-origin");
  const filterDest = document.getElementById("filter-dest");
  const btnRefresh = document.getElementById("btn-refresh");
  const filterDateFrom = document.getElementById("filter-date-from");
  const filterDateTo = document.getElementById("filter-date-to");
  const filterMonth = document.getElementById("filter-month");
  const filterPeriodWrap = document.getElementById("filter-period-wrap");
  const filterMonthWrap = document.getElementById("filter-month-wrap");
  const toggleMonth = document.getElementById("toggle-month");
  const monthPickerTrigger = document.getElementById("month-picker-trigger");
  const monthPickerDropdown = document.getElementById("month-picker-dropdown");
  const monthPickerYearEl = document.getElementById("month-picker-year");
  const monthPickerPrev = document.getElementById("month-picker-prev");
  const monthPickerNext = document.getElementById("month-picker-next");
  const monthPickerGrid = document.getElementById("month-picker-grid");
  const highlightSection = document.getElementById("highlight-section");

  var monthPickerCurrentYear = new Date().getFullYear();
  var monthNamesShort = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
  var monthNamesLong = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
  const listSection = document.getElementById("list-section");
  const highlightCards = document.getElementById("highlight-cards");
  const btnHome = document.getElementById("btn-home");
  const btnVerTodas = document.getElementById("btn-ver-todas");
  const btnVoltarHome = document.getElementById("btn-voltar-home");

  let allOpportunities = [];
  let airportLabels = {};
  let originAutocompleteOptions = [];
  let destAutocompleteOptions = [];
  const HIGHLIGHT_COUNT = 8;
  const AUTOCOMPLETE_MAX = 18;
  let viewMode = "home";

  /**
   * Ranqueamento dos voos para os cards da home.
   * Hoje: menor preço da rota (melhor oferta por origem→destino) define a ordem.
   * Quanto menor o preço mínimo da rota, maior o "score" (mais destaque).
   * Retorna score maior = melhor (para ordenar desc).
   */
  function routeScore(route) {
    var minPrice = Math.min.apply(null, (route.offers || []).map(function (o) { return o.price || 0; }));
    if (minPrice <= 0) return 0;
    return 1000000 / minPrice;
  }

  function setState(which) {
    stateLoading.hidden = which !== "loading";
    stateEmpty.hidden = which !== "empty";
    stateError.hidden = which !== "error";
    stateLoading.classList.toggle("state-loading", which === "loading");
    if (which === "ok") {
      if (highlightSection) highlightSection.hidden = false;
      if (listSection) listSection.hidden = viewMode !== "list";
      if (container) container.style.display = viewMode === "list" ? "" : "none";
    } else {
      if (highlightSection) highlightSection.hidden = true;
      if (listSection) listSection.hidden = true;
      if (container) container.style.display = "none";
    }
  }

  function showHomeView() {
    viewMode = "home";
    if (highlightSection) highlightSection.hidden = false;
    if (listSection) listSection.hidden = true;
    if (container) container.style.display = "none";
    window.scrollTo(0, 0);
  }

  function showListView() {
    viewMode = "list";
    if (highlightSection) highlightSection.hidden = true;
    if (listSection) listSection.hidden = false;
    if (container) container.style.display = "";
  }

  function optionValue(code, labels) {
    var label = labels && labels[code];
    return label ? label + " (" + code + ")" : code;
  }

  function optionDisplayText(item) {
    return item.label ? item.label + " (" + item.code + ")" : item.code;
  }

  function matchOption(item, q) {
    if (!q || !q.trim()) return true;
    var qq = q.trim().toLowerCase();
    var label = (item.label || "").toLowerCase();
    var code = (item.code || "").toLowerCase();
    return label.indexOf(qq) >= 0 || code.indexOf(qq) >= 0;
  }

  function showAutocompleteDropdown(inputEl, dropdownEl, options) {
    var q = (inputEl.value || "").trim();
    var list = options.filter(function (item) { return matchOption(item, q); }).slice(0, AUTOCOMPLETE_MAX);
    dropdownEl.innerHTML = "";
    if (list.length === 0) {
      dropdownEl.hidden = true;
      return;
    }
    list.forEach(function (item) {
      var text = optionDisplayText(item);
      var div = document.createElement("div");
      div.className = "autocomplete-item";
      div.setAttribute("role", "option");
      div.textContent = item.label ? item.label : item.code;
      if (item.label && item.code) {
        var codeSpan = document.createElement("span");
        codeSpan.className = "autocomplete-code";
        codeSpan.textContent = " · " + item.code;
        div.appendChild(codeSpan);
      }
      div.dataset.value = text;
      div.addEventListener("mousedown", function (e) {
        e.preventDefault();
        e.stopPropagation();
        inputEl.value = text;
        dropdownEl.hidden = true;
        inputEl.blur();
        if (typeof load === "function") {
          load();
        } else if (typeof inputEl.dispatchEvent !== "undefined") {
          inputEl.dispatchEvent(new Event("input", { bubbles: true }));
        } else {
          render(allOpportunities);
        }
      });
      dropdownEl.appendChild(div);
    });
    dropdownEl.hidden = false;
  }

  function setupCityAutocomplete() {
    var originDropdown = document.getElementById("origin-autocomplete");
    var destDropdown = document.getElementById("dest-autocomplete");
    if (!filterOrigin || !filterDest || !originDropdown || !destDropdown) return;
    var blurTimer = null;
    function bindOne(inputEl, dropdownEl, getOptions) {
      inputEl.addEventListener("input", function () {
        if (blurTimer) clearTimeout(blurTimer);
        showAutocompleteDropdown(inputEl, dropdownEl, getOptions());
        render(allOpportunities);
      });
      inputEl.addEventListener("focus", function () {
        if (blurTimer) clearTimeout(blurTimer);
        showAutocompleteDropdown(inputEl, dropdownEl, getOptions());
      });
      inputEl.addEventListener("blur", function () {
        blurTimer = setTimeout(function () { dropdownEl.hidden = true; }, 180);
      });
      inputEl.addEventListener("keydown", function (e) {
        if (e.key === "Escape") { dropdownEl.hidden = true; return; }
        var items = dropdownEl.querySelectorAll(".autocomplete-item");
        if (items.length === 0) return;
        var current = dropdownEl.querySelector(".autocomplete-item[aria-selected=\"true\"]");
        var idx = current ? Array.prototype.indexOf.call(items, current) : -1;
        if (e.key === "ArrowDown") { e.preventDefault(); idx = Math.min(idx + 1, items.length - 1); }
        else if (e.key === "ArrowUp") { e.preventDefault(); idx = Math.max(idx - 1, 0); }
        else if (e.key === "Enter" && idx >= 0 && items[idx]) {
          e.preventDefault();
          inputEl.value = items[idx].dataset.value;
          dropdownEl.hidden = true;
          render(allOpportunities);
          return;
        }
        items.forEach(function (el, i) { el.setAttribute("aria-selected", i === idx); });
        if (idx >= 0 && items[idx]) items[idx].scrollIntoView({ block: "nearest" });
      });
    }
    bindOne(filterOrigin, originDropdown, function () { return originAutocompleteOptions; });
    bindOne(filterDest, destDropdown, function () { return destAutocompleteOptions; });
  }

  function fillAutocomplete(origins, destinations, labels) {
    labels = labels || airportLabels;
    var originsArr = Array.isArray(origins) ? origins : [];
    var destsArr = Array.isArray(destinations) ? destinations : [];
    var allCodes = [];
    var seen = {};
    originsArr.forEach(function (c) {
      if (!seen[c]) { seen[c] = true; allCodes.push(c); }
    });
    destsArr.forEach(function (c) {
      if (!seen[c]) { seen[c] = true; allCodes.push(c); }
    });
    allCodes.sort();
    var options = allCodes.map(function (c) {
      return { code: c, label: (labels && labels[c]) || "" };
    });
    originAutocompleteOptions = options;
    destAutocompleteOptions = options;
  }

  function loadAutocomplete() {
    fetch("/api/origins_destinations")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.labels) airportLabels = data.labels;
        if (data && data.origins && data.destinations) {
          fillAutocomplete(data.origins, data.destinations, data.labels || airportLabels);
        }
        if (data && data.labels && allOpportunities.length) render(allOpportunities);
      })
      .catch(function () {});
  }

  function escapeHtml(s) {
    if (!s) return "";
    var div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function formatAirport(code) {
    if (!code) return "?";
    var label = airportLabels[code];
    return label ? code + " (" + escapeHtml(label) + ")" : code;
  }

  function formatDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
  }

  function toYyyyMmDd(isoOrDate) {
    if (!isoOrDate) return "";
    var d = new Date(isoOrDate);
    if (isNaN(d.getTime())) return "";
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  function buildViajanetOnewayUrl(origin, destination, departureDate) {
    var base = "https://www.viajanet.com.br/shop/flights/results/oneway";
    var o = (origin || "").toUpperCase();
    var dest = (destination || "").toUpperCase();
    var dateStr = toYyyyMmDd(departureDate);
    if (!o || !dest || !dateStr) return null;
    return base + "/" + o + "/" + dest + "/" + dateStr + "/1/0/0?from=SB&di=1&reSearch=true";
  }

  function formatPrice(n) {
    return "R$ " + Number(n).toLocaleString("pt-BR");
  }

  function sourceLabel(source) {
    if (!source) return "—";
    if (source === "viajanet") return "ViajaNet";
    if (source === "passagens_imperdiveis") return "Passagens Imperdíveis";
    if (source === "melhores_destinos") return "Melhores Destinos";
    return source.replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function sourceClass(source) {
    if (!source) return "";
    return source.toLowerCase().replace(/[^a-z0-9]/g, "_");
  }

  function parseAirportInput(val) {
    val = (val || "").trim();
    var match = val.match(/\s*\(([A-Z0-9]{3})\)\s*$/i);
    return match ? match[1].toUpperCase() : val.toUpperCase();
  }

  function parseDateOnly(isoOrDate) {
    if (!isoOrDate) return null;
    var d = new Date(isoOrDate);
    if (isNaN(d.getTime())) return null;
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  }

  function parseMonthInput(val) {
    var s = (val || "").trim();
    if (!s) return null;
    var m, y;
    var parts = s.split(/[\/\-]/);
    if (parts.length === 2) {
      var a = parseInt(parts[0], 10), b = parseInt(parts[1], 10);
      if (parts[0].length === 4) { y = a; m = b; } else { m = a; y = b; }
    } else {
      return null;
    }
    if (m >= 1 && m <= 12 && y >= 2000 && y <= 2100) {
      return { year: y, month: m - 1 };
    }
    return null;
  }

  function applyDateFilter(list) {
    if (!list || !list.length) return list;
    var useMonth = toggleMonth && toggleMonth.getAttribute("aria-checked") === "true";
    var fromTs = null, toTs = null;
    if (useMonth && filterMonth && filterMonth.value) {
      var parsed = parseMonthInput(filterMonth.value);
      if (parsed) {
        fromTs = new Date(parsed.year, parsed.month, 1).getTime();
        toTs = new Date(parsed.year, parsed.month + 1, 0).getTime();
      }
    } else if (filterDateFrom && filterDateTo && filterDateFrom.value && filterDateTo.value) {
      fromTs = parseDateOnly(filterDateFrom.value);
      toTs = parseDateOnly(filterDateTo.value);
      if (fromTs != null && toTs != null && fromTs > toTs) { var t = fromTs; fromTs = toTs; toTs = t; }
    }
    if (fromTs == null && toTs == null) return list;
    return list.filter(function (o) {
      var dep = parseDateOnly(o.departure_date);
      if (dep == null) return false;
      if (fromTs != null && dep < fromTs) return false;
      if (toTs != null && dep > toTs) return false;
      return true;
    });
  }

  function applyFilters(list) {
    let out = list;
    const origin = parseAirportInput(filterOrigin && filterOrigin.value);
    const dest = parseAirportInput(filterDest && filterDest.value);
    var originStr = (origin || "").trim().toUpperCase();
    var destStr = (dest || "").trim().toUpperCase();
    var originExact = originStr.length === 3;
    var destExact = destStr.length === 3;
    if (originStr) {
      out = out.filter(function (o) {
        var oOrig = (o.origin || "").trim().toUpperCase();
        return originExact ? oOrig === originStr : oOrig.indexOf(originStr) >= 0;
      });
    }
    if (destStr) {
      out = out.filter(function (o) {
        var oDest = (o.destination || "").trim().toUpperCase();
        return destExact ? oDest === destStr : oDest.indexOf(destStr) >= 0;
      });
    }
    out = applyDateFilter(out);
    return out;
  }

  function groupByRoute(opportunities) {
    const byRoute = {};
    for (const o of opportunities) {
      const key = o.origin + "|" + o.destination;
      if (!byRoute[key]) byRoute[key] = { origin: o.origin, destination: o.destination, offers: [] };
      byRoute[key].offers.push(o);
    }
    for (const k of Object.keys(byRoute)) {
      var offers = byRoute[k].offers;
      offers.sort(function (a, b) {
        if (a.global_rank != null && b.global_rank != null) return a.global_rank - b.global_rank;
        return a.price - b.price;
      });
    }
    return Object.values(byRoute);
  }

  function bestGlobalRank(route) {
    if (!route || !route.offers || !route.offers.length) return Infinity;
    var r = route.offers[0].global_rank;
    return r != null ? r : Infinity;
  }

  function renderHighlightCards(routes) {
    if (!highlightCards) return;
    var sorted = routes.slice().sort(function (a, b) {
      var rankA = bestGlobalRank(a), rankB = bestGlobalRank(b);
      if (rankA !== Infinity || rankB !== Infinity) return rankA - rankB;
      return routeScore(b) - routeScore(a);
    });
    var top = sorted.slice(0, HIGHLIGHT_COUNT);
    highlightCards.innerHTML = top.map(function (route) {
      var offers = route.offers;
      var minPrice = Math.min.apply(null, offers.map(function (o) { return o.price; }));
      var bestOffer = offers[0];
      var firstSource = bestOffer ? sourceLabel(bestOffer.source) : "";
      var offerUrl = "#";
      if (bestOffer) {
        var src = (bestOffer.source || "").toLowerCase();
        var isOneway = !bestOffer.return_date;
        if (src === "viajanet" && isOneway && bestOffer.departure_date) {
          var viajanetUrl = buildViajanetOnewayUrl(route.origin, route.destination, bestOffer.departure_date);
          if (viajanetUrl) offerUrl = viajanetUrl;
          else if (bestOffer.url) offerUrl = bestOffer.url;
        } else if (bestOffer.url) {
          offerUrl = bestOffer.url;
        }
      }
      var isExternal = offerUrl && offerUrl !== "#";
      var depStr = bestOffer && bestOffer.departure_date ? formatDate(bestOffer.departure_date) : "";
      var retStr = bestOffer && bestOffer.return_date ? formatDate(bestOffer.return_date) : "";
      var dateHtml = "";
      if (depStr && retStr) {
        dateHtml = '<div class="highlight-card-date">' +
          '<span class="highlight-card-date-icon">📅</span> ' +
          '<span>Data de partida: Ida ' + escapeHtml(depStr) + ' · Volta ' + escapeHtml(retStr) + '</span></div>';
      } else if (depStr) {
        dateHtml = '<div class="highlight-card-date"><span class="highlight-card-date-icon">📅</span> Data de partida: ' + escapeHtml(depStr) + "</div>";
      }
      var tag = isExternal ? "a" : "div";
      var attrs = isExternal ? ' href="' + escapeHtml(offerUrl) + '" target="_blank" rel="noopener"' : "";
      return (
        "<" + tag + " class=\"highlight-card\"" + attrs + ">" +
          '<div class="highlight-card-route">' +
          escapeHtml(formatAirport(route.origin)) +
          ' <span class="highlight-card-arrow">→</span> ' +
          escapeHtml(formatAirport(route.destination)) +
          "</div>" +
          dateHtml +
          '<div class="highlight-card-price">' + formatPrice(minPrice) + "</div>" +
          (firstSource ? '<div class="highlight-card-source">' + escapeHtml(firstSource) + "</div>" : "") +
        "</" + tag + ">"
      );
    }).join("");
  }

  function render(opportunities) {
    const filtered = applyFilters(opportunities);
    const routes = groupByRoute(filtered);

    if (routes.length === 0) {
      container.innerHTML = "";
      setState("empty");
      return;
    }

    setState("ok");
    if (viewMode === "home") {
      renderHighlightCards(routes);
      if (listSection) listSection.hidden = true;
      if (container) container.style.display = "none";
    } else {
      container.innerHTML = "";
      routes.forEach((route) => {
        const minPrice = Math.min(...route.offers.map((o) => o.price));
        const card = document.createElement("div");
        card.className = "route-card";
        card.innerHTML =
          '<div class="route-header">' +
          '<span class="route-route">' +
          formatAirport(route.origin) +
          ' <span>→</span> ' +
          formatAirport(route.destination) +
          "</span>" +
          '<span class="route-min-price">' +
          formatPrice(minPrice) +
          "</span>" +
          "</div>" +
          '<div class="offers">' +
          '<div class="offer-row offer-header">' +
          '<span class="offer-source">Fornecedor</span>' +
          '<span class="offer-date">Data partida</span>' +
          '<span class="offer-price">Preço</span>' +
          '<span class="offer-link-cell">Ver oferta</span>' +
          '</div>' +
          '</div>';
        const offersEl = card.querySelector(".offers");
        route.offers.forEach((offer) => {
          const row = document.createElement("div");
          row.className = "offer-row";
          row.innerHTML =
            '<span class="offer-source ' +
            sourceClass(offer.source) +
            '">' +
            sourceLabel(offer.source) +
            "</span>" +
            '<span class="offer-date">' +
            formatDate(offer.departure_date) +
            "</span>" +
            '<span class="offer-price">' +
            formatPrice(offer.price) +
            "</span>" +
            (offer.url
              ? '<a class="offer-link" href="' +
                (offer.url || "#") +
                '" target="_blank" rel="noopener">Ver oferta</a>'
              : '<span class="offer-link-cell"></span>');
          offersEl.appendChild(row);
        });
        container.appendChild(card);
      });
    }
  }

  function load() {
    setState("loading");
    errorMsg.textContent = "";
    var timeoutId;
    var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    if (controller) timeoutId = setTimeout(function () { controller.abort(); }, 15000);

    function done(err) {
      if (timeoutId) clearTimeout(timeoutId);
      if (err) {
        errorMsg.textContent = err;
        setState("error");
      }
    }

    var originParam = parseAirportInput(filterOrigin && filterOrigin.value);
    var destParam = parseAirportInput(filterDest && filterDest.value);
    var url = "/api/deals?limit=200";
    if (originParam) url += "&origin=" + encodeURIComponent(originParam);
    if (destParam) url += "&destination=" + encodeURIComponent(destParam);
    var opts = controller ? { signal: controller.signal } : {};
    fetch(url, opts)
      .then(function (r) {
        if (!r.ok) throw new Error(r.status + " " + (r.statusText || "Erro"));
        var ct = r.headers.get("Content-Type") || "";
        if (ct.indexOf("application/json") === -1) throw new Error("Resposta inválida do servidor (não é JSON).");
        return r.json();
      })
      .then(function (data) {
        if (timeoutId) clearTimeout(timeoutId);
        try {
          if (Array.isArray(data)) {
            allOpportunities = data;
            render(data);
          } else if (data && data.error) {
            errorMsg.textContent = data.error;
            setState("error");
          } else {
            setState("empty");
          }
        } catch (e) {
          errorMsg.textContent = e.message || "Erro ao exibir dados.";
          setState("error");
        }
      })
      .catch(function (err) {
        if (err.name === "AbortError") {
          done("Tempo esgotado (15s). Verifique se o PostgreSQL está rodando e se o banco está acessível.");
        } else {
          done(err.message || "Falha ao carregar ofertas. Verifique o console (F12).");
        }
      });
  }

  function updatePeriodMonthVisibility() {
    var on = toggleMonth && toggleMonth.getAttribute("aria-checked") === "true";
    if (filterPeriodWrap) {
      if (on) filterPeriodWrap.classList.add("filter-hidden");
      else filterPeriodWrap.classList.remove("filter-hidden");
    }
    if (filterMonthWrap) {
      if (on) {
        filterMonthWrap.classList.remove("filter-hidden");
        if (monthPickerTrigger) monthPickerTrigger.textContent = getMonthTriggerLabel();
      } else {
        filterMonthWrap.classList.add("filter-hidden");
        closeMonthPicker();
      }
    }
  }

  function getMonthTriggerLabel() {
    var val = (filterMonth && filterMonth.value) || "";
    if (!val) return "Selecione o mês";
    var p = parseMonthInput(val);
    if (!p) return "Selecione o mês";
    return monthNamesLong[p.month] + " " + p.year;
  }

  function renderMonthGrid(year) {
    if (!monthPickerGrid) return;
    monthPickerCurrentYear = year;
    if (monthPickerYearEl) monthPickerYearEl.textContent = year;
    monthPickerGrid.innerHTML = "";
    for (var m = 0; m < 12; m++) {
      var val = year + "-" + String(m + 1).padStart(2, "0");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "month-picker-cell";
      btn.textContent = monthNamesShort[m];
      btn.dataset.value = val;
      btn.addEventListener("click", function () {
        var v = this.dataset.value;
        if (filterMonth) filterMonth.value = v;
        if (monthPickerTrigger) monthPickerTrigger.textContent = getMonthTriggerLabel();
        closeMonthPicker();
        render(allOpportunities);
      });
      monthPickerGrid.appendChild(btn);
    }
  }

  function openMonthPicker() {
    if (!monthPickerDropdown || !monthPickerTrigger) return;
    var val = (filterMonth && filterMonth.value) || "";
    var y = monthPickerCurrentYear;
    if (val) {
      var p = parseMonthInput(val);
      if (p) y = p.year;
    } else {
      y = new Date().getFullYear();
    }
    monthPickerCurrentYear = y;
    renderMonthGrid(y);
    monthPickerDropdown.hidden = false;
    monthPickerTrigger.setAttribute("aria-expanded", "true");
  }

  function closeMonthPicker() {
    if (monthPickerDropdown) {
      monthPickerDropdown.hidden = true;
      if (monthPickerTrigger) monthPickerTrigger.setAttribute("aria-expanded", "false");
    }
  }

  if (monthPickerTrigger) {
    monthPickerTrigger.addEventListener("click", function (e) {
      e.preventDefault();
      if (monthPickerDropdown && monthPickerDropdown.hidden) openMonthPicker();
      else closeMonthPicker();
    });
    monthPickerTrigger.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (monthPickerDropdown && monthPickerDropdown.hidden) openMonthPicker();
        else closeMonthPicker();
      }
    });
  }
  if (monthPickerPrev) {
    monthPickerPrev.addEventListener("click", function () {
      renderMonthGrid(monthPickerCurrentYear - 1);
    });
  }
  if (monthPickerNext) {
    monthPickerNext.addEventListener("click", function () {
      renderMonthGrid(monthPickerCurrentYear + 1);
    });
  }
  document.addEventListener("click", function (e) {
    if (!monthPickerDropdown || monthPickerDropdown.hidden) return;
    var tr = monthPickerTrigger;
    var dd = monthPickerDropdown;
    if (tr && dd && e.target !== tr && !tr.contains(e.target) && e.target !== dd && !dd.contains(e.target)) {
      closeMonthPicker();
    }
  });

  if (toggleMonth) {
    toggleMonth.addEventListener("click", function () {
      var on = toggleMonth.getAttribute("aria-checked") !== "true";
      toggleMonth.setAttribute("aria-checked", on ? "true" : "false");
      updatePeriodMonthVisibility();
      render(allOpportunities);
    });
  }
  updatePeriodMonthVisibility();
  if (monthPickerTrigger) monthPickerTrigger.textContent = getMonthTriggerLabel();

  if (filterDateFrom) filterDateFrom.addEventListener("change", function () { render(allOpportunities); });
  if (filterDateTo) filterDateTo.addEventListener("change", function () { render(allOpportunities); });

  btnRefresh.addEventListener("click", load);
  filterOrigin.addEventListener("input", function () { render(allOpportunities); });
  filterDest.addEventListener("input", function () { render(allOpportunities); });

  if (btnHome) {
    btnHome.addEventListener("click", function (e) {
      e.preventDefault();
      showHomeView();
      if (allOpportunities.length) {
        var routes = groupByRoute(applyFilters(allOpportunities));
        if (routes.length) renderHighlightCards(routes);
      }
    });
  }
  if (btnVerTodas) {
    btnVerTodas.addEventListener("click", function () {
      showListView();
      render(allOpportunities);
    });
  }
  if (btnVoltarHome) {
    btnVoltarHome.addEventListener("click", function () {
      showHomeView();
      if (allOpportunities.length) {
        var routes = groupByRoute(applyFilters(allOpportunities));
        if (routes.length) renderHighlightCards(routes);
      }
    });
  }

  setupCityAutocomplete();
  loadAutocomplete();
  load();
})();
