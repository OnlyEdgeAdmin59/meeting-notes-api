const I18N = {
    en: {
        tagline: 'Turn meetings into tasks that actually get done', apiKey: 'API Key',
        webhook: 'Slack Webhook URL (optional)', webhookHelp: 'Leave empty to use the channel saved on your account.',
        test: 'Test Slack connection', file: 'Upload transcript (Zoom, Meet, Teams: .vtt, .srt, .txt)',
        or: 'or paste it', extract: 'Extract & send to Slack', summary: 'Summary', tasks: 'Action items',
        decisions: 'Decisions', processing: 'Processing...', testing: 'Testing...', ok: 'Slack connection OK',
        sent: 'Sent to Slack', slackFail: 'Extracted, but sending to Slack failed', empty: 'Upload a file or paste a transcript',
        none: 'No action items found', usage: (u, l) => `${u} of ${l} meetings used this month`, unlimited: (u) => `Unlimited plan · ${u} meetings this month`
    },
    es: {
        tagline: 'Convierte tus reuniones en tareas que sí se cumplen', apiKey: 'API Key',
        webhook: 'Webhook de Slack (opcional)', webhookHelp: 'Déjalo vacío para usar el canal guardado en tu cuenta.',
        test: 'Probar conexión con Slack', file: 'Sube la transcripción (Zoom, Meet, Teams: .vtt, .srt, .txt)',
        or: 'o pégala', extract: 'Extraer y enviar a Slack', summary: 'Resumen', tasks: 'Tareas',
        decisions: 'Decisiones', processing: 'Procesando...', testing: 'Probando...', ok: 'Conexión con Slack OK',
        sent: 'Enviado a Slack', slackFail: 'Se extrajo, pero falló el envío a Slack', empty: 'Sube un archivo o pega una transcripción',
        none: 'No se encontraron tareas', usage: (u, l) => `${u} de ${l} reuniones usadas este mes`, unlimited: (u) => `Plan Ilimitado · ${u} reuniones este mes`
    }
};
const LANG = (navigator.language || 'en').toLowerCase().startsWith('es') ? 'es' : 'en';
const T = I18N[LANG];
document.documentElement.lang = LANG;
document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = T[el.dataset.i18n]; });

const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const errorOf = (data) => data.error || data.detail || 'Request failed';
const key = () => $('apiKey').value.trim();

function showStatus(kind, text) {
    const colors = {ok: 'green', warn: 'yellow', err: 'red'}[kind];
    $('status').className = `mt-6 p-4 rounded-lg bg-${colors}-50 border border-${colors}-200 text-${colors}-900`;
    $('status').textContent = text;
}

async function loadUsage() {
    if (!key()) return;
    try {
        const r = await fetch('/api/me', {headers: {'X-API-Key': key()}});
        if (!r.ok) return;
        const d = await r.json();
        if (d.meetings_this_month === null) { $('usage').textContent = ''; return; }
        $('usage').textContent = d.monthly_limit ? T.usage(d.meetings_this_month, d.monthly_limit) : T.unlimited(d.meetings_this_month);
    } catch (e) { /* sin uso visible */ }
}
$('apiKey').addEventListener('change', loadUsage);

$('testBtn').addEventListener('click', async () => {
    const btn = $('testBtn');
    btn.disabled = true; btn.textContent = T.testing;
    try {
        const r = await fetch('/api/test', {method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-API-Key': key()},
            body: JSON.stringify({webhook_url: $('webhookUrl').value.trim() || null})});
        const d = await r.json();
        d.success ? showStatus('ok', '✅ ' + T.ok) : showStatus('err', '❌ ' + errorOf(d));
    } catch (e) { showStatus('err', '❌ ' + e.message); }
    finally { btn.disabled = false; btn.textContent = T.test; }
});

$('extractBtn').addEventListener('click', async () => {
    const file = $('file').files[0];
    const transcript = $('transcript').value.trim();
    const webhook = $('webhookUrl').value.trim();
    if (!file && !transcript) { showStatus('warn', '⚠️ ' + T.empty); return; }
    const btn = $('extractBtn');
    btn.disabled = true; btn.textContent = T.processing;
    $('results').classList.add('hidden');
    try {
        let r;
        if (file) {
            const form = new FormData();
            form.append('file', file);
            if (webhook) form.append('webhook_url', webhook);
            r = await fetch('/api/extract-file', {method: 'POST', headers: {'X-API-Key': key()}, body: form});
        } else {
            r = await fetch('/api/extract', {method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-API-Key': key()},
                body: JSON.stringify({transcript, webhook_url: webhook || null})});
        }
        const d = await r.json();
        if (!d.success) { showStatus('err', '❌ ' + errorOf(d)); return; }
        d.slack_sent ? showStatus('ok', '✅ ' + T.sent) : showStatus('warn', '⚠️ ' + T.slackFail);
        $('summary').textContent = d.summary || '';
        $('decisions').innerHTML = (d.decisions || []).length
            ? `<h3 class="font-semibold text-gray-900 mb-2">${esc(T.decisions)}</h3><ul class="list-disc pl-5 mb-4 text-sm">` +
              d.decisions.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>' : '';
        $('actionItems').innerHTML = (d.action_items || []).map(i =>
            `<div class="mb-3 p-3 bg-white rounded border-l-4 border-purple-600"><p class="font-semibold text-gray-900">${esc(i.task)}</p>` +
            `<p class="text-sm text-gray-600">👤 ${esc(i.owner)} • 📅 ${esc(i.due_date || i.deadline)}</p></div>`).join('')
            || `<p class="text-gray-600">${esc(T.none)}</p>`;
        $('results').classList.remove('hidden');
        loadUsage();
    } catch (e) { showStatus('err', '❌ ' + e.message); }
    finally { btn.disabled = false; btn.textContent = T.extract; }
});
