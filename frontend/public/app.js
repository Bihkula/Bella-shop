// Fieldkit storefront: vanilla JS talking to the gateway at /api/<service>/.
const $ = (s) => document.querySelector(s);
const money = (p, c = "GBP") =>
  new Intl.NumberFormat("en-GB", { style: "currency", currency: c }).format(p / 100);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const PALETTE_SIZE = 6; // .swatch.c0 … .c5 in style.css (CSP forbids inline styles)

const state = {
  token: sessionStorage.getItem("token"),
  cart: JSON.parse(localStorage.getItem("cart") || "{}"), // {productId: {product, qty}}
  products: [],
  payment: null,
  stripe: null,
};

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), 2800);
}

async function api(path, { method = "GET", body, auth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(`/api/${path}`, { method, headers, body: body && JSON.stringify(body) });
  if (res.status === 401 && auth) { logout(); throw new Error("Please sign in again"); }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const d = data?.detail;
    throw new Error(Array.isArray(d) ? d.map((e) => e.msg).join(", ") : d || `Error ${res.status}`);
  }
  return data;
}

// ---------- auth ----------
let registering = false;
function renderAuth() {
  $("#authBtn").textContent = state.token ? "Sign out" : "Sign in";
  document.querySelectorAll("[data-auth]").forEach((el) => (el.hidden = !state.token));
}
function logout() {
  state.token = null;
  sessionStorage.removeItem("token");
  renderAuth();
}
$("#authBtn").onclick = () => (state.token ? (logout(), toast("Signed out")) : $("#authDlg").showModal());
$("#authToggle").onclick = (e) => {
  e.preventDefault();
  registering = !registering;
  $("#authTitle").textContent = registering ? "Create account" : "Sign in";
  $("#authToggle").textContent = registering ? "Have an account? Sign in" : "New here? Create an account";
};
$("#authForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const creds = { email: f.get("email"), password: f.get("password") };
  $("#authErr").textContent = "";
  try {
    if (registering) await api("auth/register", { method: "POST", body: creds });
    const { access_token } = await api("auth/login", { method: "POST", body: creds });
    state.token = access_token;
    sessionStorage.setItem("token", access_token);
    $("#authDlg").close();
    renderAuth();
    toast("Welcome!");
    if (state.afterLogin) { const fn = state.afterLogin; state.afterLogin = null; fn(); }
  } catch (err) {
    $("#authErr").textContent = err.message;
  }
};

// ---------- cart ----------
function saveCart() { localStorage.setItem("cart", JSON.stringify(state.cart)); renderCart(); }
function addToCart(p) {
  const line = state.cart[p.id] || { product: p, qty: 0 };
  if (line.qty >= p.stock) return toast("No more in stock");
  line.qty += 1;
  state.cart[p.id] = line;
  saveCart();
  toast(`Added ${p.name}`);
}
function renderCart() {
  const lines = Object.values(state.cart);
  $("#cartCount").textContent = lines.reduce((n, l) => n + l.qty, 0);
  $("#cartTotal").textContent = money(lines.reduce((n, l) => n + l.qty * l.product.price_pence, 0));
  $("#cartLines").innerHTML = lines.length
    ? lines.map((l) => `
      <li><div><b>${esc(l.product.name)}</b><br><span class="muted small">${money(l.product.price_pence)}</span></div>
      <div class="qty"><button data-dec="${l.product.id}">−</button>${l.qty}<button data-inc="${l.product.id}">+</button></div></li>`).join("")
    : `<li class="muted">Your basket is empty.</li>`;
  $("#checkoutBtn").disabled = !lines.length;
}
$("#cartLines").onclick = (e) => {
  const id = e.target.dataset.inc || e.target.dataset.dec;
  if (!id) return;
  const line = state.cart[id];
  line.qty += e.target.dataset.inc ? 1 : -1;
  if (line.qty <= 0) delete state.cart[id];
  saveCart();
};
const openCart = (open) => $("#cart").classList.toggle("open", open);
$("#cartBtn").onclick = () => openCart(true);
$("[data-close]").onclick = () => openCart(false);

// ---------- checkout ----------
$("#checkoutBtn").onclick = () => {
  if (!state.token) { state.afterLogin = checkout; return $("#authDlg").showModal(); }
  checkout();
};

async function checkout() {
  const btn = $("#checkoutBtn");
  btn.disabled = true;
  try {
    const items = Object.values(state.cart).map((l) => ({ product_id: l.product.id, quantity: l.qty }));
    const order = await api("orders/orders", { method: "POST", body: { items }, auth: true });
    state.cart = {};
    saveCart();
    openCart(false);
    await startPayment(order);
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
}

async function startPayment(order) {
  const pay = await api(`orders/orders/${order.id}/checkout`, { method: "POST", auth: true });
  state.payment = { ...pay, order };
  $("#payAmount").textContent = `Order #${order.id} · ${money(order.total_pence, order.currency)}`;
  $("#payErr").textContent = "";
  const isStripe = pay.provider === "stripe";
  $("#mockFields").hidden = isStripe;
  $("#stripeFields").hidden = !isStripe;
  if (isStripe) await mountStripe(pay);
  $("#payDlg").showModal();
}

async function mountStripe(pay) {
  if (!window.Stripe) {
    await new Promise((ok, fail) => {
      const s = document.createElement("script");
      s.src = "https://js.stripe.com/v3/";
      s.onload = ok; s.onerror = () => fail(new Error("Could not load Stripe"));
      document.head.appendChild(s);
    });
  }
  state.stripe = window.Stripe(pay.publishable_key);
  state.elements = state.stripe.elements({ clientSecret: pay.client_secret });
  $("#payment-element").innerHTML = "";
  state.elements.create("payment").mount("#payment-element");
}

$("#payForm").onsubmit = async (e) => {
  e.preventDefault();
  const { payment } = state;
  $("#payBtn").disabled = true;
  $("#payErr").textContent = "";
  try {
    if (payment.provider === "stripe") {
      const { error } = await state.stripe.confirmPayment({
        elements: state.elements,
        confirmParams: { return_url: `${location.origin}/#/orders` },
        redirect: "if_required",
      });
      if (error) throw new Error(error.message);
      await waitForPaid(payment.order.id);   // webhook updates the order
    } else {
      const card = new FormData(e.target).get("card");
      const res = await api(`payments/payments/${payment.payment_id}/confirm`,
        { method: "POST", body: { card_number: card }, auth: true });
      if (res.status !== "succeeded") throw new Error(`Payment ${res.failure_reason?.replace(/_/g, " ") || "failed"}`);
    }
    $("#payDlg").close();
    toast("Payment received — thank you!");
    location.hash = "#/orders";
  } catch (err) {
    $("#payErr").textContent = err.message;
    // A declined mock payment needs a fresh attempt.
    if (payment.provider !== "stripe") {
      const retry = await api(`orders/orders/${payment.order.id}/checkout`, { method: "POST", auth: true }).catch(() => null);
      if (retry) state.payment = { ...retry, order: payment.order };
    }
  } finally {
    $("#payBtn").disabled = false;
  }
};

async function waitForPaid(orderId) {
  for (let i = 0; i < 15; i++) {
    const o = await api(`orders/orders/${orderId}`, { auth: true });
    if (o.status === "PAID") return;
    if (o.status === "PAYMENT_FAILED") throw new Error("Payment failed");
    await new Promise((r) => setTimeout(r, 1000));
  }
}

// ---------- views ----------
async function shopView() {
  $("#view").innerHTML = `<section class="hero"><h1>Well-made things<br>for time outside.</h1>
    <p>Small-batch goods, shipped from London.</p></section><div class="grid" id="grid"></div>`;
  try {
    state.products = await api("products/products");
  } catch (err) {
    $("#grid").innerHTML = `<p class="err">Couldn't load products: ${esc(err.message)}</p>`;
    return;
  }
  $("#grid").innerHTML = state.products.map((p, i) => `
    <article class="card">
      <div class="swatch c${i % PALETTE_SIZE}">${esc(p.name[0])}</div>
      <h3>${esc(p.name)}</h3><p>${esc(p.description)}</p>
      <div class="row"><span class="price">${money(p.price_pence, p.currency)}</span>
        <button class="primary" data-add="${p.id}" ${p.stock ? "" : "disabled"}>${p.stock ? "Add" : "Sold out"}</button></div>
      <span class="stock">${p.stock} in stock</span>
    </article>`).join("");
  $("#grid").onclick = (e) => {
    const id = Number(e.target.dataset.add);
    if (id) addToCart(state.products.find((p) => p.id === id));
  };
}

async function ordersView() {
  if (!state.token) { state.afterLogin = ordersView; $("#authDlg").showModal(); return; }
  $("#view").innerHTML = `<h1>Your orders</h1><div id="orders">Loading…</div>`;
  try {
    const orders = await api("orders/orders", { auth: true });
    $("#orders").innerHTML = orders.length ? `<table><thead><tr><th>#</th><th>Date</th><th>Items</th><th>Total</th><th>Status</th><th></th></tr></thead><tbody>
      ${orders.map((o) => `<tr><td>${o.id}</td><td>${new Date(o.created_at).toLocaleDateString("en-GB")}</td>
        <td>${o.lines.map((l) => `${l.quantity}× ${esc(l.name)}`).join(", ")}</td>
        <td>${money(o.total_pence, o.currency)}</td><td><span class="pill ${o.status}">${o.status.replace(/_/g, " ").toLowerCase()}</span></td>
        <td>${["PENDING_PAYMENT", "PAYMENT_FAILED"].includes(o.status) ? `<button data-pay="${o.id}">Pay</button>` : ""}</td></tr>`).join("")}
      </tbody></table>` : `<p class="muted">No orders yet.</p>`;
    $("#orders").onclick = async (e) => {
      const id = Number(e.target.dataset.pay);
      if (id) startPayment(orders.find((o) => o.id === id)).catch((err) => toast(err.message));
    };
  } catch (err) {
    $("#orders").innerHTML = `<p class="err">${esc(err.message)}</p>`;
  }
}

function route() { (location.hash === "#/orders" ? ordersView : shopView)(); }
window.addEventListener("hashchange", route);
renderAuth();
renderCart();
route();
