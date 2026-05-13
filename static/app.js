const queryInput = document.getElementById('queryInput');
const sendBtn = document.getElementById('sendBtn');
const stopBtn = document.getElementById('stopBtn');
const documentList = document.getElementById('documentList');
const documentCount = document.getElementById('documentCount');
const uploadForm = document.getElementById('uploadForm');
const pdfUpload = document.getElementById('pdfUpload');
const uploadBtn = document.getElementById('uploadBtn');
const uploadStatus = document.getElementById('uploadStatus');
const sourcesList = document.getElementById('sourcesList');
const answerEl = document.getElementById('answer');
const answerMeta = document.getElementById('answerMeta');
const copyAnswerBtn = document.getElementById('copyAnswerBtn');
const addAnalysisBtn = document.getElementById('addAnalysisBtn');
const clearAnalysisBtn = document.getElementById('clearAnalysisBtn');
const analysisList = document.getElementById('analysisList');
const generateMemoBtn = document.getElementById('generateMemoBtn');
const copyMemoBtn = document.getElementById('copyMemoBtn');
const memoDraft = document.getElementById('memoDraft');

let lastAnswer = '';
let lastQuestion = '';
let lastSources = [];
let analysisItems = [];
let conversationStarted = false;
let currentController = null;

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {'Content-Type': 'application/json'},
    ...options
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || 'Request failed');
  }
  return data;
}

function renderSources(sources) {
  if (!sources || sources.length === 0) {
    sourcesList.className = 'sources-empty';
    sourcesList.textContent = 'No source names returned. Check the answer body for inline citations.';
    return;
  }

  sourcesList.className = '';
  sourcesList.innerHTML = sources.map((source, index) => `
    <div class="source-item">
      <strong>[${index + 1}] ${escapeHtml(source.name)}</strong>
      <span>${escapeHtml(source.type || 'House Journal source')}${source.page ? ` · page ${escapeHtml(source.page)}` : ''}${source.score ? ` · score ${escapeHtml(source.score)}` : ''}</span>
      ${source.snippet ? `<p>${escapeHtml(source.snippet)}</p>` : ''}
    </div>
  `).join('');
}

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
}

function renderMarkdownTable(lines, startIndex) {
  const rows = [];
  let index = startIndex;
  while (index < lines.length && lines[index].trim().startsWith('|')) {
    const cells = lines[index].trim().slice(1, -1).split('|').map(cell => cell.trim());
    rows.push(cells);
    index += 1;
  }

  if (rows.length < 2) return {html: `<p>${inlineMarkdown(lines[startIndex])}</p>`, nextIndex: startIndex + 1};
  const header = rows[0];
  const body = rows.slice(2);
  const html = `
    <div class="answer-table-wrap">
      <table class="answer-table">
        <thead><tr>${header.map(cell => `<th>${inlineMarkdown(cell)}</th>`).join('')}</tr></thead>
        <tbody>
          ${body.map(row => `<tr>${row.map(cell => `<td>${inlineMarkdown(cell)}</td>`).join('')}</tr>`).join('')}
        </tbody>
      </table>
    </div>
  `;
  return {html, nextIndex: index};
}

function renderAnswerMarkdown(text) {
  const lines = String(text || '').split('\n');
  const html = [];
  let listOpen = false;

  function closeList() {
    if (listOpen) {
      html.push('</ul>');
      listOpen = false;
    }
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].trim();
    if (!line) {
      closeList();
      continue;
    }

    if (line.startsWith('|') && lines[i + 1]?.trim().startsWith('|')) {
      closeList();
      const rendered = renderMarkdownTable(lines, i);
      html.push(rendered.html);
      i = rendered.nextIndex - 1;
      continue;
    }

    const heading = line.match(/^\*\*(.+?)\*\*:?$/);
    if (heading) {
      closeList();
      html.push(`<h3>${inlineMarkdown(heading[1])}</h3>`);
      continue;
    }

    const bullet = line.match(/^[*-]\s+(.+)/);
    if (bullet) {
      if (!listOpen) {
        html.push('<ul>');
        listOpen = true;
      }
      html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
      continue;
    }

    closeList();
    html.push(`<p>${inlineMarkdown(line)}</p>`);
  }

  closeList();
  return html.join('');
}

function renderDocuments(data) {
  const documents = data.documents || [];
  documentCount.textContent = `${documents.length} PDF${documents.length === 1 ? '' : 's'}`;

  if (!documents.length) {
    documentList.className = 'document-empty';
    documentList.textContent = data.message || 'No indexed PDFs were returned for this collection.';
    return;
  }

  documentList.className = 'document-list';
  documentList.innerHTML = documents.map((document) => `
    <div class="document-item">
      <strong>${escapeHtml(document.title || document.name)}</strong>
      <span>${escapeHtml(document.type || 'PDF')}${document.date ? ` · ${escapeHtml(document.date)}` : ''}</span>
      <span>${escapeHtml(document.name)}</span>
    </div>
  `).join('');

  if (data.message) {
    const message = document.createElement('div');
    message.className = 'document-message';
    message.textContent = data.message;
    documentList.append(message);
  }
}

async function refreshStatus() {
  await api('/api/status').catch(() => {});
}

async function refreshDocuments() {
  try {
    const data = await api('/api/documents');
    renderDocuments(data);
  } catch (error) {
    documentCount.textContent = 'unavailable';
    documentList.className = 'document-empty';
    documentList.textContent = 'Could not load the indexed document list.';
  }
}

async function ask(question) {
  const clean = question.trim();
  if (!clean) return;
  if (currentController) return;

  lastQuestion = clean;
  if (!conversationStarted) {
    answerEl.className = 'answer chat-thread';
    answerEl.innerHTML = '';
    conversationStarted = true;
  }

  const userMessage = document.createElement('div');
  userMessage.className = 'chat-message user-message';
  userMessage.innerHTML = `<div class="chat-label">You</div><div>${escapeHtml(clean)}</div>`;
  answerEl.append(userMessage);

  const assistantMessage = document.createElement('div');
  assistantMessage.className = 'chat-message assistant-message pending';
  assistantMessage.innerHTML = '<div class="chat-label">Research Assistant</div><div>Searching House Journal passages and preparing a cited answer...</div>';
  answerEl.append(assistantMessage);
  assistantMessage.scrollIntoView({behavior: 'smooth', block: 'nearest'});

  answerMeta.textContent = 'Researching';
  sourcesList.className = 'sources-empty';
  sourcesList.textContent = 'Searching indexed PDFs...';
  currentController = new AbortController();
  sendBtn.disabled = true;
  stopBtn.disabled = false;

  try {
    const data = await api('/api/ask', {
      method: 'POST',
      body: JSON.stringify({question: clean}),
      signal: currentController.signal
    });
    assistantMessage.className = 'chat-message assistant-message';
    assistantMessage.innerHTML = `<div class="chat-label">Research Assistant</div><div>${renderAnswerMarkdown(data.answer)}</div>`;
    assistantMessage.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    answerMeta.textContent = data.mode === 'bill_lookup' ? 'Bill lookup' : 'Sourced research';
    lastAnswer = data.answer;
    lastSources = data.sources || [];
    renderSources(data.sources);
  } catch (error) {
    if (error.name === 'AbortError') {
      assistantMessage.className = 'chat-message assistant-message pending';
      assistantMessage.innerHTML = '<div class="chat-label">Research Assistant</div><div>Stopped. You can ask another question.</div>';
      answerMeta.textContent = 'Stopped';
      sourcesList.className = 'sources-empty';
      sourcesList.textContent = 'No sources returned for the stopped request.';
    } else {
      assistantMessage.className = 'chat-message assistant-message error-message';
      assistantMessage.innerHTML = `<div class="chat-label">Research Assistant</div><div>Error: ${escapeHtml(error.message)}</div>`;
      answerMeta.textContent = 'Error';
    }
  } finally {
    currentController = null;
    sendBtn.disabled = false;
    stopBtn.disabled = true;
    queryInput.focus();
  }
}

function sourceText() {
  if (!lastSources.length) return 'Sources: none returned';
  return `Sources: ${lastSources.map((s, i) => `[${i + 1}] ${s.name}${s.page ? ` p. ${s.page}` : ''}`).join(', ')}`;
}

copyAnswerBtn.addEventListener('click', async () => {
  const text = `${lastQuestion ? `Question: ${lastQuestion}\n\n` : ''}${lastAnswer || answerEl.textContent}\n\n${sourceText()}`;
  await navigator.clipboard.writeText(text);
  copyAnswerBtn.textContent = 'Copied';
  setTimeout(() => {
    copyAnswerBtn.textContent = 'Copy answer';
  }, 1200);
});

addAnalysisBtn.addEventListener('click', () => {
  const answer = lastAnswer || answerEl.textContent.trim();
  if (!answer || answerEl.classList.contains('empty')) return;

  if (analysisList.classList.contains('analysis-empty')) {
    analysisList.className = '';
    analysisList.innerHTML = '';
  }

  const item = document.createElement('div');
  item.className = 'analysis-item';
  item.innerHTML = `
    <h3>${escapeHtml(lastQuestion || 'Research finding')}</h3>
    <pre>${escapeHtml(answer)}\n\n${escapeHtml(sourceText())}</pre>
  `;
  analysisList.prepend(item);
  analysisItems.unshift({
    question: lastQuestion || 'Research finding',
    answer,
    sources: [...lastSources]
  });
});

clearAnalysisBtn.addEventListener('click', () => {
  analysisItems = [];
  analysisList.className = 'analysis-empty';
  analysisList.textContent = 'Use “Add to analysis” after a response to collect findings here.';
  memoDraft.className = 'memo-empty';
  memoDraft.textContent = 'Save one or more findings, then click “Generate bill memo.”';
});

function inferBillTitle() {
  const explicitBillQuestions = analysisItems
    .map(item => item.question)
    .find(question => /\b(HB|SB|HR|SR)\s*[-#]?\s*\d{1,5}\b/i.test(question));
  const billMatch = (explicitBillQuestions || '').match(/\b(HB|SB|HR|SR)\s*[-#]?\s*(\d{1,5})\b/i);
  if (!billMatch) return 'Legislative Research Memo';
  return `${billMatch[1].toUpperCase()} ${billMatch[2]} Research Memo`;
}

function itemBillNumber(item) {
  const billMatch = item.question.match(/\b(HB|SB|HR|SR)\s*[-#]?\s*(\d{1,5})\b/i);
  if (!billMatch) return '';
  return `${billMatch[1].toUpperCase()} ${billMatch[2]}`;
}

function uniqueSources(items) {
  const seen = new Set();
  const sources = [];
  items.forEach(item => {
    item.sources.forEach(source => {
      if (!source.name || seen.has(source.name)) return;
      seen.add(source.name);
      sources.push(source.name);
    });
  });
  return sources;
}

function generateMemo() {
  if (!analysisItems.length) {
    memoDraft.className = 'memo-empty';
    memoDraft.textContent = 'Add at least one answer to the analysis workspace first.';
    return;
  }

  const title = inferBillTitle();
  const primaryBill = title.match(/\b(HB|SB|HR|SR)\s+\d{1,5}\b/i)?.[0] || '';
  const billSpecific = primaryBill
    ? analysisItems.filter(item => itemBillNumber(item) === primaryBill)
    : analysisItems.filter(item => itemBillNumber(item));
  const broaderNotes = primaryBill
    ? analysisItems.filter(item => itemBillNumber(item) !== primaryBill)
    : analysisItems.filter(item => !itemBillNumber(item));
  const memoItems = billSpecific.length ? billSpecific : analysisItems;
  const sources = uniqueSources(analysisItems);
  const body = memoItems.map((item, index) => {
    const itemSources = item.sources.map((s, i) => `[${i + 1}] ${s.name}`).join(', ') || 'none returned';
    return [
      `Finding ${index + 1}: ${item.question}`,
      item.answer,
      `Sources: ${itemSources}`
    ].join('\n');
  }).join('\n\n');

  const broader = broaderNotes.length
    ? broaderNotes.map((item, index) => {
        const itemSources = item.sources.map((s, i) => `[${i + 1}] ${s.name}`).join(', ') || 'none returned';
        return [
          `Context Note ${index + 1}: ${item.question}`,
          item.answer,
          `Sources: ${itemSources}`
        ].join('\n');
      }).join('\n\n')
    : 'No broader context notes were added.';

  const memo = [
    title,
    '',
    'Purpose',
    'Summarize sourced findings from the active indexed Pennsylvania House Journal collection for analyst review.',
    '',
    'Scope',
    primaryBill
      ? `Primary bill focus: ${primaryBill}. Broader saved findings are listed separately below.`
      : 'No single primary bill was detected; this memo summarizes all saved legislative findings.',
    '',
    'Bill-Specific Findings',
    body,
    '',
    'Broader Context Notes',
    broader,
    '',
    'Source List',
    sources.length ? sources.map((source, index) => `[${index + 1}] ${source}`).join('\n') : 'No sources returned.',
    '',
    'Review Notes',
    '- Verify each cited House Journal passage before using this memo externally.',
    '- Fields not present in retrieved passages should remain marked as not found.'
  ].join('\n');

  memoDraft.className = '';
  memoDraft.textContent = memo;
}

generateMemoBtn.addEventListener('click', generateMemo);

copyMemoBtn.addEventListener('click', async () => {
  await navigator.clipboard.writeText(memoDraft.textContent);
  copyMemoBtn.textContent = 'Copied';
  setTimeout(() => {
    copyMemoBtn.textContent = 'Copy memo';
  }, 1200);
});

uploadForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const files = Array.from(pdfUpload.files || []);
  if (!files.length) {
    uploadStatus.textContent = 'Choose one or more PDF files first.';
    return;
  }

  const formData = new FormData();
  files.forEach(file => formData.append('documents', file));
  uploadBtn.disabled = true;
  uploadStatus.textContent = `Uploading ${files.length} PDF${files.length === 1 ? '' : 's'} to the RAG ingestor...`;

  try {
    const response = await fetch('/api/upload', {
      method: 'POST',
      body: formData
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Upload failed');
    uploadStatus.textContent = data.message || 'Upload submitted for ingestion.';
    pdfUpload.value = '';
    refreshDocuments();
  } catch (error) {
    uploadStatus.textContent = `Upload failed: ${error.message}`;
  } finally {
    uploadBtn.disabled = false;
  }
});

sendBtn.addEventListener('click', () => {
  const question = queryInput.value;
  if (question.trim()) {
    queryInput.value = '';
  }
  ask(question);
});

stopBtn.addEventListener('click', () => {
  if (currentController) {
    currentController.abort();
  }
});

queryInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    sendBtn.click();
  }
});

document.querySelectorAll('.example-grid button').forEach((button) => {
  button.addEventListener('click', () => {
    queryInput.value = button.textContent.trim();
    sendBtn.click();
  });
});

refreshStatus();
refreshDocuments();
