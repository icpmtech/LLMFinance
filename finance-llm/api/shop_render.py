"""Vitrine pública da loja online (`/loja/...`).

Converte o modelo do `shop_store` em HTML pronto a servir: catálogo com
pesquisa, filtros e paginação, ficha de produto com avaliações, carrinho e
finalização de compra, além de confirmação de encomenda, `sitemap.xml` e
`robots.txt`.

O HTML é **autónomo** (CSS embutido, sem dependências) e cada página leva a
mesma aplicação de carrinho em JavaScript: o carrinho vive no `localStorage` do
visitante e o **servidor continua a ser a autoridade** — o browser só envia
identificadores e quantidades, os preços, o stock e os portes são recalculados
em `shop_store.checkout`.
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import markdown as markdown_lib

from api import shop_store as store

logger = logging.getLogger(__name__)

MD_EXTENSIONS = ["extra", "sane_lists", "nl2br", "toc"]

_THEMES: Dict[str, Dict[str, str]] = {
    "claro": {
        "bg": "#f6f7f9",
        "surface": "#ffffff",
        "text": "#0f172a",
        "muted": "#5c6678",
        "border": "#e3e7ee",
        "soft": "#f1f3f8",
        "shadow": "0 1px 2px rgba(15,23,42,.06), 0 10px 30px rgba(15,23,42,.07)",
    },
    "escuro": {
        "bg": "#0a1119",
        "surface": "#111c27",
        "text": "#eef2f7",
        "muted": "#93a1b5",
        "border": "#20303f",
        "soft": "#16232f",
        "shadow": "0 1px 2px rgba(0,0,0,.4), 0 12px 34px rgba(0,0,0,.38)",
    },
}

_CART_KEY = "iqos-loja-carrinho"


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _md(text: str) -> str:
    if not (text or "").strip():
        return ""
    try:
        return markdown_lib.markdown(text, extensions=MD_EXTENSIONS, output_format="html5")
    except Exception as exc:  # pragma: no cover - markdown robusto
        logger.warning("Falha a converter Markdown (%s); a devolver texto.", exc)
        return f"<p>{_esc(text)}</p>"


def _euros(value: Any) -> str:
    amount = store.money(value)
    text = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} €"


def _date(value: Optional[str], with_time: bool = False) -> str:
    if not value:
        return ""
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:10]
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone().strftime("%d/%m/%Y %H:%M") if with_time else stamp.astimezone().strftime("%d/%m/%Y")


def _initials(name: str) -> str:
    parts = [part for part in re.split(r"\s+", name or "") if part]
    return "".join(part[0] for part in parts[:2]).upper() or "IQ"


def _image(url: str, alt: str, name: str = "") -> str:
    if url:
        return f'<img src="{_esc(url)}" alt="{_esc(alt)}" loading="lazy">'
    return f'<span class="ph" aria-hidden="true">{_esc(_initials(name or alt))}</span>'


def _stars(average: float, count: int = 0) -> str:
    value = store.money(average)
    full = int(value + 0.5)
    marks = "".join("★" if index < full else "☆" for index in range(5))
    label = f"{value:.1f}".replace(".", ",") if count else "sem avaliações"
    return f'<span class="stars" title="{_esc(label)}">{marks}<small>{_esc(label)}{f" ({count})" if count else ""}</small></span>'


# --------------------------------------------------------------------------
# CSS
# --------------------------------------------------------------------------
def _css(settings: Dict[str, Any]) -> str:
    theme = _THEMES.get(str(settings.get("theme") or "claro"), _THEMES["claro"])
    accent = str(settings.get("accent") or "#0ea5a4")
    radius = store._int(settings.get("radius"), 14)
    return """
:root{--bg:%(bg)s;--surface:%(surface)s;--text:%(text)s;--muted:%(muted)s;--border:%(border)s;--soft:%(soft)s;
--accent:%(accent)s;--radius:%(radius)spx;--shadow:%(shadow)s}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 "Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif}
img{max-width:100%%;display:block}
a{color:inherit;text-decoration:none}
.wrap{max-width:1180px;margin:0 auto;padding:0 18px}
h1,h2,h3{line-height:1.2;margin:0 0 10px}
h1{font-size:clamp(24px,3.4vw,34px)}
h2{font-size:20px}
small{font-size:12px;color:var(--muted)}
.muted{color:var(--muted)}
/* cabeçalho */
.site-header{position:sticky;top:0;z-index:40;background:color-mix(in srgb,var(--surface) 88%%,transparent);backdrop-filter:blur(12px);border-bottom:1px solid var(--border)}
.site-header .wrap{display:flex;align-items:center;gap:14px;min-height:62px;flex-wrap:wrap}
.brand{display:flex;flex-direction:column;font-weight:700;font-size:16px;line-height:1.1}
.brand small{font-weight:400}
.site-header nav{display:flex;gap:14px;font-size:13.5px;color:var(--muted);flex-wrap:wrap}
.site-header nav a:hover{color:var(--text)}
.header-tools{margin-left:auto;display:flex;align-items:center;gap:8px}
.search{display:flex;align-items:center;gap:6px;background:var(--soft);border:1px solid var(--border);border-radius:999px;padding:6px 12px}
.search input{border:0;background:transparent;color:var(--text);outline:none;width:170px;font-size:13.5px}
.cart-pill{position:relative;display:inline-flex;align-items:center;gap:8px;background:var(--accent);color:#04252a;font-weight:600;
border-radius:999px;padding:8px 14px;font-size:13.5px;cursor:pointer;border:0}
.cart-pill[data-count]:not([data-count="0"])::after{content:attr(data-count);position:absolute;top:-6px;right:-6px;background:#0f172a;color:#fff;
border-radius:999px;min-width:19px;height:19px;display:grid;place-items:center;font-size:11px;padding:0 5px}
/* botões */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:1px solid transparent;border-radius:calc(var(--radius) - 4px);
padding:10px 16px;font-size:14px;font-weight:600;cursor:pointer;background:var(--accent);color:#04252a;transition:.15s}
.btn:hover{filter:brightness(1.06)}
.btn.ghost{background:transparent;border-color:var(--border);color:var(--text)}
.btn.ghost:hover{background:var(--soft)}
.btn.danger{background:#e11d48;color:#fff}
.btn[disabled]{opacity:.5;cursor:not-allowed}
.btn.small{padding:7px 12px;font-size:13px}
/* cartões de produto */
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(250px,1fr))}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow);display:flex;flex-direction:column}
.card .thumb{aspect-ratio:4/3;background:var(--soft);display:grid;place-items:center;overflow:hidden}
.card .thumb img{width:100%%;height:100%%;object-fit:cover}
.ph{font-weight:700;font-size:28px;color:var(--muted);letter-spacing:1px}
.card .body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:6px;flex:1}
.card .name{font-weight:600;font-size:14.5px}
.card .desc{color:var(--muted);font-size:12.5px;flex:1}
.price{display:flex;align-items:baseline;gap:8px;font-weight:700;font-size:16px}
.price del{font-weight:400;font-size:13px;color:var(--muted)}
.badges{display:flex;gap:6px;flex-wrap:wrap}
.badge{border-radius:999px;padding:3px 9px;font-size:11px;font-weight:600;background:var(--soft);color:var(--muted);border:1px solid var(--border)}
.badge.sale{background:#fee2e2;color:#b91c1c;border-color:#fecaca}
.badge.good{background:#dcfce7;color:#15803d;border-color:#bbf7d0}
.badge.warn{background:#fef3c7;color:#a16207;border-color:#fde68a}
.badge.out{background:#f1f5f9;color:#64748b}
.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:18px 0}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{border:1px solid var(--border);border-radius:999px;padding:6px 12px;font-size:13px;background:var(--surface);color:var(--muted)}
.chip.active{background:var(--accent);color:#04252a;border-color:transparent;font-weight:600}
select,input[type=text],input[type=email],input[type=tel],input[type=number],input[type=date],textarea{
width:100%%;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:9px 11px;color:var(--text);font:inherit;font-size:14px;outline:none}
select:focus,input:focus,textarea:focus{border-color:var(--accent)}
label{display:flex;flex-direction:column;gap:5px;font-size:12.5px;color:var(--muted)}
.field-grid{display:grid;gap:12px;grid-template-columns:1fr 1fr}
.field-grid .wide{grid-column:1/-1}
/* ficha de produto */
.product{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:28px;margin:22px 0 34px}
.gallery{border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;background:var(--surface);box-shadow:var(--shadow)}
.gallery .main{aspect-ratio:4/3;display:grid;place-items:center;background:var(--soft)}
.gallery .main img{width:100%%;height:100%%;object-fit:cover}
.thumbs{display:flex;gap:8px;padding:10px}
.thumbs img{width:64px;height:64px;object-fit:cover;border-radius:8px;border:1px solid var(--border);cursor:pointer}
.buy{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow);align-self:start}
.buy .price{font-size:26px;margin:6px 0}
.attributes{display:grid;gap:6px;margin:14px 0;border-top:1px solid var(--border);padding-top:12px}
.attributes div{display:flex;justify-content:space-between;gap:12px;font-size:13.5px}
.attributes span:first-child{color:var(--muted)}
.qty{display:inline-flex;align-items:center;border:1px solid var(--border);border-radius:10px;overflow:hidden}
.qty button{background:var(--soft);border:0;width:34px;height:38px;cursor:pointer;font-size:16px;color:var(--text)}
.qty input{width:52px;text-align:center;border:0;background:transparent}
section.block{margin:30px 0}
.prose{max-width:74ch}
.prose h2{margin-top:22px}
.prose table{border-collapse:collapse;width:100%%}
.prose td,.prose th{border:1px solid var(--border);padding:6px 9px;font-size:13.5px}
.reviews{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(280px,1fr))}
.review{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px}
.stars{color:#f59e0b;font-size:14px;letter-spacing:1px}
.stars small{color:var(--muted);margin-left:6px}
/* carrinho */
.cart{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:22px;align-items:start;margin:22px 0 40px}
.cart-side{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:18px;box-shadow:var(--shadow);position:sticky;top:78px}
.lines{display:flex;flex-direction:column;gap:10px}
.line{display:grid;grid-template-columns:64px minmax(0,1fr) auto;gap:12px;align-items:center;background:var(--surface);
border:1px solid var(--border);border-radius:var(--radius);padding:10px}
.line .thumb{width:64px;height:64px;border-radius:10px;overflow:hidden;background:var(--soft);display:grid;place-items:center}
.line .thumb img{width:100%%;height:100%%;object-fit:cover}
.line .remove{background:transparent;border:0;color:var(--muted);cursor:pointer;font-size:12px;text-decoration:underline}
.totals{display:flex;flex-direction:column;gap:6px;margin:14px 0;border-top:1px solid var(--border);padding-top:12px;font-size:14px}
.totals div{display:flex;justify-content:space-between;gap:12px}
.totals .grand{font-weight:700;font-size:17px;border-top:1px solid var(--border);margin-top:6px;padding-top:10px}
.coupon{display:flex;gap:8px;margin:12px 0}
.notice{border-radius:10px;padding:10px 12px;font-size:13.5px;border:1px solid var(--border);background:var(--soft);color:var(--muted)}
.notice.ok{border-color:#bbf7d0;background:#f0fdf4;color:#15803d}
.notice.error{border-color:#fecaca;background:#fef2f2;color:#b91c1c}
.notice.warn{border-color:#fde68a;background:#fffbeb;color:#a16207}
.pay{margin:14px 0;display:grid;gap:8px}
.pay label{flex-direction:row;align-items:center;gap:9px;font-size:13.5px;color:var(--text)}
.pay input{width:auto}
.empty{border:1px dashed var(--border);border-radius:var(--radius);padding:40px;text-align:center;color:var(--muted)}
.receipt{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:22px;box-shadow:var(--shadow)}
.receipt .num{font-size:22px;font-weight:700}
.receipt table{width:100%%;border-collapse:collapse;margin:14px 0;font-size:14px}
.receipt td,.receipt th{border-bottom:1px solid var(--border);padding:8px 4px;text-align:left}
.receipt td:last-child,.receipt th:last-child{text-align:right}
/* rodapé e avisos */
.site-footer{margin-top:50px;border-top:1px solid var(--border);background:var(--surface)}
.site-footer .wrap{display:flex;justify-content:space-between;gap:16px;padding:22px 18px;flex-wrap:wrap;font-size:13px;color:var(--muted)}
.site-footer nav{display:flex;gap:14px;flex-wrap:wrap}
.toast{position:fixed;left:50%%;bottom:22px;transform:translate(-50%%,20px);background:#0f172a;color:#fff;border-radius:12px;padding:11px 18px;
font-size:13.5px;opacity:0;transition:.22s;pointer-events:none;z-index:80}
.toast.show{opacity:1;transform:translate(-50%%,0)}
.pager{display:flex;gap:6px;align-items:center;justify-content:center;margin:26px 0}
.pager a,.pager span{border:1px solid var(--border);border-radius:8px;padding:6px 11px;font-size:13.5px;background:var(--surface)}
.pager .on{background:var(--accent);color:#04252a;border-color:transparent;font-weight:600}
@media (max-width:900px){
 .product,.cart,.field-grid{grid-template-columns:1fr}
 .cart-side{position:static}
 .search input{width:120px}
}
""" % {
        "bg": theme["bg"],
        "surface": theme["surface"],
        "text": theme["text"],
        "muted": theme["muted"],
        "border": theme["border"],
        "soft": theme["soft"],
        "shadow": theme["shadow"],
        "accent": accent,
        "radius": radius,
    }


# --------------------------------------------------------------------------
# Carrinho (JavaScript da vitrine)
# --------------------------------------------------------------------------
_CART_JS = r"""
(function(){
  var DATA = JSON.parse(document.getElementById("loja-dados").textContent || "{}");
  var KEY = DATA.cart_key || "iqos-loja-carrinho";
  var money = function(v){ return (Math.round((Number(v)||0)*100)/100).toFixed(2).replace(".", ",") + " \u20AC"; };
  function read(){ try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch(e){ return []; } }
  function write(cart){
    localStorage.setItem(KEY, JSON.stringify(cart));
    document.dispatchEvent(new CustomEvent("loja:carrinho", {detail: cart}));
    badge();
  }
  function badge(){
    var count = read().reduce(function(sum, line){ return sum + (Number(line.qty)||0); }, 0);
    Array.prototype.forEach.call(document.querySelectorAll("[data-cart-count]"), function(node){
      node.setAttribute("data-count", String(count));
      node.textContent = "Carrinho";
    });
  }
  function product(id){ return (DATA.products || {})[id]; }
  function add(id, qty){
    var item = product(id);
    if(!item){ toast("Produto indisponível."); return; }
    if(!item.available){ toast("Este produto está esgotado."); return; }
    var cart = read(), found = null;
    cart.forEach(function(line){ if(String(line.id) === String(id)) found = line; });
    if(found){ found.qty = (Number(found.qty)||0) + (qty || 1); }
    else { cart.push({id: String(id), qty: qty || 1}); }
    write(cart);
    toast(item.name + " adicionado ao carrinho");
  }
  function toast(message){
    var node = document.querySelector(".toast");
    if(!node){ node = document.createElement("div"); node.className = "toast"; document.body.appendChild(node); }
    node.textContent = message;
    node.classList.add("show");
    clearTimeout(node._t);
    node._t = setTimeout(function(){ node.classList.remove("show"); }, 2600);
  }
  function lines(){
    return read().map(function(line){
      var item = product(line.id);
      return item ? {item: item, qty: Number(line.qty)||1} : null;
    }).filter(Boolean);
  }
  function subtotal(rows){ return rows.reduce(function(sum, row){ return sum + row.item.price * row.qty; }, 0); }
  function couponDiscount(coupon, base){
    if(!coupon || !coupon.valid) return 0;
    if(coupon.type === "percentagem") return base * (Number(coupon.value)||0) / 100;
    if(coupon.type === "valor") return Math.min(Number(coupon.value)||0, base);
    return 0;
  }
  function shippingFor(method, base){
    if(!method) return 0;
    if(couponState && couponState.valid && couponState.free_shipping) return 0;
    if(Number(method.free_above) > 0 && base >= Number(method.free_above)) return 0;
    return Number(method.price)||0;
  }
  var couponState = null, couponCode = "";
  function renderCart(){
    var host = document.getElementById("loja-carrinho");
    var listHost = document.getElementById("loja-linhas");
    var totalsHost = document.getElementById("loja-totais");
    var conteudo = document.getElementById("loja-conteudo");
    // Sem a moldura do carrinho (página de produto) ou depois do recibo já
    // desenhado, não há nada a fazer — evita apagar a confirmação da compra.
    if(!host || !listHost || !totalsHost || !conteudo) return;
    var rows = lines();
    var formHost = document.getElementById("loja-form");
    var emptyHost = document.getElementById("loja-vazio");
    if(!rows.length){
      if(emptyHost) emptyHost.hidden = false;
      conteudo.hidden = true;
      return;
    }
    if(emptyHost) emptyHost.hidden = true;
    conteudo.hidden = false;
    listHost.innerHTML = rows.map(function(row){
      return '<div class="line" data-id="' + row.item.id + '">'
        + '<div class="thumb">' + (row.item.image_url ? '<img src="' + row.item.image_url + '" alt="">' : '<span class="ph">' + row.item.name.slice(0,2).toUpperCase() + '</span>') + '</div>'
        + '<div><div class="name"><a href="' + row.item.url + '">' + row.item.name + '</a></div>'
        + '<small>' + money(row.item.price) + ' / ' + row.item.unit + (row.item.sku ? ' · ' + row.item.sku : '') + '</small>'
        + '<div class="qty" style="margin-top:6px"><button type="button" data-step="-1">\u2212</button>'
        + '<input type="number" min="1" value="' + row.qty + '" data-qty><button type="button" data-step="1">+</button></div></div>'
        + '<div style="text-align:right"><div class="price">' + money(row.item.price * row.qty) + '</div>'
        + '<button type="button" class="remove" data-remove>remover</button></div></div>';
    }).join("");
    Array.prototype.forEach.call(listHost.querySelectorAll(".line"), function(node){
      var id = node.getAttribute("data-id");
      node.querySelector("[data-remove]").onclick = function(){
        write(read().filter(function(line){ return String(line.id) !== String(id); }));
      };
      Array.prototype.forEach.call(node.querySelectorAll("[data-step]"), function(button){
        button.onclick = function(){
          var delta = Number(button.getAttribute("data-step"));
          var cart = read();
          cart.forEach(function(line){ if(String(line.id) === String(id)) line.qty = Math.max(1, (Number(line.qty)||1) + delta); });
          write(cart);
        };
      });
      var input = node.querySelector("[data-qty]");
      input.onchange = function(){
        var value = Math.max(1, Number(input.value)||1);
        var cart = read();
        cart.forEach(function(line){ if(String(line.id) === String(id)) line.qty = value; });
        write(cart);
      };
    });
    var base = subtotal(rows);
    var selected = formHost ? formHost.querySelector("[name=shipping_method_id]:checked") : null;
    var method = selected ? DATA.shipping.filter(function(item){ return String(item.id) === selected.value; })[0] : DATA.shipping[0];
    var discount = couponDiscount(couponState, base);
    var shipping = shippingFor(method, base - discount);
    var total = Math.max(0, base - discount + shipping);
    totalsHost.innerHTML =
      '<div><span>Subtotal</span><span>' + money(base) + '</span></div>'
      + (discount ? '<div><span>Desconto ' + (couponState.code||"") + '</span><span>\u2212' + money(discount) + '</span></div>' : '')
      + '<div><span>Portes' + (method ? ' (' + method.name + ')' : '') + '</span><span>' + (shipping ? money(shipping) : 'grátis') + '</span></div>'
      + '<div class="grand"><span>Total (IVA incluído)</span><span>' + money(total) + '</span></div>';
    var submit = document.getElementById("loja-submeter");
    if(submit) submit.textContent = "Finalizar encomenda · " + money(total);
  }
  function validateCoupon(code){
    var rows = lines();
    if(!code){ couponState = null; couponCode = ""; renderCart(); return; }
    fetch(DATA.urls.coupon, {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({code: code, items: rows.map(function(row){ return {product_id: row.item.id, quantity: row.qty}; })})})
      .then(function(r){ return r.json(); })
      .then(function(payload){
        couponState = payload.valid ? payload : null;
        couponCode = payload.valid ? code : "";
        var notice = document.getElementById("loja-cupao-aviso");
        if(notice){ notice.textContent = payload.valid ? (payload.description || "Cupão aplicado.") : payload.error; notice.className = "notice " + (payload.valid ? "ok" : "error"); notice.hidden = false; }
        renderCart();
      })
      .catch(function(){ toast("Não foi possível validar o cupão."); });
  }
  function submitOrder(event){
    event.preventDefault();
    var form = event.target;
    var rows = lines();
    if(!rows.length){ toast("O carrinho está vazio."); return; }
    var button = document.getElementById("loja-submeter");
    if(button) button.disabled = true;
    var data = new FormData(form);
    var payload = {
      items: rows.map(function(row){ return {product_id: row.item.id, quantity: row.qty}; }),
      coupon_code: couponCode,
      shipping_method_id: data.get("shipping_method_id") || "",
      payment_method: data.get("payment_method") || "transferencia",
      notes: data.get("notes") || "",
      customer: {
        name: data.get("name") || "", email: data.get("email") || "", phone: data.get("phone") || "",
        tax_id: data.get("tax_id") || "", company: data.get("company") || ""
      },
      shipping_address: {
        name: data.get("name") || "", line1: data.get("line1") || "", line2: data.get("line2") || "",
        postal_code: data.get("postal_code") || "", city: data.get("city") || "", country: data.get("country") || "Portugal",
        phone: data.get("phone") || ""
      },
      billing: {
        name: data.get("name") || "", line1: data.get("line1") || "", line2: data.get("line2") || "",
        postal_code: data.get("postal_code") || "", city: data.get("city") || "", country: data.get("country") || "Portugal"
      },
      marketing: data.get("marketing") ? true : false
    };
    fetch(DATA.urls.checkout, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)})
      .then(function(response){ return response.json().then(function(body){ return {ok: response.ok, body: body}; }); })
      .then(function(result){
        if(button) button.disabled = false;
        if(!result.ok){ var detail = (result.body && result.body.detail) || "Não foi possível concluir a encomenda."; toast(detail); var box = document.getElementById("loja-aviso"); if(box){ box.textContent = detail; box.className = "notice error"; box.hidden = false; } return; }
        write([]);
        couponState = null; couponCode = "";
        showReceipt(result.body.order, result.body);
      })
      .catch(function(){ if(button) button.disabled = false; toast("Falha de rede ao finalizar a encomenda."); });
  }
  function showReceipt(order, payload){
    var host = document.getElementById("loja-carrinho");
    if(!host) return;
    var emptyHost = document.getElementById("loja-vazio");
    if(emptyHost) emptyHost.hidden = true;
    var rows = (order.items || []).map(function(line){
      return '<tr><td>' + line.name + ' <small>× ' + line.quantity + '</small></td><td>' + money(line.unit_price * line.quantity) + '</td></tr>';
    }).join("");
    host.innerHTML = '<div class="receipt" style="grid-column:1/-1">'
      + '<div class="num">Encomenda ' + order.number + '</div>'
      + '<p class="muted">Obrigado! Enviámos a confirmação para <strong>' + ((order.customer||{}).email||"") + '</strong>.</p>'
      + '<table><thead><tr><th>Produto</th><th>Total</th></tr></thead><tbody>' + rows + '</tbody></table>'
      + '<div class="totals"><div><span>Subtotal</span><span>' + money(order.subtotal) + '</span></div>'
      + (order.discount_total ? '<div><span>Desconto</span><span>\u2212' + money(order.discount_total) + '</span></div>' : '')
      + '<div><span>Portes</span><span>' + (order.shipping_total ? money(order.shipping_total) : "grátis") + '</span></div>'
      + '<div class="grand"><span>Total</span><span>' + money(order.total) + '</span></div></div>'
      + '<div class="notice">Pagamento: <strong>' + (order.payment_label || "") + '</strong>. ' + (order.payment_instructions || '') + '</div>'
      + '<p><a class="btn ghost small" href="' + payload.store_url + '">Continuar a comprar</a></p></div>';
    window.scrollTo({top: 0, behavior: "smooth"});
  }
  document.addEventListener("loja:carrinho", renderCart);
  document.addEventListener("click", function(event){
    var node = event.target.closest("[data-add-to-cart]");
    if(node){ event.preventDefault(); add(node.getAttribute("data-add-to-cart"), 1); }
    var buy = event.target.closest("[data-buy-now]");
    if(buy){ event.preventDefault(); add(buy.getAttribute("data-buy-now"), Number((document.getElementById("loja-qtd")||{}).value)||1); window.location.href = DATA.urls.cart; }
  });
  document.addEventListener("change", function(event){
    if(event.target.name === "shipping_method_id") renderCart();
  });
  document.addEventListener("submit", function(event){
    if(event.target.id === "loja-form") submitOrder(event);
    if(event.target.id === "loja-avaliacao") submitReview(event);
  });
  function submitReview(event){
    event.preventDefault();
    var form = event.target;
    var data = new FormData(form);
    fetch(DATA.urls.review, {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        product_id: data.get("product_id"), customer_name: data.get("customer_name"),
        email: data.get("email"), rating: Number(data.get("rating"))||5,
        title: data.get("title"), body: data.get("body")
      })})
      .then(function(response){ return response.json().then(function(body){ return {ok: response.ok, body: body}; }); })
      .then(function(result){
        var box = document.getElementById("loja-avaliacao-aviso");
        if(!box) return;
        if(result.ok){ box.textContent = "Obrigado! A sua avaliação vai ser publicada depois de revista."; box.className = "notice ok"; form.reset(); }
        else { box.textContent = (result.body && result.body.detail) || "Não foi possível enviar a avaliação."; box.className = "notice error"; }
        box.hidden = false;
      })
      .catch(function(){ toast("Falha de rede ao enviar a avaliação."); });
  }
  var couponButton = document.getElementById("loja-aplicar-cupao");
  if(couponButton) couponButton.onclick = function(){ validateCoupon((document.getElementById("loja-cupao")||{}).value || ""); };
  badge();
  renderCart();
})();
"""


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------
def _data_payload(settings: Dict[str, Any], products: List[Dict[str, Any]], shipping: List[Dict[str, Any]]) -> str:
    payload = {
        "cart_key": _CART_KEY,
        "currency": settings.get("currency") or "EUR",
        "products": {str(item["id"]): item for item in products},
        "shipping": shipping,
        "urls": {"cart": "/loja/carrinho", "checkout": "/loja/encomendas", "coupon": "/loja/cupoes/validar", "review": "/loja/avaliacoes"},
        "prices_include_tax": bool(settings.get("prices_include_tax", True)),
    }
    return json.dumps(payload, ensure_ascii=False)


def _header(settings: Dict[str, Any], *, current_path: str = "", preview: bool = False) -> str:
    categories = store.public_categories()
    nav = ['<a href="/loja">Catálogo</a>']
    for category in categories[:5]:
        nav.append(f'<a href="/loja/categoria/{_esc(category.get("slug"))}">{_esc(category.get("name"))}</a>')
    nav.append('<a href="/loja/produtos">Todos os produtos</a>')
    tagline = f'<small>{_esc(settings.get("tagline"))}</small>' if settings.get("tagline") else ""
    banner = '<div class="notice warn" style="border-radius:0;margin:0">Pré-visualização — ainda não publicado</div>' if preview else ""
    return (
        banner
        + '<header class="site-header"><div class="wrap">'
        + f'<a class="brand" href="/loja">{_esc(settings.get("store_name"))}{tagline}</a>'
        + f'<nav>{"".join(nav)}</nav>'
        + '<div class="header-tools">'
        + '<form class="search" method="get" action="/loja/produtos">'
        + f'<input type="text" name="q" placeholder="Procurar produtos…" value="{_esc(_query_of(current_path))}">'
        + '<button class="btn small ghost" type="submit">Procurar</button></form>'
        + '<a class="cart-pill" href="/loja/carrinho" data-cart-count data-count="0">Carrinho</a>'
        + "</div></div></header>"
    )


def _query_of(path: str) -> str:
    if "q=" not in (path or ""):
        return ""
    from urllib.parse import parse_qs, urlparse

    try:
        return (parse_qs(urlparse(path).query).get("q") or [""])[0]
    except Exception:  # pragma: no cover - caminho invulgar
        return ""


def _social_links(settings: Dict[str, Any]) -> str:
    labels = {"email": "Email", "linkedin": "LinkedIn", "x": "X", "github": "GitHub"}
    parts = []
    for key, label in labels.items():
        value = str((settings.get("social") or {}).get(key) or "").strip()
        if not value:
            continue
        href = f"mailto:{value}" if key == "email" else value
        parts.append(f'<a href="{_esc(href)}">{label}</a>')
    return "".join(parts)


def _footer(settings: Dict[str, Any]) -> str:
    contacts = []
    if settings.get("email"):
        contacts.append(f'<a href="mailto:{_esc(settings["email"])}">{_esc(settings["email"])}</a>')
    if settings.get("phone"):
        contacts.append(f'<a href="tel:{_esc(str(settings["phone"]).replace(" ", ""))}">{_esc(settings["phone"])}</a>')
    if settings.get("address"):
        contacts.append(f'<span>{_esc(settings["address"])}</span>')
    return (
        '<footer class="site-footer"><div class="wrap">'
        f'<div><strong>{_esc(settings.get("store_name"))}</strong><br>{_esc(settings.get("footer_text") or "")}'
        + (f'<br><small>NIF {_esc(settings.get("tax_id"))}</small>' if settings.get("tax_id") else "")
        + "</div>"
        + f'<nav>{"".join(contacts)}{_social_links(settings)}<a href="/loja/produtos">Produtos</a><a href="/loja/carrinho">Carrinho</a></nav>'
        + "</div></footer>"
    )


def _layout(
    *,
    title: str,
    description: str,
    body: str,
    settings: Dict[str, Any],
    products: List[Dict[str, Any]],
    shipping: List[Dict[str, Any]],
    canonical: str = "",
    og_type: str = "website",
    og_image: str = "",
    keywords: Optional[List[str]] = None,
    json_ld: Optional[Dict[str, Any]] = None,
    preview: bool = False,
    noindex: bool = False,
) -> str:
    store_name = _esc(settings.get("store_name") or "Loja")
    full_title = f"{title} · {store_name}" if title and store_name not in title else (title or store_name)
    base_url = str(settings.get("base_url") or "")
    canonical_url = canonical or "/loja"
    if base_url and not canonical_url.startswith("http"):
        canonical_url = f"{base_url.rstrip('/')}{canonical_url}"
    robots = "noindex, nofollow" if (noindex or preview) else str(settings.get("robots") or "index, follow")
    meta = [
        f'<meta name="description" content="{_esc(description)}">',
        f'<meta name="robots" content="{_esc(robots)}">',
        f'<link rel="canonical" href="{_esc(canonical_url)}">',
        '<meta property="og:site_name" content="' + store_name + '">',
        f'<meta property="og:type" content="{_esc(og_type)}">',
        f'<meta property="og:title" content="{_esc(full_title)}">',
        f'<meta property="og:description" content="{_esc(description)}">',
        f'<meta property="og:url" content="{_esc(canonical_url)}">',
        '<meta name="twitter:card" content="summary_large_image">',
    ]
    if og_image:
        meta.append(f'<meta property="og:image" content="{_esc(og_image)}">')
    if keywords:
        meta.append(f'<meta name="keywords" content="{_esc(", ".join(keywords))}">')
    if json_ld:
        meta.append(f'<script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>')
    analytics = str(settings.get("analytics_id") or "").strip()
    if analytics and not preview:
        meta.append(
            '<script async src="https://www.googletagmanager.com/gtag/js?id=' + _esc(analytics) + '"></script>'
            '<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag("js",new Date());gtag("config","' + _esc(analytics) + '");</script>'
        )
    data = _data_payload(settings, products, shipping)
    return (
        '<!doctype html><html lang="' + _esc(str(settings.get("language") or "pt-PT")) + '">'
        '<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(full_title)}</title>"
        + "".join(meta)
        + f"<style>{_css(settings)}</style></head><body>"
        + _header(settings, preview=preview)
        + f'<main><div class="wrap">{body}</div></main>'
        + _footer(settings)
        + f'<script type="application/json" id="loja-dados">{data}</script>'
        + f"<script>{_CART_JS}</script></body></html>"
    )


# --------------------------------------------------------------------------
# Cartões e catálogo
# --------------------------------------------------------------------------
def _price_block(product: Dict[str, Any]) -> str:
    compare = store.money(product.get("compare_at_price"))
    price = store.money(product.get("price"))
    if compare > price:
        return f'<div class="price">{_euros(price)} <del>{_euros(compare)}</del></div>'
    return f'<div class="price">{_euros(price)}</div>'


def _card_badges(product: Dict[str, Any]) -> str:
    badges = []
    if store.money(product.get("compare_at_price")) > store.money(product.get("price")):
        badges.append('<span class="badge sale">Promoção</span>')
    if store._bool(product.get("featured"), False):
        badges.append('<span class="badge good">Destaque</span>')
    if product.get("type") == "digital":
        badges.append('<span class="badge">Digital</span>')
    if not product.get("available"):
        badges.append('<span class="badge out">Esgotado</span>')
    elif store._bool(product.get("track_stock"), False) and store._int(product.get("stock")) > 0 and store._int(product.get("stock")) <= store._int(store.get_settings().get("low_stock_threshold"), 5):
        badges.append(f'<span class="badge warn">{_esc(product.get("stock_label") or "Stock baixo")}</span>')
    return f'<div class="badges">{"".join(badges)}</div>' if badges else ""


def _product_card(product: Dict[str, Any], settings: Dict[str, Any]) -> str:
    disabled = "" if product.get("available") else " disabled"
    label = "Adicionar" if product.get("available") else "Esgotado"
    rating = ""
    if store._int(product.get("rating_count")):
        rating = _stars(store.money(product.get("rating_avg")), store._int(product.get("rating_count")))
    return (
        '<article class="card">'
        + f'<a class="thumb" href="{_esc(product.get("url"))}">{_image(str(product.get("image_url") or ""), str(product.get("name") or ""), str(product.get("name") or ""))}</a>'
        + '<div class="body">'
        + _card_badges(product)
        + f'<a class="name" href="{_esc(product.get("url"))}">{_esc(product.get("name"))}</a>'
        + f'<p class="desc">{_esc(product.get("short_description") or "")}</p>'
        + rating
        + _price_block(product)
        + f'<div class="toolbar" style="margin:0"><button class="btn small" type="button" data-add-to-cart="{_esc(product.get("id"))}"{disabled}>{label}</button>'
        + f'<a class="btn small ghost" href="{_esc(product.get("url"))}">Ver ficha</a></div>'
        + "</div></article>"
    )


def _catalogue_body(
    products: List[Dict[str, Any]],
    *,
    settings: Dict[str, Any],
    categories: List[Dict[str, Any]],
    current_category: Optional[Dict[str, Any]] = None,
    query: str = "",
    tag: str = "",
    page: int = 1,
    pages: int = 1,
    sort: str = "destaque",
    title: str = "Produtos",
    description: str = "",
) -> str:
    chips = ['<a class="chip%s" href="/loja/produtos">Todos</a>' % (" active" if not current_category and not tag and not query else "")]
    for category in categories:
        active = " active" if current_category and current_category.get("id") == category.get("id") else ""
        chips.append(f'<a class="chip{active}" href="/loja/categoria/{_esc(category.get("slug"))}">{_esc(category.get("name"))} ({store._int(category.get("products"))})</a>')
    sorts = "".join(
        f'<option value="{_esc(option["id"])}"{" selected" if option["id"] == sort else ""}>{_esc(option["label"])}</option>'
        for option in store.SORT_OPTIONS
    )
    head = f"<h1>{_esc(title)}</h1>" + (f'<p class="muted">{_esc(description)}</p>' if description else "")
    if query:
        head += f'<p class="muted">Resultados para <strong>{_esc(query)}</strong>.</p>'
    if tag:
        head += f'<p class="muted">Produtos com a etiqueta <strong>{_esc(tag)}</strong>.</p>'
    body = [head, f'<div class="toolbar"><div class="chips">{"".join(chips)}</div><div style="margin-left:auto">'
            f'<form method="get" action="/loja/produtos" style="display:flex;gap:8px;align-items:center">'
            f'<input type="hidden" name="q" value="{_esc(query)}">'
            f'<select name="ordenar" onchange="this.form.submit()">{sorts}</select></form></div></div>']
    if not products:
        body.append('<div class="empty"><p>Não encontrámos produtos com estes critérios.</p><p><a class="btn ghost small" href="/loja/produtos">Ver todos os produtos</a></p></div>')
    else:
        body.append('<div class="grid">' + "".join(_product_card(product, settings) for product in products) + "</div>")
    if pages > 1:
        links = []
        for number in range(1, pages + 1):
            if number in (1, pages) or abs(number - page) <= 2:
                css = "on" if number == page else ""
                params = f"?pagina={number}"
                if current_category:
                    params = f"?pagina={number}"
                if query:
                    params += f"&q={_esc(query)}"
                if tag:
                    params += f"&etiqueta={_esc(tag)}"
                base = f"/loja/categoria/{_esc(current_category.get('slug'))}" if current_category else "/loja/produtos"
                links.append(f'<a class="{css}" href="{base}{params}">{number}</a>')
            elif links and links[-1] != "<span>…</span>":
                links.append("<span>…</span>")
        body.append('<div class="pager">' + "".join(links) + "</div>")
    return "".join(body)


def render_catalogue(
    products: List[Dict[str, Any]],
    *,
    settings: Optional[Dict[str, Any]] = None,
    categories: Optional[List[Dict[str, Any]]] = None,
    current_category: Optional[Dict[str, Any]] = None,
    query: str = "",
    tag: str = "",
    page: int = 1,
    pages: int = 1,
    sort: str = "destaque",
    title: str = "Loja",
    description: str = "",
    all_products: Optional[List[Dict[str, Any]]] = None,
) -> str:
    settings = settings or store.get_settings()
    categories = categories if categories is not None else store.public_categories()
    body = _catalogue_body(
        products,
        settings=settings,
        categories=categories,
        current_category=current_category,
        query=query,
        tag=tag,
        page=page,
        pages=pages,
        sort=sort,
        title=title,
        description=description or str(settings.get("description") or ""),
    )
    canonical = f"/loja/categoria/{current_category.get('slug')}" if current_category else "/loja/produtos"
    if page > 1:
        canonical += f"?pagina={page}"
    json_ld = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": title,
        "numberOfItems": len(products),
        "itemListElement": [
            {"@type": "ListItem", "position": index + 1, "url": str(product.get("url") or ""), "name": product.get("name")}
            for index, product in enumerate(products[:20])
        ],
    }
    return _layout(
        title=title,
        description=description or str(settings.get("description") or ""),
        body=body,
        settings=settings,
        products=all_products if all_products is not None else products,
        shipping=store.public_shipping_methods(),
        canonical=canonical,
        json_ld=json_ld,
    )


# --------------------------------------------------------------------------
# Ficha de produto
# --------------------------------------------------------------------------
def render_product(
    product: Dict[str, Any],
    *,
    settings: Optional[Dict[str, Any]] = None,
    reviews: Optional[List[Dict[str, Any]]] = None,
    related: Optional[List[Dict[str, Any]]] = None,
) -> str:
    settings = settings or store.get_settings()
    reviews = reviews if reviews is not None else store.approved_reviews(str(product.get("id")))
    related = related if related is not None else store.related_products(product)
    images = store.image_urls(product) or [""]
    gallery = (
        '<div class="gallery"><div class="main" id="loja-imagem">'
        + _image(images[0], str(product.get("name") or ""), str(product.get("name") or ""))
        + "</div>"
        + ('<div class="thumbs">' + "".join(
            f'<img src="{_esc(url)}" alt="" onclick="document.getElementById(\'loja-imagem\').firstElementChild.src=this.src">' for url in images[1:6]
        ) + "</div>" if len(images) > 1 else "")
        + "</div>"
    )
    attributes = "".join(
        f'<div><span>{_esc(attribute.get("label"))}</span><span>{_esc(attribute.get("value"))}</span></div>'
        for attribute in product.get("attributes") or []
    )
    stock_notice = ""
    if not product.get("available"):
        stock_notice = '<div class="notice warn">Este produto está esgotado.</div>'
    elif store._bool(product.get("track_stock"), False):
        stock_notice = f'<div class="notice">{_esc(product.get("stock_label") or "Em stock")}</div>'
    buy = (
        '<div class="buy">'
        + _card_badges(product)
        + f'<h1>{_esc(product.get("name"))}</h1>'
        + (f'<p class="muted">{_esc(product.get("short_description"))}</p>' if product.get("short_description") else "")
        + ('<div>' + _stars(store.money(product.get("rating_avg")), store._int(product.get("rating_count"))) + "</div>" if store._int(product.get("rating_count")) else "")
        + _price_block(product)
        + f'<small>IVA incluído · por {_esc(product.get("unit") or "un")}</small>'
        + (f'<div class="attributes">{attributes}</div>' if attributes else "")
        + stock_notice
        + '<div class="toolbar" style="margin-top:12px">'
        + '<div class="qty"><button type="button" onclick="var f=document.getElementById(\'loja-qtd\');f.value=Math.max(1,Number(f.value)-1)">−</button>'
        + f'<input id="loja-qtd" type="number" min="1" value="1"{" disabled" if not product.get("available") else ""}>'
        + '<button type="button" onclick="var f=document.getElementById(\'loja-qtd\');f.value=Number(f.value)+1">+</button></div>'
        + f'<button class="btn" type="button" data-buy-now="{_esc(product.get("id"))}"{" disabled" if not product.get("available") else ""}>Comprar</button>'
        + f'<button class="btn ghost" type="button" data-add-to-cart="{_esc(product.get("id"))}"{" disabled" if not product.get("available") else ""}>Adicionar ao carrinho</button>'
        + "</div>"
        + (f'<p><small>Referência {_esc(product.get("sku"))}</small></p>' if product.get("sku") else "")
        + "</div>"
    )
    review_cards = "".join(
        '<article class="review">'
        + f'<div>{_stars(store._int(review.get("rating")), 0)}</div>'
        + f'<strong>{_esc(review.get("title") or "")}</strong>'
        + f'<p>{_esc(review.get("body") or "")}</p>'
        + f'<small>{_esc(review.get("customer_name"))} · {_esc(_date(review.get("created_at")))}</small>'
        + "</article>"
        for review in reviews
    )
    review_form = ""
    if store._bool(settings.get("allow_reviews", True), True):
        review_form = (
            '<section class="block"><h2>Deixar avaliação</h2>'
            '<form id="loja-avaliacao" class="field-grid" style="max-width:640px">'
            f'<input type="hidden" name="product_id" value="{_esc(product.get("id"))}">'
            '<label>Nome<input type="text" name="customer_name" required></label>'
            '<label>Email<input type="email" name="email"></label>'
            '<label>Nota<select name="rating"><option value="5">5 — Excelente</option><option value="4">4 — Bom</option>'
            '<option value="3">3 — Razoável</option><option value="2">2 — Fraco</option><option value="1">1 — Mau</option></select></label>'
            '<label>Título<input type="text" name="title"></label>'
            '<label class="wide">Comentário<textarea name="body" rows="4"></textarea></label>'
            '<div class="wide"><button class="btn" type="submit">Enviar avaliação</button></div>'
            "</form>"
            '<div id="loja-avaliacao-aviso" class="notice" hidden></div></section>'
        )
    body = (
        f'<p class="muted" style="margin-top:14px"><a href="/loja/produtos">Produtos</a> › {_esc(product.get("name"))}</p>'
        + '<div class="product">' + gallery + buy + "</div>"
        + (f'<section class="block"><h2>Descrição</h2><div class="prose">{_md(str(product.get("description") or ""))}</div></section>' if product.get("description") else "")
        + (f'<section class="block"><h2>Avaliações de clientes</h2><div class="reviews">{review_cards}</div></section>' if review_cards else "")
        + review_form
        + (
            '<section class="block"><h2>Também pode gostar</h2><div class="grid">'
            + "".join(_product_card(item, settings) for item in related)
            + "</div></section>"
            if related
            else ""
        )
    )
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.get("name"),
        "sku": product.get("sku"),
        "description": product.get("short_description") or store.text_excerpt(str(product.get("description") or "")),
        "image": [str(url) for url in images if url],
        "offers": {
            "@type": "Offer",
            "price": store.money(product.get("price")),
            "priceCurrency": settings.get("currency") or "EUR",
            "availability": "https://schema.org/InStock" if product.get("available") else "https://schema.org/OutOfStock",
            "url": f"/loja/produto/{product.get('slug')}",
        },
    }
    if store._int(product.get("rating_count")):
        json_ld["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": store.money(product.get("rating_avg")),
            "reviewCount": store._int(product.get("rating_count")),
        }
    return _layout(
        title=f'{product.get("name")} — {_euros(product.get("price"))}',
        description=str(product.get("short_description") or store.text_excerpt(str(product.get("description") or ""))),
        body=body,
        settings=settings,
        products=[store.product_payload(product)] + related,
        shipping=store.public_shipping_methods(),
        canonical=f"/loja/produto/{product.get('slug')}",
        og_type="product",
        og_image=images[0] if images and images[0] else "",
        json_ld=json_ld,
    )


# --------------------------------------------------------------------------
# Carrinho e finalização
# --------------------------------------------------------------------------
def render_cart(*, settings: Optional[Dict[str, Any]] = None, products: Optional[List[Dict[str, Any]]] = None) -> str:
    settings = settings or store.get_settings()
    catalog = products if products is not None else store.public_products(limit=400)
    shipping = store.public_shipping_methods()
    shipping_options = "".join(
        f'<label><input type="radio" name="shipping_method_id" value="{_esc(method["id"])}"{" checked" if index == 0 else ""}>'
        f'<span>{_esc(method["name"])} — {"grátis" if not method["price"] else _euros(method["price"])}'
        + (f' <small>(grátis acima de {_euros(method["free_above"])})</small>' if method.get("free_above") else "")
        + (f' <small>· {store._int(method.get("days_min"))}–{store._int(method.get("days_max"))} dias</small>' if method.get("days_max") else "")
        + "</span></label>"
        for index, method in enumerate(shipping)
    )
    payment_settings = settings.get("payments") or {}
    payment_options = "".join(
        f'<label><input type="radio" name="payment_method" value="{_esc(method["id"])}"{" checked" if index == 0 else ""}>'
        f'<span>{_esc(method["label"])} <small>{_esc(method["hint"])}</small></span></label>'
        for index, method in enumerate(method for method in store.PAYMENT_METHODS if store._bool(payment_settings.get(method["id"]), False))
    ) or '<p class="notice warn">Não há métodos de pagamento ativos. Contacte a loja.</p>'
    body = (
        "<h1>Carrinho</h1>"
        '<div class="empty" id="loja-vazio" hidden><p>O seu carrinho está vazio.</p>'
        '<p><a class="btn small" href="/loja/produtos">Ver produtos</a></p></div>'
        '<div class="cart" id="loja-carrinho"><div id="loja-conteudo">'
        '<div><div class="lines" id="loja-linhas"></div>'
        '<div class="coupon"><input type="text" id="loja-cupao" placeholder="Código de desconto">'
        '<button class="btn ghost" type="button" id="loja-aplicar-cupao">Aplicar</button></div>'
        '<div id="loja-cupao-aviso" class="notice" hidden></div></div>'
        '<aside class="cart-side">'
        '<div id="loja-totais" class="totals"></div>'
        f'<form id="loja-form" class="field-grid">'
        '<label>Nome<input type="text" name="name" required></label>'
        '<label>Email<input type="email" name="email" required></label>'
        '<label>Telefone<input type="tel" name="phone"></label>'
        '<label>NIF<input type="text" name="tax_id"></label>'
        '<label class="wide">Empresa<input type="text" name="company"></label>'
        '<label class="wide">Morada<input type="text" name="line1" required></label>'
        '<label class="wide">Complemento<input type="text" name="line2"></label>'
        '<label>Código postal<input type="text" name="postal_code"></label>'
        '<label>Localidade<input type="text" name="city"></label>'
        '<label class="wide">País<input type="text" name="country" value="Portugal"></label>'
        f'<div class="wide"><p class="muted" style="margin:14px 0 6px">Envio</p><div class="pay">{shipping_options}</div></div>'
        f'<div class="wide"><p class="muted" style="margin:14px 0 6px">Pagamento</p><div class="pay">{payment_options}</div></div>'
        '<label class="wide">Notas para a loja<textarea name="notes" rows="3"></textarea></label>'
        '<label class="wide"><span><input type="checkbox" name="marketing"> Quero receber novidades por email</span></label>'
        '<div class="wide"><button class="btn" type="submit" id="loja-submeter">Finalizar encomenda</button></div>'
        "</form>"
        '<div id="loja-aviso" class="notice" hidden></div>'
        '<p><small>Os valores são recalculados no servidor antes de a encomenda ser criada.</small></p>'
        "</aside></div></div>"
    )
    return _layout(
        title="Carrinho",
        description="Reveja o carrinho e conclua a encomenda.",
        body=body,
        settings=settings,
        products=[store.product_payload(product) for product in catalog],
        shipping=shipping,
        canonical="/loja/carrinho",
        noindex=True,
    )


def render_order(order: Dict[str, Any], *, settings: Optional[Dict[str, Any]] = None) -> str:
    settings = settings or store.get_settings()
    lines = "".join(
        f'<tr><td>{_esc(line.get("name"))} <small>× {store._int(line.get("quantity"))}</small><br><small>{_esc(line.get("sku"))}</small></td>'
        f'<td>{_euros(store.money(line.get("unit_price")) * store._int(line.get("quantity")))}</td></tr>'
        for line in order.get("items") or []
    )
    totals = order.get("totals") or store.order_totals(order)
    timeline = "".join(
        f'<li>{_esc(_date(step.get("at"), with_time=True))} — {_esc(store.ORDER_LABELS.get(str(step.get("status")), str(step.get("status"))))}'
        + (f' <small>{_esc(step.get("note"))}</small>' if step.get("note") else "")
        + "</li>"
        for step in order.get("timeline") or []
    )
    payment = order.get("payment") or {}
    body = (
        '<div class="receipt" style="margin:22px 0">'
        f'<div class="num">Encomenda {_esc(order.get("number"))}</div>'
        f'<p class="muted">Feita a {_esc(_date(order.get("placed_at"), with_time=True))} · '
        f'estado <strong>{_esc(store.ORDER_LABELS.get(str(order.get("status")), ""))}</strong> · '
        f'pagamento <strong>{_esc(store.PAYMENT_LABELS.get(str(payment.get("status")), ""))}</strong></p>'
        f'<table><thead><tr><th>Produto</th><th>Total</th></tr></thead><tbody>{lines}</tbody></table>'
        '<div class="totals">'
        f'<div><span>Subtotal</span><span>{_euros(totals.get("subtotal"))}</span></div>'
        + (f'<div><span>Desconto {_esc(order.get("coupon_code"))}</span><span>−{_euros(totals.get("discount_total"))}</span></div>' if store.money(totals.get("discount_total")) else "")
        + f'<div><span>Portes</span><span>{_euros(totals.get("shipping_total")) if store.money(totals.get("shipping_total")) else "grátis"}</span></div>'
        + f'<div class="grand"><span>Total (IVA incluído)</span><span>{_euros(totals.get("total"))}</span></div>'
        "</div>"
        + f'<div class="notice">{(settings.get("payment_instructions") or {}).get(str(payment.get("method")), "")}</div>'
        + (f'<section class="block"><h2>Seguimento</h2><ul>{timeline}</ul></section>' if timeline else "")
        + '<p><a class="btn ghost small" href="/loja/produtos">Continuar a comprar</a></p>'
        "</div>"
    )
    return _layout(
        title=f'Encomenda {order.get("number")}',
        description=f'Detalhe da encomenda {order.get("number")}.',
        body=body,
        settings=settings,
        products=[],
        shipping=store.public_shipping_methods(),
        canonical=f'/loja/encomenda/{order.get("number")}',
        noindex=True,
    )


def render_not_found(*, settings: Optional[Dict[str, Any]] = None, message: str = "") -> str:
    settings = settings or store.get_settings()
    body = (
        '<div class="empty" style="margin:40px 0"><h1>Não encontrámos esta página</h1>'
        f'<p>{_esc(message or "O produto ou a encomenda que procura pode já não estar disponível.")}</p>'
        '<p><a class="btn small" href="/loja/produtos">Ver produtos</a></p></div>'
    )
    return _layout(
        title="Página não encontrada",
        description="Conteúdo indisponível.",
        body=body,
        settings=settings,
        products=[],
        shipping=store.public_shipping_methods(),
        canonical="/loja",
        noindex=True,
    )


# --------------------------------------------------------------------------
# Sitemap e robots
# --------------------------------------------------------------------------
def render_sitemap(*, settings: Optional[Dict[str, Any]] = None) -> str:
    settings = settings or store.get_settings()
    base = str(settings.get("base_url") or "").rstrip("/")
    urls = ["/loja", "/loja/produtos"]
    for category in store.public_categories():
        urls.append(f'/loja/categoria/{category.get("slug")}')
    for product in store.public_products(limit=1000):
        urls.append(str(product.get("url")))
    entries = "".join(f"<url><loc>{_esc(base + url)}</loc></url>" for url in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + entries + "</urlset>"
    )


def render_robots(*, settings: Optional[Dict[str, Any]] = None) -> str:
    settings = settings or store.get_settings()
    base = str(settings.get("base_url") or "").rstrip("/")
    lines = ["User-agent: *", "Disallow: /shop", "Disallow: /loja/carrinho", "Disallow: /loja/encomenda"]
    if base:
        lines.append(f"Sitemap: {base}/loja/sitemap.xml")
    return "\n".join(lines) + "\n"
