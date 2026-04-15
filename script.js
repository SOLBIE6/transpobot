const API = 'https://transpobot-production-433d.up.railway.app';

// Clock
function tick() {
    document.getElementById('clock').textContent = new Date().toLocaleTimeString('fr-FR');
}
setInterval(tick, 1000);
tick();

// Navigation
function go(id, el) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.getElementById('page-' + id).classList.add('active');
    if (el) el.classList.add('active');

    const loaders = {
        vehicules: loadV,
        chauffeurs: loadC,
        trajets: loadT,
        incidents: loadI
    };
    const key = '_' + id + 'loaded';
    if (loaders[id] && !window[key]) {
        loaders[id]();
        window[key] = true;
    }
}

// Filter rows
function filterRows(id, q) {
    const t = document.getElementById(id);
    if (!t) return;
    t.querySelectorAll('tbody tr').forEach(r => {
        r.style.display = r.textContent.toLowerCase().includes(q.toLowerCase()) ? '' : 'none';
    });
}

// Helpers
const fmt = n => n == null ? '—' : Number(n).toLocaleString('fr-FR');
const fmtDate = d => d ? new Date(d).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';
const fmtDT = d => d ? new Date(d).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—';
const badge = v => v ? `<span class="badge badge-${v}">${v.replace('_', ' ')}</span>` : '—';

async function api(path) {
    return (await fetch(API + path)).json();
}

// Stats + Dashboard
async function loadStats() {
    try {
        const d = await api('/api/stats');
        document.getElementById('k-traj').textContent = d.total_trajets ?? '—';
        document.getElementById('k-enc').textContent = d.trajets_en_cours ?? '—';
        document.getElementById('k-veh').textContent = d.vehicules_actifs ?? '—';
        document.getElementById('k-inc').textContent = d.incidents_ouverts ?? '—';
        document.getElementById('k-rec').textContent = fmt(d.recette_totale) + ' FCFA';
        document.getElementById('k-upd').textContent = new Date().toLocaleTimeString('fr-FR');
        document.getElementById('bv').textContent = d.vehicules_actifs ?? '—';

        ['cs-t', 'cs-e', 'cs-v', 'cs-i'].forEach((id, i) => {
            const el = document.getElementById(id);
            if (el) el.textContent = [d.total_trajets, d.trajets_en_cours, d.vehicules_actifs, d.incidents_ouverts][i] ?? '—';
        });
    } catch (e) { }
}

async function loadDashTrajets() {
    try {
        const data = await api('/api/trajets/recent');
        document.getElementById('bc').textContent = data.length;

        const el = document.getElementById('dash-trajets');
        if (!data.length) {
            el.innerHTML = '<div class="empty-state"><i class="fa-solid fa-inbox ei"></i>Aucun trajet récent</div>';
            return;
        }

        el.innerHTML = `<table class="data-table"><thead><tr><th>Ligne</th><th>Chauffeur</th><th>Véhicule</th><th>Départ</th><th>Statut</th></tr></thead><tbody>
            ${data.slice(0, 8).map(t => `
                <tr>
                    <td style="color:var(--text);font-weight:500">${t.ligne}</td>
                    <td>${t.chauffeur_nom}</td>
                    <td style="font-family:'Inter',monospace;font-size:0.75rem">${t.immatriculation}</td>
                    <td>${fmtDT(t.date_heure_depart)}</td>
                    <td>${badge(t.statut)}</td>
                </tr>
            `).join('')}
        </tbody></table>`;
    } catch (e) { }
}

// Véhicules, Chauffeurs, Trajets, Incidents
async function loadV() {
    try {
        const data = await api('/api/vehicules');
        let a = 0, m = 0, h = 0;
        data.forEach(v => {
            if (v.statut === 'actif') a++;
            else if (v.statut === 'maintenance') m++;
            else h++;
        });

        document.getElementById('va').textContent = a;
        document.getElementById('vm').textContent = m;
        document.getElementById('vh').textContent = h;

        document.getElementById('vwrap').innerHTML = `<table class="data-table" id="vtbl">
            <thead><tr><th>Immatriculation</th><th>Type</th><th>Capacité</th><th>Statut</th><th>Kilométrage</th><th>Acquisition</th></tr></thead>
            <tbody>${data.map(v => `
                <tr>
                    <td style="color:var(--text);font-weight:600;font-family:'Inter',monospace">${v.immatriculation}</td>
                    <td>${v.type || '—'}</td>
                    <td>${v.capacite} pl.</td>
                    <td>${badge(v.statut)}</td>
                    <td>${fmt(v.kilometrage)} km</td>
                    <td>${fmtDate(v.date_acquisition)}</td>
                </tr>
            `).join('')}</tbody></table>`;
    } catch (e) {
        document.getElementById('vwrap').innerHTML = '<div class="empty-state"><i class="fa-solid fa-triangle-exclamation ei"></i>Erreur de chargement</div>';
    }
}

async function loadC() {
    try {
        const data = await api('/api/chauffeurs');
        document.getElementById('cwrap').innerHTML = `<table class="data-table" id="ctbl">
            <thead><tr><th>Nom complet</th><th>N° Permis</th><th>Catégorie</th><th>Téléphone</th><th>Véhicule assigné</th><th>Embauche</th></tr></thead>
            <tbody>${data.map(c => `
                <tr>
                    <td style="color:var(--text);font-weight:500">${c.nom} ${c.prenom}</td>
                    <td style="font-family:'Inter',monospace;font-size:0.75rem">${c.numero_permis || '—'}</td>
                    <td>${c.categorie_permis || '—'}</td>
                    <td>${c.telephone || '—'}</td>
                    <td>${c.immatriculation ? `<span style="color:var(--accent)">${c.immatriculation}</span>` : '<span style="color:var(--text3)">Non assigné</span>'}</td>
                    <td>${fmtDate(c.date_embauche)}</td>
                </tr>
            `).join('')}</tbody></table>`;
    } catch (e) {
        document.getElementById('cwrap').innerHTML = '<div class="empty-state"><i class="fa-solid fa-triangle-exclamation ei"></i>Erreur de chargement</div>';
    }
}

async function loadT() {
    try {
        const data = await api('/api/trajets/recent');
        document.getElementById('twrap').innerHTML = `<table class="data-table" id="ttbl">
            <thead><tr><th>Ligne</th><th>Chauffeur</th><th>Véhicule</th><th>Départ</th><th>Arrivée</th><th>Statut</th><th>Recette</th></tr></thead>
            <tbody>${data.map(t => `
                <tr>
                    <td style="color:var(--text);font-weight:500">${t.ligne}</td>
                    <td>${t.chauffeur_nom}</td>
                    <td style="font-family:'Inter',monospace;font-size:0.75rem">${t.immatriculation}</td>
                    <td>${fmtDT(t.date_heure_depart)}</td>
                    <td>${t.date_heure_arrivee ? fmtDT(t.date_heure_arrivee) : '—'}</td>
                    <td>${badge(t.statut)}</td>
                    <td style="color:var(--green)">${t.recette ? fmt(t.recette) + ' F' : '—'}</td>
                </tr>
            `).join('')}</tbody></table>`;
    } catch (e) {
        document.getElementById('twrap').innerHTML = '<div class="empty-state"><i class="fa-solid fa-triangle-exclamation ei"></i>Erreur de chargement</div>';
    }
}

async function loadI() {
    try {
        const data = await api('/api/incidents');
        if (!data || !data.length) {
            document.getElementById('iwrap').innerHTML = '<div class="empty-state"><i class="fa-solid fa-check-circle ei" style="color:var(--green)"></i>Aucun incident signalé</div>';
            return;
        }
        document.getElementById('iwrap').innerHTML = `<table class="data-table" id="itbl">
            <thead><tr><th>Type</th><th>Description</th><th>Gravité</th><th>Date</th><th>Statut</th><th>Chauffeur</th></tr></thead>
            <tbody>${data.map(i => `
                <tr>
                    <td style="color:var(--text);font-weight:500">${i.type || '—'}</td>
                    <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${i.description || '—'}</td>
                    <td>${badge(i.gravite)}</td>
                    <td>${fmtDT(i.date_incident)}</td>
                    <td>${i.resolu ? '<span class="badge badge-resolu">Résolu</span>' : '<span class="badge badge-ouvert">Ouvert</span>'}</td>
                    <td>${i.chauffeur_nom || '—'}</td>
                </tr>
            `).join('')}</tbody></table>`;
    } catch (e) {
        document.getElementById('iwrap').innerHTML = '<div class="empty-state"><i class="fa-solid fa-triangle-exclamation ei"></i>Erreur de chargement</div>';
    }
}

function loadAll() {
    loadStats();
    loadDashTrajets();
}

// ====================== CHAT FUNCTIONS ======================
function ask(q) {
    document.getElementById('chat-in').value = q;
    if (!document.getElementById('page-chat').classList.contains('active'))
        go('chat', document.querySelectorAll('.nav-item')[5]);
    sendMsg();
}

function addMsg(role, html, sql = null) {
    const box = document.getElementById('chat-msgs');
    const d = document.createElement('div');
    d.className = `chat-msg ${role}`;
    d.innerHTML = `<div class="chat-av">${role === 'bot' ? '🤖' : '👤'}</div>
        <div><div class="bubble">${html}</div>${sql ? `<div class="sql-chip">${sql}</div>` : ''}</div>`;
    box.appendChild(d);
    box.scrollTop = box.scrollHeight;
}

function addLoading() {
    const box = document.getElementById('chat-msgs');
    const d = document.createElement('div');
    d.className = 'chat-msg bot _loading';
    d.innerHTML = `<div class="chat-av">🤖</div><div><div class="bubble"><div class="dots"><span></span><span></span><span></span></div></div></div>`;
    box.appendChild(d);
    box.scrollTop = box.scrollHeight;
}

async function sendMsg() {
    const inp = document.getElementById('chat-in');
    const q = inp.value.trim();
    if (!q) return;
    inp.value = '';

    addMsg('user', q);
    addLoading();

    try {
        const r = await fetch(API + '/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: q })
        });
        const d = await r.json();

        document.querySelector('._loading')?.remove();

        const cnt = d.count != null ? ` <span style="color:var(--text3);font-size:0.76em">(${d.count} résultat${d.count > 1 ? 's' : ''})</span>` : '';
        addMsg('bot', (d.answer || '—') + cnt, d.sql || null);

        if (d.data && d.data.length) {
            const box = document.getElementById('chat-msgs');
            const w = document.createElement('div');
            w.style.paddingLeft = '34px';
            const keys = Object.keys(d.data[0]);
            w.innerHTML = `<div class="res-wrap"><table><thead><tr>${keys.map(k => `<th>${k}</th>`).join('')}</tr></thead><tbody>
                ${d.data.map(row => `<tr>${keys.map(k => `<td>${row[k] ?? '—'}</td>`).join('')}</tr>`).join('')}
            </tbody></table></div>`;
            box.appendChild(w);
            box.scrollTop = box.scrollHeight;
        }
    } catch (e) {
        document.querySelector('._loading')?.remove();
        addMsg('bot', '❌ Erreur de connexion au serveur.');
    }
}

// ====================== EXEMPLES DE QUESTIONS ======================
function loadExampleQuestions() {
    const questions = [
        "Combien de trajets aujourd'hui ?",
        "Quel véhicule a le plus de km ?",
        "Chauffeurs disponibles ?",
        "Recette moyenne par trajet ?",
        "Incidents non résolus ce mois ?"
    ];

    const container = document.getElementById('examples-container');
    if (!container) return;

    container.innerHTML = questions.map(q => `
        <button class="sug" style="text-align:left; border-radius:8px; padding:6px 10px; width:100%" onclick="ask('${q.replace(/'/g, "\\'")}')">
            ${q}
        </button>
    `).join('');
}
// ==================== RESPONSIVE MENU ====================
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('open');
}

// Ajouter un bouton hamburger dans la topbar (à ajouter dans index.html si tu veux)
// Initialisation
loadAll();
loadExampleQuestions();