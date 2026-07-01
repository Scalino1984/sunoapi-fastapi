import React from 'react';
import { useI18n } from '../i18n/I18nContext.jsx';

function tryParseJsonMessage(value, t = null) {
  const raw = String(value || '').trim();
  if (!raw) return '';

  const candidates = [];
  candidates.push(raw);

  const fenced = raw.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (fenced?.[1]) candidates.push(fenced[1].trim());

  const firstBrace = raw.indexOf('{');
  const lastBrace = raw.lastIndexOf('}');
  if (firstBrace >= 0 && lastBrace > firstBrace) {
    candidates.push(raw.slice(firstBrace, lastBrace + 1));
  }

  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate);
      if (typeof parsed === 'string') {
        if (parsed.trim() !== raw) return tryParseJsonMessage(parsed, t);
        return parsed;
      }
      if (parsed && typeof parsed === 'object') {
        const message = parsed.assistant_message || parsed.message || parsed.reply || parsed.content;
        const summary = parsed.change_summary || parsed.summary;
        const canvasText = parsed.canvas_text;
        const pieces = [];
        if (typeof message === 'string' && message.trim()) pieces.push(message.trim());
        if (typeof summary === 'string' && summary.trim()) pieces.push(`${t?.('formattedMessage.change', 'Änderung') || 'Änderung'}: ${summary.trim()}`);
        if (typeof canvasText === 'string' && canvasText.trim() && !message?.includes(canvasText.trim())) {
          pieces.push(t?.('formattedMessage.canvasPrepared', 'Canvas-Inhalt wurde vorbereitet ({{lines}} Zeilen).', { lines: canvasText.trim().split(/\r?\n/).length }) || `Canvas-Inhalt wurde vorbereitet (${canvasText.trim().split(/\r?\n/).length} Zeilen).`);
        }
        if (pieces.length) return pieces.join('\n\n');
      }
    } catch {
      // Kein JSON, normal weiter rendern.
    }
  }

  return raw;
}

function normalizeMarkdownText(text, t = null) {
  const parsed = tryParseJsonMessage(text, t)
    .replace(/\\n/g, '\n')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n');

  const originalLines = parsed.split('\n');
  const lines = [];

  for (let index = 0; index < originalLines.length; index += 1) {
    const current = originalLines[index];
    const trimmed = current.trim();
    const next = originalLines[index + 1];

    if (/^[-*•]$/.test(trimmed) && next && next.trim()) {
      lines.push(`${trimmed} ${next.trim()}`);
      index += 1;
      continue;
    }

    lines.push(current);
  }

  return lines.join('\n');
}

function renderInlineMarkdown(text, keyPrefix = 'inline') {
  const raw = String(text || '');
  if (!raw) return null;

  const parts = raw.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter((part) => part !== '');

  return parts.map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    return <React.Fragment key={key}>{part}</React.Fragment>;
  });
}

export function FormattedMessage({ text }) {
  const { t } = useI18n();
  const normalized = normalizeMarkdownText(text, t);
  const lines = normalized.split('\n');
  const blocks = [];
  let paragraph = [];
  let listBuffer = [];
  let orderedListBuffer = [];

  function flushParagraph() {
    if (!paragraph.length) return;
    const key = `p-${blocks.length}`;
    blocks.push(
      <p key={key} className="formatted-message-paragraph">
        {paragraph.map((line, index) => (
          <React.Fragment key={`${key}-line-${index}`}>
            {index > 0 && <br />}
            {renderInlineMarkdown(line, `${key}-inline-${index}`)}
          </React.Fragment>
        ))}
      </p>
    );
    paragraph = [];
  }

  function flushUnorderedList() {
    if (!listBuffer.length) return;
    const key = `ul-${blocks.length}`;
    blocks.push(
      <ul key={key} className="formatted-message-list">
        {listBuffer.map((item, index) => (
          <li key={`${key}-${index}`}>{renderInlineMarkdown(item, `${key}-item-${index}`)}</li>
        ))}
      </ul>
    );
    listBuffer = [];
  }

  function flushOrderedList() {
    if (!orderedListBuffer.length) return;
    const key = `ol-${blocks.length}`;
    blocks.push(
      <ol key={key} className="formatted-message-list ordered">
        {orderedListBuffer.map((item, index) => (
          <li key={`${key}-${index}`}>{renderInlineMarkdown(item, `${key}-item-${index}`)}</li>
        ))}
      </ol>
    );
    orderedListBuffer = [];
  }

  function flushLists() {
    flushUnorderedList();
    flushOrderedList();
  }

  lines.forEach((line, index) => {
    const trimmed = line.trim();

    if (!trimmed) {
      flushParagraph();
      flushLists();
      return;
    }

    if (/^[-_]{3,}$/.test(trimmed)) {
      flushParagraph();
      flushLists();
      blocks.push(<hr key={`hr-${index}`} className="formatted-message-rule" />);
      return;
    }

    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushLists();
      const Tag = headingMatch[1].length <= 2 ? 'h4' : 'h5';
      blocks.push(<Tag key={`h-${index}`} className="formatted-message-heading">{renderInlineMarkdown(headingMatch[2], `h-${index}`)}</Tag>);
      return;
    }

    const numberedMatch = trimmed.match(/^(\d+)\.\s+(.+)$/);
    if (numberedMatch) {
      flushParagraph();
      flushUnorderedList();
      orderedListBuffer.push(numberedMatch[2]);
      return;
    }

    const bulletMatch = trimmed.match(/^[-*•]\s+(.+)$/);
    if (bulletMatch) {
      flushParagraph();
      flushOrderedList();
      listBuffer.push(bulletMatch[1]);
      return;
    }

    const quoteMatch = trimmed.match(/^>\s*(.+)$/);
    if (quoteMatch) {
      flushParagraph();
      flushLists();
      blocks.push(<blockquote key={`q-${index}`} className="formatted-message-quote">{renderInlineMarkdown(quoteMatch[1], `q-${index}`)}</blockquote>);
      return;
    }

    flushLists();
    paragraph.push(line);
  });

  flushParagraph();
  flushLists();

  if (!blocks.length) return null;
  return <div className="formatted-message">{blocks}</div>;
}
