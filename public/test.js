const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function handleSubmit(event) {
    event.preventDefault();
    const transcript = document.getElementById('transcript').value;
    const webhook_url = document.getElementById('webhook_url').value;
    const api_key = document.getElementById('api_key').value.trim();
    const resultDiv = document.getElementById('result');
    resultDiv.innerHTML = '<p class="text-blue-600">Processing...</p>';

    try {
        const response = await fetch('/api/extract', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-API-Key': api_key},
            body: JSON.stringify({transcript, webhook_url})
        });
        const data = await response.json();
        
        if (data.success) {
            let html = '<div class="bg-green-100 text-green-700 px-4 py-3 rounded"><p class="font-bold mb-2">✅ Success!</p><p><strong>Summary:</strong> ' + esc(data.summary) + '</p><ul class="list-disc pl-5 mt-2">';
            data.action_items.forEach(item => {
                html += '<li>' + esc(item.task) + ' (Owner: ' + esc(item.owner) + ')</li>';
            });
            html += '</ul></div>';
            resultDiv.innerHTML = html;
        } else {
            resultDiv.innerHTML = '<div class="bg-red-100 text-red-700 px-4 py-3 rounded">❌ Error: ' + esc(data.error || data.detail || 'Request failed') + '</div>';
        }
    } catch (error) {
        resultDiv.innerHTML = '<div class="bg-red-100 text-red-700 px-4 py-3 rounded">❌ Error: ' + esc(error.message) + '</div>';
    }
}

document.getElementById('extractForm').addEventListener('submit', handleSubmit);
